
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
process to exit. This is wrapped in Python and the Occasional
implementation gets this from the multiprocessing module.

For other cases - Python exit value or error with value and stack trace,
the Occasional implementation running in the user process must send this
value on the socket connection back to the central services before
exiting the process
the system implementation reconciles these optional exit values sent
via message passing, and the os reported exit number/signal, to report
a single exit value for a process.

"""

import multiprocessing
import sys
import signal
import sck
import traceback
import yeshup

class ExitValException(Exception):
    def __init__(self,val):
        self.val = val

class ExitErrorException(Exception):
    def __init__(self,val):
        self.val = val

def spawn(f, daemon=False):

    (server_s, client_s) = sck.socketpair()

    def spawned_process_wrapper(client_s, f):
        yeshup.yeshup_me()
        try:
            ret = f(client_s)
            if ret != None:
                client_s.send_value(ret)
        except SystemExit:
            raise
        except ExitValException as e:
            client_s.send_value(e.val)
        except ExitErrorException as e:
            einf = sys.exc_info()
            client_s.send_value(("error", e.val, traceback.extract_tb(einf[2])))
        except:
            einf = sys.exc_info()
            client_s.send_value(("error", einf[1], traceback.extract_tb(einf[2])))
            
    
    p = multiprocessing.Process(target=spawned_process_wrapper, args=[client_s, f], daemon=daemon)
    p.start()
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
    raise ExitValException(val)

# call in a spawned function to exit with this value
# and a stack trace
def spawn_error(val):
    # similar comments as above
    raise ExitErrorException(val)

# wait for a process to exit and get it's exit value
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
