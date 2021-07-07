

"""
test plan:

start with simple demos:
run process with multiprocessing
  exit with 0, exit with non 0, use signal to exit
  -> capture and check these values
then do the same with an external exe

the add a socket connection
show:
the above cases
exiting with an arbitrary python value by returning from the function
  -> set up a simple spawn wrapper for this
exiting with arbitrary python value by using the exit function
exiting using an error function to show the exit value includes a stack trace
same but using an uncaught exception escaping the spawned function

each non exe test will work:
  spawn a python function
  call wait on the return value from spawn
  this gives the 'exit value' of the spawned process
for the exe, use a spawn_exe function which takes a command line to run
  apart from that it works the same (but will only be able to return
    linux integer exit codes or signals)
"""

from occ.spawn import *

import os
import sys
import time
import functools
bind = functools.partial
from tblib import pickling_support

# simple exits from a python function

def spawn_ignore(f):
    def ignore_f(f, _):
        return f()
    return spawn(bind(ignore_f, f))
        

def helper_test_function(trp, msg, f, v, ex):
    x = spawn_ignore(f)
    res = wait_spawn(x)
    match res:
        case ("process-exit", _, a, b) if v==a and ex==b:
            trp.tpass(msg)
        case _:
            trp.fail(f"{msg}: expected {('process-exit', '_', v, ex)}, got {res}")

def test_leave_function(trp):
    def f():
        pass
    helper_test_function(trp, "leave function exit code", f, "ok", ("exitcode", 0))

def test_python_exit_0(trp):
    def f():
        sys.exit()
    helper_test_function(trp, "sys.exit()", f, "ok", ("exitcode", 0))
    

def test_linux_exit_0(trp):
    def f():
        os._exit(0)
    helper_test_function(trp, "os._exit(0)", f, "ok", ("exitcode", 0))


def test_python_exit_non_zero(trp):
    def f():
        sys.exit(1)
    helper_test_function(trp, "sys.exit(1)", f, "error", ("exitcode", 1))

def test_linux_exit_non_zero(trp):
    def f():
        os._exit(1)
    helper_test_function(trp, "os._exit(1)", f, "error", ("exitcode", 1))

def test_sigterm(trp):
    def f():
        time.sleep(1000)
        
    x = spawn_ignore(f)
    os.kill(get_spawn_pid(x), signal.SIGTERM)
    res = wait_spawn(x)
    trp.assert_equal("sigterm",
                     ("process-exit", get_spawn_pid(x),
                      "error", ('signal', 'Terminated')),
                     res)

def test_sigkill_0(trp):
    def f():
        time.sleep(1000)
        
    x = spawn_ignore(f)
    os.kill(get_spawn_pid(x), signal.SIGKILL)
    res = wait_spawn(x)
    trp.assert_equal("sigkill",
                     ("process-exit", get_spawn_pid(x),
                      "error", ('signal', 'Killed')),
                     res)

    
# TODO: spawn an exe versions
def test_exe_exit_0(trp):
    pass

def test_exe_exit_non_zero(trp):
    pass

def test_exe_sigterm(trp):
    pass

def test_exe_sigkill(trp):
    pass

# exits which use the socket connection for the exit value
def test_return_from_function(trp):
    def f():
        return "bye"
    helper_test_function(trp, "return value", f, "ok", "bye")

def test_exit_value_function_0(trp):
    def f():
        spawn_exit(0)
    # exiting with an integer value is distinguishable
    # from the process exiting with os exit code 0
    helper_test_function(trp, "exit value function", f, "ok", 0)

def test_exit_value_function_non_trivial(trp):
    def f():
        spawn_exit("bye also")
    helper_test_function(trp, "exit value function", f, "ok", "bye also")

@pickling_support.install
class Tedious(Exception):
    def __init__(self,msg):
        self.msg = msg

    
def test_uncaught_exception(trp):
    def f():
        raise Tedious("hi")
    x = spawn_ignore(f)
    res = wait_spawn(x)
    match res:
        case ("process-exit", _, "error", e):
            trp.assert_equal("exception class", Tedious, type(e))
            trp.assert_equal("exception value", "hi", e.msg)
            # no idea how to get the actual type
            trp.assert_true("stacktrace", "traceback" in str(type(e.__traceback__)))
        case _:
            trp.fail(f"expected ('error', Tedious, str), got {res}")


def test_error_function(trp):
    def f():
        spawn_error("wheee")
    x = spawn_ignore(f)
    res = wait_spawn(x)
    match res:
        case ("process-exit", _, "error", e):
            trp.assert_equal("error exit", "wheee", e.val)
        case _:
            trp.fail(f"expected ('error', 'wheee', stacktrace), got {res}")

def test_process_key_ret(trp):
    def f():
        return os.getpid()
    x = spawn_ignore(f)
    res = wait_spawn(x)
    match res:
        case ("process-exit", pk, "ok", rv):
            trp.assert_equal("key return value", rv, pk)
        case _:
            trp.fail(f"key return value {res}")

# todo: test the other way of returning
def test_process_key_exit_0(trp):
    def f(_):
        #sck.send_value(os.getpid())
        os._exit(0)
    x = spawn(f)
    pid = get_spawn_pid(x)
    #pid = x[1].receive_value()
    res = wait_spawn(x)
    match res:
        case ("process-exit", pk, "ok", _):
            trp.assert_equal("key exit 0", pid, pk)
        case _:
            trp.fail(f"key return value {res} {pid}")
