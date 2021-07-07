#!/usr/bin/env python3

"""x

A test framework which supports test results from multiple concurrent
processes

This code is very temporary atm

Planned:
run in the occasional system - should fix a bunch of issues
run tests distributed
logging and reports
profiling support
timeout support
support for running tests written in other frameworks using adaptors
  (the adaptors run the other tests' executables and get the results
   either from stdout/stderr or the log produced from the test runs)


running tests from the command line
-----------------------------------

run all tests in current dir:

> test_framework.py 

Run tests matching at least one of the regexes given. A test will
match if the pattern matches the name of the module containing the
test or the name of the function for the test. Later it will match the
test name or any of the test groups the test is in.

> test_framework.py  -t test_trivial_sockets test_socket_accept_exit
> test_framework.py  -t inbox_tests

test without using the server, this will only work if the none of the
test assertions run in other processes

> test_framework.py --use-local

other options: hide success lines, show times for every test

> test_framework.py -t --hide-successes --show-times


writing tests
-------------

def test_simple(trp):
    a = 5
    b = test_this_function(2,3)
    assert_equal(trp, "my assertion message", a, b)

tests are found by looking for all the functions named test_*
you can also specific the list of tests manually

see the _tests.py files for examples




TODO: tests for the test framework:

check running a test case
check running two test cases
check running two test modules
check autodiscovery run
test pattern filtering
globbing
check all the basic assertion variations
check a test case with an uncaught exception
check generating a static file and then running it
check the output
check any other command line options
test when there are no discoverable test modules
test when the pattern doesn't match any tests


"""
import datetime
test_run_start_time = datetime.datetime.now()

import inspect
import types
import glob
import importlib
import sys
import traceback
import argparse
import re
import queue
import multiprocessing
import threading
import sqlite3
import os
import tempfile
import signal
from multiprocessing import cpu_count

import functools
bind = functools.partial

import occ.sck as sck
import occ.spawn as spawn
import occ.yeshup as yeshup
from occ.utils import sort_list, format_exception

from tblib import pickling_support
pickling_support.install()

##############################################################################

# wrap the confusing python dbi api

def connect_db(cs):
    dbconn = sqlite3.connect(cs)
    dbconn.isolation_level = None
    return dbconn

def run_script(dbconn, sql):
    cur = dbconn.cursor()
    r = cur.executescript(sql)
    return r

def run_sql(dbconn, sql, args=None):
    cur = dbconn.cursor()
    if args is None:
        cur.execute(sql)
    else:
        cur.execute(sql, args)
    return cur.fetchall()

def run_sql_1(dbconn, sql, args=None):
    r = run_sql(dbconn, sql, args)
    if len(r) == 1:
        return r[0]
    else:
        raise Exception(f"run sql 1 {sql} {args} returned {len(r)} rows, expecting 1 row")

##############################################################################

# setup for the database
# this is just a really quick easy way to log the results as it executes
# and then summarize them at the end

main_ddl = """

-- PRAGMA foreign_keys = ON;

-- speed up this slow motherfucker
-- only using a file because want to update from multiple threads/processes
-- switching to a file and turning on autocommit so multiple threads could
-- update without getting deadlocked made it much slower, this speeds it up again
-- this will need revisiting later when want persistence for logged test
-- data in the presence of test framework crashes

PRAGMA JOURNAL_MODE = OFF;
PRAGMA SYNCHRONOUS = OFF;


--create table test_runs (
--   test_run_id integer primary key not null,
--   test_run_start timestamp not null,
--   test_run_end timestamp
---- todo: maybe add machine id, invocation options, etc.
--)
   
create table groups (
    group_id integer primary key not null,
    --test_run_id integer not null, -- references test_runs,
    group_name text not null,
    parent_group_id integer, -- references groups (group_id),
    start_time timestamp not null,
    open bool
);

create table test_cases (
    test_case_id integer primary key not null,
    test_case_name text not null,
    parent_group_id integer not null, -- references groups (group_id),
    start_time timestamp not null,
    end_time timestamp,
    open bool
);
create table test_assertions (
    assertion_id integer primary key not null,
    assertion_message text not null,
    test_case_id integer not null, -- references test_cases,
    atime timestamp not null,
    status bool not null -- true == pass
);



-- test cases with the num asserts, num passed, and end times
create view test_case_extras as
select test_cases.*,
            sum(1) as num_asserts,
            coalesce(sum(1) filter (where status),0) as num_passed_asserts,
            max(atime) as end_time
     from test_assertions
     natural inner join test_cases
     group by test_case_id;

-- groups with the num direct test cases and test cases passed
-- todo: use with recursive to add the num groups and num groups passed
-- and to add the end times
create view group_extras as
select groups.*,
       sum(1) as num_test_cases,
       coalesce(sum(1) filter (where num_asserts = num_passed_asserts), 0) as num_passed_test_cases
from test_case_extras
inner join groups
on (groups.group_id = test_case_extras.parent_group_id)
group by test_case_extras.parent_group_id;

-- quick summary hack
create view quick_summary as
with tas as (
select sum(1) filter (where status)
       || ' / ' || sum(1) as ta
from test_assertions),
tcs as (
select sum(1) filter (where num_asserts = num_passed_asserts)
       || ' / ' || sum(1) as tc
from test_case_extras)
select tc || ' test cases,  ' || ta || ' assertions'
from tas cross join tcs
;
/*
todo:

do a list with group ids going up to the top
+ the test case id
then can use this to generate the text of the group path and the test case
  through to the assertion

*/


"""


##############################################################################

# test item types

class TestGroup:
    def __eq__(self, other):
        return isinstance(other, TestGroup)

class TestCase:
    def __eq__(self, other):
        return isinstance(other, TestCase)

# used for reporting errors loading test code
class FailTestCaseBody:
    def __init__(self, msg):
        self.msg = msg
    

def make_test_group(nm, ts):
    if not type(nm) is str:
        raise Exception(f"make test group not string: {nm}")
    if not type(ts) is list:
        raise Exception(f"make test group not list: {ts}")
    for i in ts:
        if not (type(i) is tuple and len(i) == 3):
            raise Exception(f"make test group not testitem: {i}")
        if not (type(i[0]) is TestGroup or type(i[0]) is TestCase):
            raise Exception(f"make test group not testitem: {i}")
    #check ts are a list of testgroups/testcases
    return (TestGroup(), nm, ts)

def make_test_case(nm, f):
    if not type(nm) is str:
        raise Exception(f"make test case not string: {nm}")
    if not callable(f) and type(f) is not FailTestCaseBody:
        raise Exception(f"make test case not callable: {f}")
    return (TestCase(), nm, f)

##############################################################################

# test discovery
# -> going from the source code to a test item tree

# function to get the tests from a module
# first, look for the all_tests value
# if it's missing, look for all the top level XX_test functions

def get_module_test_tree(mod):
    try:
        x = getattr(mod, "all_tests")
        return x
        # todo: check the type
    except AttributeError:
        pass
    tfs = [getattr(mod,x) for x in dir(mod)
           if x.startswith('test_')]
    if tfs == []:
        return None
    tcs = [make_test_case(tf.__name__, tf) for tf in tfs]
    x = make_test_group(mod.__name__, tcs)
    # TODO: get the test case functions in the order they are in the
    # source file
    return x

def get_modules_tests_from_glob(glob_list):

    files = []
    for i in glob_list:
        files = files + glob.glob(i, recursive=True)
    files = sort_list(list(set(files)))

    def gfs(nm):
        mod = None
        try:
            nm0 = nm
            if nm.endswith(".py"):
                nm = nm[0:-3]
            nm = nm.replace('/', '.')
            mod = importlib.import_module(nm)
            ts = get_module_test_tree(mod)
            if ts is None:
                msg = f"no tests found in {nm0}"
                return make_test_group(nm, [make_test_case("no_tests_found",
                                                           FailTestCaseBody(msg))])
            else:
                return ts
        except:
            nm = mod if mod is not None else nm
            msg = format_exception(sys.exc_info()[1])
            return make_test_group(nm, [make_test_case("load_failed",
                                                       FailTestCaseBody(msg))])
        
    ts = [gfs(nm) for nm in files]
    ts = [t for t in ts if t is not None]
    # todo: if ts has one element, don't wrap it in a group
    return make_test_group("all_tests", ts)


# keep only tests matching the regexes
# any empty groups are removed completely

def filter_test_tree(tree,regs):
    x = filter_test_treex(tree,regs)
    return (TestGroup(), "all_tests", []) if x is None else x

def filter_test_treex(tree, regs):
    if regs == []:
        return tree
    match tree:
        case (TestCase(), nm, f):
            for r in regs:
                if r.search(nm):
                    return tree
            return None
        case (TestGroup(), nm, ts):
            for r in regs:
                if r.search(nm):
                    return tree
            ts1 = [filter_test_treex(t, regs) for t in ts]
            ts2 = [t for t in ts1 if t is not None]
            if ts2 == []:
                return None
            else:
                return (TestGroup(), nm, ts2)

"""

TODO:
turn all this into iterators
the main thing is to load modules on demand which will allow tests
to start executing sooner if there are a lot of modules or some
modules have a slow load time
decide what to do with the multiple globs better
  -> want to iterate here too

think about the trace messages from test discovery
  -> for profiling and troubleshooting

postponed for now because with a small number of tests it makes no
real difference

"""
            
##############################################################################

# generating python code from a test tree value
# main use is to run tests using static imports instead of the dynamic
# loader, this is for sanity purposes

def create_tests_file(tree):
    modules = []
    lines = []
   
    def append_line(idt, l):
        lines.append(f"{' ' * idt * 4}{l}")

    append_line(0, "all_tests = \\")
    
    def ff(idt, ti, ctu=True):
        nonlocal modules, lines
        e = ',' if ctu else ''
        match ti:
            case (TestGroup(), nm, tis):
                append_line(idt, f"(TestGroup(), '{nm}', [")
                for i in tis:
                    ff(idt + 1, i)
                append_line(idt, f"]){e}")
            case (TestCase(), nm, FailTestCaseBody()):
                append_line(idt, f'(TestCase(), "{nm}", FailTestCaseBody("""{ti[2].msg}"""))')
            case (TestCase(), nm, f):
                modules.append(f.__module__)
                append_line(idt, f"(TestCase(), '{nm}', {f.__module__}.{f.__name__}){e}")
            case _:
                logger.error(f"test_framework: unrecognised ti {ti}")

    ls = ff(1, tree, False)
    print("from test_framework import TestGroup,TestCase,FailTestCaseBody")
    print("import test_framework")
    for i in sort_list(list(set(modules))):
        print(f"import {i}")
    for i in lines:
        print(i)
    print("""
if __name__ == "__main__":
    test_framework.run_main_with_args(all_tests)
""")
            

######################################

# test case execution


class AssertVariations():
    def assert_equal(self, msg, exp, got):
        if exp == got:
            self.tpass(msg)
        else:
            self.fail(f"{msg} expected {exp} got {got}")

    def assert_true(self, msg, b):
        if b:
            self.tpass(msg)
        else:
            self.fail(msg)

    def assert_false(self, msg, b):
        if b:
            self.fail(msg)
        else:
            self.tpass(msg)
            
    def assert_pred(self, msg, pred, v):
        if pred(v):
            self.tpass(msg)
        else:
            self.fail(f"{msg} failed predicate: {v}")

# remote test handle allows making test assertions from different
# processes
class RemoteTestHandle(AssertVariations):
    def __init__(self, tid, addr):
        self.tid = tid
        self.addr = addr
        self.sock = sck.connected_socket(self.addr)
        self.my_pid = os.getpid()
    def check_connection(self):
        if os.getpid() != self.my_pid:
            self.sock = sck.connected_socket(self.addr)
    def tpass(self, msg):
        self.check_connection()
        self.sock.send_value(("test_assert", self.tid, msg, True, datetime.datetime.now()))
    def fail(self, msg):
        self.check_connection()
        self.sock.send_value(("test_assert", self.tid, msg, False, datetime.datetime.now()))

    def __getstate__(self):
        attributes = self.__dict__.copy()
        del attributes['sock']
        return attributes

    def __setstate__(self, state):
        self.__dict__ = state
        self.sock = sck.connected_socket(self.addr)

        
##############################################################################

# discover tests
# todo: make this an iterator, combine with the get_modules stuff
# move the regex testing to the make testcase iterator

def discover_tests(all_tests, glob, test_patterns):
    if all_tests is None:
        all_tests = get_modules_tests_from_glob(glob)
    test_patterns_re = []
    for i in test_patterns:
        test_patterns_re.append(re.compile(i))
    all_tests = filter_test_tree(all_tests, test_patterns_re)
    return all_tests

def make_testcase_iterator(tree):
    ctr = 0
    def new_ctr():
        nonlocal ctr
        r = ctr
        ctr += 1
        return r

    def f(ti, parent_id):
        match ti:
            case (TestGroup(), nm, tis):
                gid = new_ctr()
                yield ("start_group", gid, nm, parent_id)
                for ti in tis:
                    yield from f(ti, gid)
                yield ("end_group", gid)
            case (TestCase(), nm, fn):
                tid = new_ctr()
                yield (TestCase(), tid, parent_id, nm, fn)
            case _:
                logger.error(f"test_framework: no match for {tree}")
               

    return f(tree, None)
        


##############################################################################

# test runner that supports running each test in a separate process

@pickling_support.install
class TimeoutException(Exception):
   pass

def alarm_handler(signum, frame):
    raise TimeoutException()
    
def testcase_worker_wrapper(tid, nm, f, addr, ig=None, timeout=1):
    x = None
    h = RemoteTestHandle(tid, addr)
    try:
        try:
            signal.signal(signal.SIGALRM, alarm_handler)
            signal.alarm(timeout)
            f(h)
            signal.alarm(0)
        except TimeoutException:
            h.fail(f"test suite {nm} timed out after {timeout}s")
        except:
            x = sys.exc_info()[1]
            h.fail(f"test suite {nm} failed with uncaught exception {format_exception(x)}")
    except TimeoutException:
        # double up here in case another exception is thrown
        # and we catch it in time, but then the alarm goes off
        # we want to make sure the exception doesn't leak, so we
        # don't have any races where the suite exception doesn't
        # get reported
        if x is None:
            h.fail(f"test suite {nm} timed out after {timeout}s")
    finally:
        h.sock.send_value(("end_testcase", tid, datetime.datetime.now()))

# reads values from the sock and posts them to the queue, in a
# background thread
# temp until move to using occasional in the test framework
def wrap_sock_in(sock, q):
    def post_it(sock,q):
        while True:
            x = sock.receive_value()
            if x is None:
                break
            q.put(x)
    t = threading.Thread(target=post_it, args=[sock,q], daemon=True)
    t.start()

# trace helper gets results on a socket
# and writes progress report and logs to db

# todo: could definitely optimise this a lot if doing tons of little queries
# like this becomes an issue
def test_case_path(con, tid):
    p = []
    (tnm, prid) = run_sql_1(con,"select test_case_name, parent_group_id from test_cases where test_case_id=?", [tid])
    p.insert(0,(tnm))
    while True:
        if prid is None:
            break
        (par, prid) = run_sql_1(con,"select group_name, parent_group_id from groups where group_id=?", [prid])
        p.insert(0,par)
    return "/".join(p)

def trace(con, hide_successes, rcd):
    """
TODO:
consider logging the traces
and then only inserting after finishing
maybe also do this 'offline', e.g. on another machine
so you can run tests super light and then load the data
into a central database later

"""
    match rcd:
        case ('start_group', gid, nm, parent_id, starttime):
            run_sql(con,"""
insert into groups(group_id, group_name, parent_group_id, start_time, open)
values(?, ?, ?, ?, true)""", (gid, nm, parent_id, starttime))
        case ('end_group', gid):
            run_sql(con,"update groups set open = false where group_id=?", (gid,))
        case ("start_testcase", tid, gid, nm, starttime):
            run_sql(con,"""
insert into test_cases(test_case_id, test_case_name, parent_group_id, start_time, open)
values (?, ?, ?, ?, true)""", (tid, nm, gid, starttime))
        case ('end_testcase', tid, endtime):
            run_sql(con,"""
update test_cases
set end_time = ?, open = false
where test_case_id = ?""", (endtime, tid))
        case ("test_assert", tid, msg, passed, tm):
            run_sql(con,"""
insert into test_assertions(assertion_message, test_case_id, atime, status)
values(?,?,?,?)""", (msg, tid, tm, passed))
            if passed and not hide_successes:
                tcp = test_case_path(con, tid)
                print(f"  PASS {tcp} {msg}")
            elif not passed:
                tcp = test_case_path(con, tid)
                print(f"  FAIL {tcp} {msg}")
        case _:
            logger.error(f"test_framework: trace got {rcd}")

# quick summary at end of run, to be expanded
def summarize(con, hide_successes):
            print("-----------")
            ctid = None

            if not hide_successes:
                for r in run_sql(con,""" 
with failed_test_cases as (
  select test_case_id
  from test_cases
  natural inner join test_assertions
  where not status)
select test_case_id
from test_cases
where test_case_id not in (select test_case_id from failed_test_cases)
order by test_case_id
"""):
                    print(f"PASS {test_case_path(con, r[0])}")
            
            for r in run_sql(con,"""
select test_case_id, assertion_message
from test_assertions
natural inner join test_cases
where not status
order by test_case_id;"""):
                (tid, msg) = r
                if tid != ctid:
                    print(f"FAIL {test_case_path(con, tid)}")
                    ctid = tid
                print(f"  {msg}")

            print("-----------")

            for r in run_sql(con,"""
    select * from quick_summary
    """):
                et = (datetime.datetime.now() - test_run_start_time).total_seconds()
                print(f"{r[0]} in {et:0.2f}s")

        
def do_test_run(all_tests, glob, test_patterns, hide_successes, num_jobs):
    with tempfile.TemporaryDirectory() as tmp:
        # connect and load the ddl into the database
        dbfile = os.path.join(tmp, 'occasional_test_db')
        con = connect_db(dbfile)
        run_script(con, main_ddl)
        
        all_tests = discover_tests(all_tests, glob, test_patterns)
        if len(all_tests) == 0:
            return

        ttrace = bind(trace,con,hide_successes)
        # in queue is where all the messages coming from the test workers
        # to this process go to be handled in the main process
        in_queue = queue.Queue()

        def test_server_handle(sock, _):
            while True:
                x = sock.receive_value()
                if x is None:
                    break
                in_queue.put(x)
        
        srv = sck.make_socket_server(test_server_handle, daemon=True)
        
        task_queue =  make_testcase_iterator(all_tests)

        def trace_usual(t):
            match t:
                case ("start_group", gid, nm, parent_id):
                    ttrace(("start_group", gid, nm, parent_id, datetime.datetime.now()))
                case ("end_group", gid):
                    ttrace(("end_group", gid))
                case (TestCase(), tid, parent_id, nm, fn):
                    ttrace(("start_testcase", tid, parent_id, nm, datetime.datetime.now()))
                case x:
                    logger.error(f"test_framework: {x}")

        num_running = 0

        def launch_task():
            nonlocal num_running
            try:
                while True:
                    t = next(task_queue)
                    trace_usual(t)
                    match t:
                        case (TestCase(), tid, parent_id, nm, FailTestCaseBody()):
                            f = lambda trp: trp.fail(t[4].msg)
                            p = spawn.spawn(bind(testcase_worker_wrapper, t[1], t[3], f, srv.addr))
                            num_running += 1
                            return True
                        case (TestCase(), tid, parent_id, nm, fn):
                            p = spawn.spawn(bind(testcase_worker_wrapper, t[1], t[3], t[4], srv.addr))
                            num_running += 1
                            return True
            except StopIteration:
                #print("all tasks done")
                return None
        # start the initial workers
        for _ in range(0,num_jobs):
            x = launch_task()
            if x is None:
                break

        # hack to make it exit when there are no tests
        in_queue.put("finish")

        while True:
            x = in_queue.get()
            match x:
                case ("end_testcase", _, _):
                    ttrace(x)
                    #print("worker finished")
                    num_running -= 1
                    if launch_task() is None and num_running == 0:
                        break
                case "finish":
                    if num_running == 0:
                        break
                case x:
                    ttrace(x)

        summarize(con, hide_successes)
        
##############################################################################

# command line handler

def run_main_with_args(all_tests = None):
    parser = argparse.ArgumentParser()

    # a test will be run if it's name or any of the names of it's parent groups
    # match (re.search in python), or if there are no test patterns
    parser.add_argument('--test-pattern', '-t', nargs='+', default=[])
    # this specifies which py files to look for tests in
    parser.add_argument('--glob', '-g', nargs='+', default=['*.py'])
    parser.add_argument("--hide-successes", action='store_true', default=False)
    parser.add_argument("--show-times", action='store_true', default=False)
    parser.add_argument("--generate-source", action='store_true', default=False)
    parser.add_argument("--num-jobs", "-j", type=int, default=cpu_count())
    
    args = parser.parse_args()

    if args.generate_source:
        all_tests =  discover_tests(all_tests, args.glob, args.test_pattern)
        create_tests_file(all_tests)
        # ./test_framework.py --generate-source | python3
    else:
        do_test_run(all_tests, args.glob, args.test_pattern, args.hide_successes, args.num_jobs)

if __name__ == "__main__":
    run_main_with_args(None)
