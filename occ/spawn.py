
"""x

Supporting getting process exit values/information in the system:

In Linux, a process can either have an 1 byte exit code, 0 being
'success', and any other number being failure with the number
indicating which failure if you're lucky, or it can have exited
because of a signal.

To mimic Erlang, we want to supplement with exiting with an arbitrary
Python value instead of a 1 byte integer, and exiting with an arbitary
Python value representing an error along with a stack trace where the
error occured.

Exiting with an arbitrary Python value can be done with an exit
function, or by returning it from the top level function for the
process. Exiting with None is indistinguishable from exiting a process
with a Linux exit value of 0.

Exiting with an error can be done with an error function, or by
raising an exception that isn't caught and exits the process. Another
process examining the exit value of the exited process can see the
arbitrary error value, and the stack trace from the exit call or where
the uncaught exception was raised.

The different between a value exit and an error exit is that the error
exit also has a stack trace.

The idea is that you usually use the Occasional exit values -> exiting
with a Python value or erroring with a Python value, but if a process
exits without an exit value, it preserves the Linux process exit code,
or the signal that caused the exit to be examined instead.

Implementation

There is a low level Linux call that the parent of a process can use
to get the Linux process exit number or the signal that caused the
process to exit.

For other cases - Python exit value or error with value and stack trace,
the Occasional implementation running in the user process must send this
value on the socket connection back to the central services before
exiting the process
the system implementation reconciles these optional exit values sent
via message passing, and the os reported exit number/signal, to report
a single exit value for a process.

"""

import sys
import signal
import occ.sck as sck
import traceback
import occ.yeshup as yeshup
import dill
import os
import functools

bind = functools.partial

import logging
logger = logging.getLogger(__name__)

from tblib import pickling_support


##############################################################################

# spawn basic

# some code to wrap fork which allows you to run a function in the new
# process which you supply which makes the code using it a little more
# direct and clear than unadorned fork, and reproduces the process exit
# behaviour of running a top level python process wrt signals, exit codes
# when you call join on the fork.

######################################

# client side code for launched processes

# how can tell python that this function will never return e.g. for
# garbage collection purposes. although not sure how useful this is
def _launched_process(target, args=[]):
    try:

        #print(f"{os.getpid()} running {target}")
        target(*args)
        #print(f"in child {os.getpid()} exit 0")
        #print(f"exiting {os.getpid()}")
        os._exit(0)
    except SystemExit as e:
        """
Duplicate main Python behaviour:
If the value is an integer, it specifies the system exit status
(passed to C’s exit() function); if it is None, the exit status is
zero; if it has another type (such as a string), the object’s value is
printed and the exit status is one.

"""
        if e.code is None:
            #print(f"exiting {os.getpid()}")
            os._exit(0)
        elif type(e.code) is int:
            #print(f"exiting {os.getpid()}")
            os._exit(e.code)
        else:
            #print(f"exiting {os.getpid()}")
            #print(e.code)
            os._exit(1)
    except:
        traceback.print_exc()
        #print(f"in child {os.getpid()} exit 1")
    finally:
        #print(f"exiting {os.getpid()}")
        os._exit(1)

                  
######################################

class _Forker:
    def __init__(self, pid):
        self.pid = pid
        self.exitcode = None

    def join(self):
        if self.exitcode is not None:
            return self.exitcode
        #print(f"joining {self.pid}")
        status = os.waitid(os.P_PID, self.pid, os.WEXITED)
        #print(f"join status {status}")
        if status.si_code == os.CLD_EXITED:
            #print(f"join thing returning {status.si_status}")
            self.exitcode = status.si_status 
        elif status.si_code == os.CLD_KILLED:
            #print(f"join thing returning {-status.si_status}")
            # mimic old exit code
            self.exitcode = -status.si_status
        else:
            raise Exception(f"internal error, expected CLD_EXITED or CLD_KILLED, got {status.si_code}")
        return self.exitcode

def spawn_basic(target, args=[]):
    pid = os.fork()
    if pid == 0:
        #print(f"started {os.getpid()} {get_name(target)}")
        #print(get_name(target))

        _launched_process(target, args)

    else:
        return _Forker(pid)

# TODO: write direct tests for this

##############################################################################

# spawn with socket

# this is a fork which passes the forked process one end of a
# socketpair and returns the other, and also comes with convenience
# functions to allow using this socket to return a value more rich
# than posix (which is just a 8 byte int, and 0 is the only value that
# traditionally represents success)

@pickling_support.install
class ExitVal(Exception):
    def __init__(self,val):
        self.val = val

@pickling_support.install
class ErrorExit(Exception):
    def __init__(self,val):
        self.val = val

def spawned_process_wrapper(client_s, f):
    yeshup.yeshup_me()
    spawn_key = os.getpid()
    p_res = None
    try:
        ret = f(client_s)
        if ret != None:
            p_res = ("process-exit", spawn_key, "ok", ret)
    except SystemExit:
        raise
    except ExitVal as e:
        p_res = ("process-exit", spawn_key, "ok", e.val)
    except:
        e = sys.exc_info()[1]
        p_res = ("process-exit", spawn_key, "error", e)
    if p_res is not None:
        client_s.send_value(p_res)
       
def spawn_with_socket(f):

    (server_s, client_s) = sck.socketpair()

    p = spawn_basic(bind(spawned_process_wrapper,client_s, f))
    return (p, server_s)


# call in a spawned function to exit with this value
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
    raise ExitVal(val)

# call in a spawned function to exit with this value
# and a stack trace
def spawn_error(val):
    # similar comments as above
    raise ErrorExit(val)

def get_process_exitval(p):
    if p.exitcode == 0:
        exit_reason = ("process-exit",  p.pid, "ok",
                       ("exitcode", p.exitcode))
    elif p.exitcode > 0:
        exit_reason = ("process-exit",  p.pid, "error",
                       ("exitcode", p.exitcode))
    else:
        exit_reason = ("process-exit", p.pid, "error",
                       ("signal", signal.strsignal(-p.exitcode)))
    return exit_reason

# wait for a process to exit and get it's exit value
def wait_spawn(x):
    (p, server_s) = x
    p.join()
    v = server_s.receive_value()
    if v is None:
        return get_process_exitval(p)
    else:
        return v

def get_spawn_pid(p):
    return p[0].pid
