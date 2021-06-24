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
import functools
import datetime
import sqlite3
import os
import tempfile

import spawn
import yeshup


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
    if not callable(f):
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
    return x

def get_modules_tests_from_glob(glob_list):

    files = []
    for i in glob_list:
        files = files + glob.glob(i, recursive=True)
    files = list(set(files))

    def gfs(nm):
        try:
            if nm.endswith(".py"):
                nm = nm[0:-3]
            mod = importlib.import_module(nm)
            return get_module_test_tree(mod)
        except:
            print(sys.exc_info()[0])
            traceback.print_exc()
            # todo: better errors
            # send to the monitor process or something
            # they can be shown as warnings in verbose mode
        
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
            case (TestCase(), nm, f):
                modules.append(f.__module__)
                append_line(idt, f"(TestCase(), '{nm}', {f.__module__}.{f.__name__}){e}")
            case _:
                print(f"unrecognised ti {ti}")

    ls = ff(1, tree, False)
    print("from test_framework import TestGroup,TestCase")
    print("import test_framework")
    for i in list(set(modules)):
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

def sysinfo_to_value(e):
    return ("".join(traceback.format_exception(*e, 0)),
            f"{type(e[0])}: {str(e[0])}",
            traceback.extract_tb(e[2]))

# remote test handle allows making test assertions from different
# processes
# it needs to be fixed so there's a test server listening on a tcp/ip
# port instead of the test handle getting a socket
# at the moment it only supports the top level process for each
# test case run concurrently, and not any extra processes
# they launch, which is needed
class RemoteTestHandle(AssertVariations):
    def __init__(self, tid, sock):
        self.tid = tid
        self.sock = sock
    def tpass(self, msg):
        self.sock.send_value(("test_assert", self.tid, msg, True, datetime.datetime.now()))
    def fail(self, msg):
        self.sock.send_value(("test_assert", self.tid, msg, False, datetime.datetime.now()))

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
                print(f"no match for {tree}")
                traceback.print_stack()  
               

    return f(tree, None)
        


##############################################################################

# test runner that supports running each test in a separate process

def testcase_worker_wrapper(tid, nm, f, status_socket):
    #print("start test")
    h = RemoteTestHandle(tid, status_socket)
    try:
        f(h)
    except:
        x = sysinfo_to_value(sys.exc_info())
        # change this to send the message on the socket
        h.fail(f"test suite {nm} failed with uncaught exception {x}")
    finally:
        status_socket.send_value(("end_testcase", tid, datetime.datetime.now()))

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

        
def do_test_run(dbfile, all_tests, glob, test_patterns, hide_successes, num_jobs):

    con = connect_db(dbfile)
    run_script(con, main_ddl)
    
    
    all_tests = discover_tests(all_tests, glob, test_patterns)

    def trace(con,rcd):
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
                if not hide_successes or not passed:
                    s = "PASS" if passed else "FAIL"
                    print(f"  {s} {msg}")
                
            case _:
                print(rcd)


    def summarize():
        print("-----------")
        for r in run_sql(con,"""
select 'FAIL ' || test_case_name || '/' || assertion_message
from test_cases
natural inner join test_assertions
where not status;"""):
            print(r[0])

        for r in run_sql(con,"""
select * from quick_summary
"""):
            print(r[0])

    # in queue is where all the messages coming from the test workers
    # to this process go to be handled in the main process
    in_queue = queue.Queue()

    task_queue =  make_testcase_iterator(all_tests)

    num_running = 0

    def launch_task():
        nonlocal num_running
        try:
            while True:
                t = next(task_queue)
                match t:
                    case ("start_group", gid, nm, parent_id):
                        trace(con, ("start_group", gid, nm, parent_id, datetime.datetime.now()))
                    case ("end_group", gid):
                        trace(con, ("end_group", gid))
                    case (TestCase(), tid, parent_id, nm, fn):
                        trace(con, ("start_testcase", tid, parent_id, nm, datetime.datetime.now()))
                        p = spawn.spawn(functools.partial(testcase_worker_wrapper, t[1], t[3], t[4]))
                        wrap_sock_in(p[1], in_queue)

                        num_running += 1
                        return True
                    case x:
                        print(f"launch task? {x}")
        except StopIteration:
            #print("all tasks done")
            return None

    # start the initial workers
    for _ in range(0,num_jobs):
        x = launch_task()
        if x is None:
            break

    while True:
        x = in_queue.get()
        match x:
            case ("end_testcase", _, _):
                trace(con, x)
                #print("worker finished")
                num_running -= 1
                if launch_task() is None and num_running == 0:
                    break
            case x:
                trace(con, x)

    summarize()
        
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
    parser.add_argument("--num-jobs", "-j", type=int, default=multiprocessing.cpu_count())
    
    args = parser.parse_args()

    if args.generate_source:
        all_tests =  discover_tests(all_tests, args.glob, args.test_pattern)
        create_tests_file(all_tests)
        # ./test_framework.py --generate-source | python3
    else:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'occasional_test_db')
            do_test_run(path, all_tests, args.glob, args.test_pattern, args.hide_successes, args.num_jobs)

if __name__ == "__main__":
    run_main_with_args(None)
