
"""x

Supporting getting process exit values/information in the system:

In Linux, a process can either have an 1 byte exit code, 0 being
'success', and any other number being failure with the number
indicating the failure, or it can have exited because of a signal.

To mimic Erlang, we want to supplement with a few variations:

returning an arbitrary python value instead of just an integer
  -> this can be done by returning the value from the python top level
    of the process, returning None is treated indistinguishably from
    linux process exit code 0
    there can also be an exit function for this like in Erlang

signalling an error, so that anyone inspecting the exit value of the process
can see an arbitrary exit value representing the error, and a stack trace

in these cases, the system arranges the linux processes to exit with
either 0 exit code, or non zero exit code depending on whether it's a
nice exit -> exit value/return, or a error exit: error called or
uncaught exception

There are a number of ways to get the python code to exit the process
with a non zero exit code, and to exit the process using a signal.

The idea is that you usually use occasional exit values, but if the
process exits without an exit value, it preserves the linux process
exit code, or the signal that caused the exit to be examined instead

Implementation

There is a low level linux call that the parent of a process can use
to get the linux process exit number or the signal that caused the
process to exit. This is wrapped in python and the occasional
implementation gets this from the multiprocessing module.

For other cases - python exit value or error with value and stack trace,
the occasional implementation running in the user process must send this
value on the socket connection back to the central services before
exiting the process
the system implementation reconciles these optional exit values sent
via message passing, and the os reported exit number/signal


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

import multiprocessing
import sys
import functools
import os
import time
import signal
import socket_wrapper
import traceback

##############################################################################

# the demonstration code

def spawn_function(f):

    (server_s, client_s) = socket_wrapper.value_socketpair()

    def spawned_process_wrapper(client_s, f):
        try:
            ret = f()
            if ret != None:
                client_s.send_value(ret)
        except SystemExit:
            raise
        except ExitValException as e:
            client_s.send_value(e.val)
        except ExitErrorException as e:
            xx = sys.exc_info()
            client_s.send_value(("error", e.val, traceback.extract_tb(xx[2])))
        except:
            e = sys.exc_info()
            client_s.send_value(("error", e[1], traceback.extract_tb(e[2])))
            
    
    p = multiprocessing.Process(target=spawned_process_wrapper, args=[client_s, f])
    p.start()
    return (p, server_s)

class ExitValException(Exception):
    def __init__(self,val):
        self.val = val

class ExitErrorException(Exception):
    def __init__(self,val):
        self.val = val


def spawn_exit(val):
    # how to get access to the surrounding client_s to send the value
    # then exit?
    # cheapo version, use a special exception
    # this is not encouraging the user to use crash only code ...
    # come back and try to find a better answer
    # really want spawn_exit to send the value immediately on the socket
    # then use os._exit, no matter where it is called
    # this also prevents the user from catching the exception
    # not sure if this is good or bad
    # but it's a good thing when you ask something to exit, it doesn't
    # have the option of refusing
    raise ExitValException(val)

def spawn_error(val):
    # similar comments as above
    raise ExitErrorException(val)

def wait_spawn(x):
    (p, server_s) = x
    p.join()
    if p.exitcode >= 0:
        exit_reason = ("exitcode", p.exitcode)
    else:
        exit_reason = ("signal", signal.strsignal(-p.exitcode))
    v = server_s.receive_value()
    if v is None:
        return exit_reason
    else:
        return v

def get_spawn_pid(p):
    return p[0].pid

    

##############################################################################

# tests

# simple exits from a python function

def test_function(trp, msg, f, ex):

    x = spawn_function(f)
    res = wait_spawn(x)
    trp.assert_equal(msg, ex, res)


def test_leave_function(trp):
    def my_f():
        pass
    test_function(trp, "leave function exit code", my_f, ("exitcode", 0))

def test_python_exit_0(trp):
    def my_f():
        sys.exit()
    test_function(trp, "sys.exit()", my_f, ("exitcode", 0))
    

def test_linux_exit_0(trp):
    def my_f():
        os._exit(0)
    test_function(trp, "os._exit(0)", my_f, ("exitcode", 0))


def test_python_exit_non_zero(trp):
    def my_f():
        sys.exit(1)
    test_function(trp, "sys.exit(1)", my_f, ("exitcode", 1))

def test_linux_exit_non_zero(trp):
    def my_f():
        os._exit(1)
    test_function(trp, "os._exit(1)", my_f, ("exitcode", 1))

def test_sigterm(trp):
    def my_f():
        time.sleep(1000)
        
    x = spawn_function(my_f)
    os.kill(get_spawn_pid(x), signal.SIGTERM)
    res = wait_spawn(x)
    trp.assert_equal("sigterm", ('signal', 'Terminated'), res)


def test_sigkill_0(trp):
    def my_f():
        time.sleep(1000)
        
    x = spawn_function(my_f)
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
    test_function(trp, "return value", my_f, "bye")

def test_exit_value_function_0(trp):
    def my_f():
        spawn_exit(0)
    # exiting with an integer value is distinguishable
    # from the process exiting with os exit code 0
    test_function(trp, "exit value function", my_f, 0)

def test_exit_value_function_non_trivial(trp):
    def my_f():
        spawn_exit("bye also")
    test_function(trp, "exit value function", my_f, "bye also")

class Tedious(Exception):
    def __init__(self,msg):
        self.msg = msg

    
def test_uncaught_exception(trp):
    def my_f():
        raise Tedious("hi")
    x = spawn_function(my_f)
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
    x = spawn_function(my_f)
    res = wait_spawn(x)
    match res:
        case ("error", e, st):
            trp.assert_equal("error exit", "wheee", e)
            trp.assert_equal("stacktrace class", traceback.StackSummary, type(st))
        case _:
            trp.fail(f"expected ('error', 'wheee', stacktrace), got {res}")


all_tests = [test_leave_function,
             test_python_exit_0,
             test_linux_exit_0,
             test_python_exit_non_zero,
             test_linux_exit_non_zero,
             test_sigterm,
             test_sigkill_0,
             test_exe_return_0,
             test_exe_return_non_zero,
             test_exe_sigterm,
             test_exe_sigkill,
             test_return_from_function,
             test_exit_value_function_0,
             test_exit_value_function_non_trivial,
             test_uncaught_exception,
             test_error_function,
             ]
    


