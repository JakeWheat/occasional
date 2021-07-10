
import occ.sysquery as sysquery
import os
import functools
bind = functools.partial
from occasional import send, receive, spawn, slf, spawn_monitor
import occasional
import time
import traceback


# TODO: make sure to check the types returned from sysquery functions
# carefully

def subtract_list(a, b):
    aa = a.copy()
    for e in b:
        aa.remove(e)
    return aa

def test_simple_fdinfo(trp):
    snapshot = list(sysquery.fdinfo(os.getpid()))
    def is_pts(fileno,x):
        return x[1] == fileno and x[2].startswith("/dev/pts/")
    def is_fileno_path(fileno,path,x):
        return x[1] == fileno and x[2] == path

    def contains_if(prd, lst):
        return next(filter(prd, lst), None) is not None
    
    trp.assert_true("has stdin",
                    contains_if(bind(is_pts, 0), snapshot))
    trp.assert_true("has stdout",
                    contains_if(bind(is_pts, 1), snapshot))
    trp.assert_true("has stderr",
                    contains_if(bind(is_pts, 2), snapshot))

    f = open("/tmp/xyx", "w")
    snapshot2 = list(sysquery.fdinfo(os.getpid()))
    diff = subtract_list(snapshot2, snapshot)
    match diff:
        case [(_,_,"/tmp/xyx",None)]:
            trp.tpass("check opened file")
        case _:
            trp.fail(f'check opened file expected [(_,_,"/tmp/xyx",None)], got {diff}')
    f.close()
    snapshot3 = list(sysquery.fdinfo(os.getpid()))
    trp.assert_equal("after file closed", snapshot, snapshot3)

def test_process_name(trp):
    # also tests we get a nice process name for the test case
    # and for spawned processes

    # todo: temporarily broken, will be fixed when test framework is refactored
    # to use occasional
    #trp.assert_true("test case name", "test_process_name" in sysquery.process_name(os.getpid()))
    #trp.assert_true("test case name", "test_process_name" in sysquery.process_name(0))

    def my_spawned_process(trp):
        trp.assert_true("my_spawned_process name", "my_spawned_process" in sysquery.process_name(0))
        time.sleep(1)

    def my_toplevel_process(trp):
        trp.assert_true("my_toplevel_process name", "my_toplevel_process" in sysquery.process_name(0))
        x = occasional.spawn(bind(my_spawned_process, trp))

    occasional.run(bind(my_toplevel_process,trp))

def test_processes_in_group(trp):
    snapshot = list(sysquery.pids_in_group(0))
    x = list(sysquery.pids_in_group(os.getpgid(0)))
    trp.assert_equal("current process group default", snapshot, x)

    def my_spawned_process(ret, trp):
        try:
            send(ret, os.getpid())
            receive()
        except:
            print("inner")
            traceback.print_exc()
        finally:
            #print("inner exiting")
            pass
        

    def my_toplevel_process(trp):
        ps = list(sysquery.pids_in_group(0))
        trp.assert_true("added process", os.getpid() in ps)
        try:
            #print(1)
            (sub,_) = spawn_monitor(bind(my_spawned_process, slf(), trp))
            #print(2)
            subpid = receive()
            #print(3)
            ps = list(sysquery.pids_in_group(0)) 
            #print(4)
            trp.assert_true("added process", subpid in ps)
            #print(5)
            send(sub, "exit")
            #print(6)
            receive()
            #print(7)

            ps = list(sysquery.pids_in_group(0))
            #print(8)
            trp.assert_true("process removed", subpid not in ps)

            #print("here")
            #return os.getpid()
        
            # get the sub pid, then wait for it to exit
            # check processes
            #time.sleep(1)
        except:
            print("EXCEPT")
            traceback.print_exc()

    occasional.run(bind(my_toplevel_process,trp))
    x = list(sysquery.pids_in_group(os.getpgid(0)))
    trp.assert_equal("processes after completing", snapshot, x)

"""
socket testing:


check getting a list of (tcp|unix,listen|connected)
-> make a new compound _df function
you pass in pid
it returns the open files only including ones which correspond
to sockets
it returns
pid, fileno, socket_inode, socket type (tcp or unix),
  connection or listening,
  for local connections, also: remote pid, remote inode
  for tcp: port
  for unix: path if there is one
do one for just the connection/listen + unix|tcp
  if it means reading less of proc

create a tcp server
create a unix server
create a socket pair
launch a new process
  connect it to both servers
then can start playing around with the info to get what want
then implement the tests


create some 

get the list of current sockets, it will vary depending on how the
tests are run, use this as the baseline. assume these won't change
during the test run for any implicit reason

start with creating a socketpair
check the change in sockets

then create a server
check the change in sockets

make one connection, check
make another, check
disconnect first, check
disconnect second, check
stop listener, check
"""

"""
check creating a server, connecting to it
and checking can see the specific processes connected + listening with
  the correct port/path - both with tcp and unix

"""
