
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

"""

import multiprocessing
import sys
import signal
import socket_wrapper
import traceback

##############################################################################

# the demonstration code

def spawn(f):

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
    raise ExitValException(val)

# call in a spawned function to exit with this value
# and a stack trace
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
