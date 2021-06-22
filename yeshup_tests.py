#!/usr/bin/env python3


"""x

test making sure child processes exit when parent exits
it won't magically continue to children of children right now
  maybe there's a way to make this more likely

This is used internally in the system
it should be used by user processes that are launched unless
you want them to not exit when the system exits (which is probably not
what you should want)
-> todo, create utils for this, in python it's easy to copy a line of code
   document this
   there's the yeshup c program that inspired this, this is good for
     an executable that itselfs takes care of any processes it then
     launches



TODO:

add automated testing to show it all working
add a test which shows the child doesn't exit when deathsig is not set
and it does exit when it is set

then start working through all the options
-> how to run the parent, and the child, etc.
start the parent using subprocess, and using multiprocessing
  is there any other way to start a process from python?
    is this true: the only way to launch processes on linux
      is via fork then exec*
      what about linux clone:
        I think clone is a generalization of threads and fork
          you can specify exactly what is shared and what isn't
          threads and fork are the usual ways to use it
            with fork, you either continue to run the same exe
            in two processes, or you exec in the forked process
              (or maybe in the forker?) and this replaces the exe
              in that process with a new one
              it's fucking weird
      what exactly happens in a shell
      what exactly happens when you launch some threads with
        each one monitoring a process
  test both fork and spawn with multiprocessing
see what happens when you launch through shell in subprocessing
use daemon or not -> both for parent and child
  this is paranoia check for weird stuff in the python implementation
vary how the parent exits
  -> python exit, os._exit
     uncaught exception
     try all the different signals
try grandchildren processes
demonstrate if a grandchild launch doesn't participate in the yeshup,
  it won't be cleaned up


recreate and test the original yeshup wrapper so it runs an arbitrary
exe

test yeshup works with the various multiprocessing spawn options

"""

import time
import datetime
import sys
import subprocess
import os
import multiprocessing
import threading
import queue
import signal
import yeshup

def run_it(cmd):
    p = subprocess.Popen(cmd)
    p.communicate()
    code = p.wait()
    return code

def run_it_stdin(cmd):
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    return p

def close_stdin(p):
    #p.stdin.close()
    p.communicate()
    code = p.wait()
    return code

def is_process_running(pid):
    try:
        os.kill(pid,0)
        return True
    except ProcessLookupError:
        return False
    
def test_simple_yeshup(trp):
    #print("run basic")
    #x = run_it([sys.argv[0], "launch", "basic"])
    #print(f"exit code: {x}")

    # start the main process in a thread, this will block
    # then can exit it asynchronously

    get_pid_queue = queue.Queue()
    
    def run_parent():
        #print("run parent")
        p = run_it_stdin(["./yeshup_tests.py", "launch", "basic"])
        #p.wait()
        #print("launched")
        # parse the two pids
        for line in p.stdout:
            #print(line)
            line = str(line, 'ascii')
            #print("here")
            #print(type(line))
            if line.startswith("parent pid:"):
                parent_pid = int(line[11:])
                break
            else:
                print(line)
        for line in p.stdout:
            line = str(line, 'ascii')
            #print("here")
            #print(type(line))
            if line.startswith("child pid:"):
                child_pid = int(line[10:])
                break
            else:
                print(line)
        #print((parent_pid, child_pid))
        get_pid_queue.put((parent_pid, child_pid))
        for line in p.stdout:
            print(line)
        p.wait()


    # need to get the stdout back from the run parent
    parent_runner_thread = threading.Thread(target=run_parent)
    parent_runner_thread.start()

    #print("queue get")
    (parent_pid,child_pid) = get_pid_queue.get()

    if trp is None:
        # display if they are running
        print(f"parent: {parent_pid} running {is_process_running(parent_pid)}")
        print(f"child: {child_pid} running {is_process_running(child_pid)}")
    else:
        trp.assert_true(f"parent running ", is_process_running(parent_pid))
        trp.assert_true(f"child running ", is_process_running(child_pid))
    # exit the process
    #c = close_stdin(p)

    #print("kill")
    os.kill(parent_pid, signal.SIGTERM)
    parent_runner_thread.join()
    
    # p.wait()
    # display again if the two processes are running

    # the child doesn't always exit fast enough without this
    # it's only needed for reliable automated testing
    time.sleep(0.01)

    if trp is None:
        print(f"parent: {parent_pid} running {is_process_running(parent_pid)}")
        print(f"child: {child_pid} running {is_process_running(child_pid)}")
    else:
        trp.assert_false(f"parent not running ", is_process_running(parent_pid))
        trp.assert_false(f"child not running ", is_process_running(child_pid))
    #return c
    

def launch_basic():
    #print("launch basic")
    print(f"parent pid: {os.getpid()}", flush=True)
    def child_process():
        # this is the line which makes sure the child exits
        # when the parent does. it has to be run in the child process
        # to make this more general, can call this then call exec*
        # it's reset on fork, but not on exec*

        yeshup.yeshup_me()
        print(f"child pid: {os.getpid()}", flush=True)
        #sys.stdout.flush()
        #for line in sys.stdin:
        #    print(line)
        time.sleep(100)
        #print("here")
    p = multiprocessing.Process(target=child_process)
    p.start()
    p.join()
    #print("exiting launch basic")

if __name__ == "__main__":
    # check the args, see if this is the launcher or the testing exe
    # you can run the test standalone if you use
    # ./yeshup_test basic

    if sys.argv[1] == "basic":
        test_simple_yeshup(None)
    elif sys.argv[1] == "launch" and sys.argv[2] == "basic":
        launch_basic()
            
     
            

