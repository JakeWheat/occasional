

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

from process_exit_spawn import *

import os
import sys
import time
import functools

# simple exits from a python function

def spawn_ignore(f):
    def ignore_f(f, _):
        return f()
    return spawn(functools.partial(ignore_f, f))
        

def helper_test_function(trp, msg, f, ex):

    x = spawn_ignore(f)
    res = wait_spawn(x)
    trp.assert_equal(msg, ex, res)


def test_leave_function(trp):
    def my_f():
        pass
    helper_test_function(trp, "leave function exit code", my_f, ("exitcode", 0))

def test_python_exit_0(trp):
    def my_f():
        sys.exit()
    helper_test_function(trp, "sys.exit()", my_f, ("exitcode", 0))
    

def test_linux_exit_0(trp):
    def my_f():
        os._exit(0)
    helper_test_function(trp, "os._exit(0)", my_f, ("exitcode", 0))


def test_python_exit_non_zero(trp):
    def my_f():
        sys.exit(1)
    helper_test_function(trp, "sys.exit(1)", my_f, ("exitcode", 1))

def test_linux_exit_non_zero(trp):
    def my_f():
        os._exit(1)
    helper_test_function(trp, "os._exit(1)", my_f, ("exitcode", 1))

def test_sigterm(trp):
    def my_f():
        time.sleep(1000)
        
    x = spawn_ignore(my_f)
    os.kill(get_spawn_pid(x), signal.SIGTERM)
    res = wait_spawn(x)
    trp.assert_equal("sigterm", ('signal', 'Terminated'), res)


def test_sigkill_0(trp):
    def my_f():
        time.sleep(1000)
        
    x = spawn_ignore(my_f)
    os.kill(get_spawn_pid(x), signal.SIGKILL)
    res = wait_spawn(x)
    trp.assert_equal("sigterm", ('signal', 'Killed'), res)

# TODO: spawn an exe versions
def test_exe_return_0(trp):
    pass

def test_exe_return_non_zero(trp):
    pass

def test_exe_sigterm(trp):
    pass

def test_exe_sigkill(trp):
    pass

# exits which use the socket connection for the exit value
def test_return_from_function(trp):
    def my_f():
        return "bye"
    helper_test_function(trp, "return value", my_f, "bye")

def test_exit_value_function_0(trp):
    def my_f():
        spawn_exit(0)
    # exiting with an integer value is distinguishable
    # from the process exiting with os exit code 0
    helper_test_function(trp, "exit value function", my_f, 0)

def test_exit_value_function_non_trivial(trp):
    def my_f():
        spawn_exit("bye also")
    helper_test_function(trp, "exit value function", my_f, "bye also")

class Tedious(Exception):
    def __init__(self,msg):
        self.msg = msg

    
def test_uncaught_exception(trp):
    def my_f():
        raise Tedious("hi")
    x = spawn_ignore(my_f)
    res = wait_spawn(x)
    match res:
        case ("error", e, st):
            trp.assert_equal("exception class", Tedious, type(e))
            trp.assert_equal("exception value", "hi", e.msg)
            trp.assert_equal("stacktrace class", traceback.StackSummary, type(st))
        case _:
            trp.fail(f"expected ('error', Tedious, traceback.StackSummary), got {res}")


def test_error_function(trp):
    def my_f():
        spawn_error("wheee")
    x = spawn_ignore(my_f)
    res = wait_spawn(x)
    match res:
        case ("error", e, st):
            trp.assert_equal("error exit", "wheee", e)
            trp.assert_equal("stacktrace class", traceback.StackSummary, type(st))
        case _:
            trp.fail(f"expected ('error', 'wheee', stacktrace), got {res}")


# all_tests = [test_leave_function,
#              test_python_exit_0,
#              test_linux_exit_0,
#              test_python_exit_non_zero,
#              test_linux_exit_non_zero,
#              test_sigterm,
#              test_sigkill_0,
#              test_exe_return_0,
#              test_exe_return_non_zero,
#              test_exe_sigterm,
#              test_exe_sigkill,
#              test_return_from_function,
#              test_exit_value_function_0,
#              test_exit_value_function_non_trivial,
#              test_uncaught_exception,
#              test_error_function,
#              ]
