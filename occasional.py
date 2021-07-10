
import os
import sys
import traceback
import dill
import signal
import atexit
import logging

import functools
bind = functools.partial

import occ.spawn as mspawn
import occ.inbox as inbox
from occ.inbox import Infinity
import occ.sck as sck
import occ.yeshup as yeshup
import occ.logging

from tblib import pickling_support
pickling_support.install()

dill.settings['recurse'] = True

logger = logging.getLogger(__name__)

##############################################################################

# central services

"""x

this loop handles spawning, detecting process exits, and connecting
processes to each other

it also handles the process/runtime catalog information

the system is running ok as long as the initial user process is still
running and the central services is running. when the initial user
process exits, central services notices and exits the system and
returns the result value of the initial user process

"""

@pickling_support.install
class _SendNotFoundException(Exception):
    def __init__(self, addr):
        self.addr = addr

"""

two ways of starting the central process:
1. with a function to execute as process zero
in this case, you pass in the function to execute, and
the results socket which sends the exit value of the function
back to the creating process
on the client side, the system creates the socket pair for
the results, spawns the occasional system, waits for the exit,
then raises if the exit value was an error, otherwise returns it

2. starting at the top level
in this case you are getting the process spawning the central process
to become the main user process until occasional is stopped
you pass in the pid of the calling process, and a socket
which will become the inbox connection to that process
on the client side, the system creates the socket pair
for the top level inbox, and spawns the central process
it turns the socket end it keeps into the local inbox
when stop is called, it closes the socket and deletes
the local inbox

"""

# TODO: this function needs a refactor, try to find some
# abstraction which make it a bit shorter without spaghettifying
# the code
def _central(a,b,c):

    try:
        ib = None
        yeshup.yeshup_me()
        occ.logging.initialize_logging()
        # work around limitation with the spawn args
        # the arg is deconstructed and reordered because
        # the spawn only allows sockets in the first arguments
        match (a,b,c):
            case (sock,"function", userf):
                start_val = ("function", userf, sock)
            case (sock,"top-level", pid):
                start_val = ("top-level", pid, sock)
            case _:
                raise Exception(f"internal error - bad start val {(a,b,c)}")
        central_address = "central"
        def no_connect(_, connect_addr):
            raise _SendNotFoundException(connect_addr)

        # todo: trace this stuff better
        def safe_send(ib, tgt, msg):
            try:
                ib.send(tgt,msg)
            except:
                logger.info(("central error sending message", tgt, msg), exc_info=1)

        with inbox.make_simple(central_address, disconnect_notify=True,
                               connect=no_connect) as ib:

            # map from pid/addr to (process object, maybe first exit value)
            processes = {}

            # list of triples of monitoring pid, monitored pid, mref
            next_mref = 0
            process_monitoring = []

            def spawn_process_internal(f):
                if not callable(f):
                    raise Exception(f"spawn function is not callable {type(f)} {f}")
                (p, sock) = mspawn.spawn_with_socket(bind(_spawned_wrapper, central_address, f))
                logger.info(("spawn", p.pid, str(f)))
                ib.attach_socket(p.pid, sock, True)
                processes[p.pid] = (p, None)
                return p.pid

            def add_monitor(addr,monitored_addr):
                nonlocal next_mref
                mref = next_mref
                next_mref += 1
                process_monitoring.append((addr, monitored_addr, mref))
                return mref

            ##########################
            
            process_zero_exit = None

            match start_val:
                case ("function", user_f, _):
                    try:
                        process_zero = spawn_process_internal(user_f)
                    except:
                        # how to keep this in sync with spawn?
                        process_zero_exit = ("error", sys.exc_info()[1])
                case ("top-level",pid,sock):
                    # add to processes table
                    processes[pid] = (None,None)
                    process_zero = pid
                    # add connection to local inbox
                    ib.attach_socket(pid, sock, True)
                case _:
                    raise Exception(f"internal error: bad start_val {start_val}")
                    
            ##########################
            
            if process_zero_exit is None:
                while True:
                    x = ib.receive()
                    match x:
                        case ("process-exit", addr, v0, v1):
                            # todo: check the process is in the table
                            # check it doesn't already have a first exit val
                            processes[addr] = (processes[addr][0], (v0,v1))
                        case ("client-disconnected", addr):
                            # skip join and getting the exit value
                            # if this is process zero in a top
                            # level run
                            pe = processes[addr]
                            if start_val[0] == "top-level" \
                               and addr == process_zero:
                                process_exit_val = None
                            else:
                                pe[0].join()
                                process_exit_val = pe[1]
                                if process_exit_val is None:
                                    match mspawn.get_process_exitval(pe[0]):
                                        case ("process-exit", _, v0, v1):
                                            process_exit_val = (v0,v1)
                                        case _:
                                            logger.error(f"bad exit val: {x}")
                            logger.info(("process-exit", pe[0].pid, process_exit_val))
                            # if process zero, exit the central services
                            if addr == process_zero:
                                process_zero_exit = process_exit_val
                                break
                            # ping all the monitoring processes
                            any_monitors = False
                            for i in process_monitoring:
                                if i[1] == addr:
                                    any_monitors = True
                                    safe_send(ib, i[0], ("down", i[2], i[1], process_exit_val))
                            # clean up the process table
                            del processes[addr]
                            # clean up the monitoring table
                            process_monitoring = [(p,m,r) for (p,m,r) in process_monitoring
                                                  if p != addr and m != addr]
                        case ('top-level-exit',) if start_val[0] == "top-level":
                            break
                        case (ret, "ping"):
                            ib.send(ret, ("pong",))
                        case (ret, "spawn", f):
                            try:
                                new = spawn_process_internal(f)
                                ib.send(ret, ("spawned-ok", new))
                            except:
                                ib.send(ret, ("spawn-error", sys.exc_info()[1]))
                        case (ret, "spawn-monitor", f):
                            try:
                                new = spawn_process_internal(f)
                                mref = add_monitor(ret, new)
                                ib.send(ret, ("spawned-ok", new, mref))
                            except:
                                ib.send(ret, ("spawn-error", sys.exc_info()[1]))
                        case (from_addr, "connect-to", connect_addr):
                            logger.info(("connect", from_addr, connect_addr))
                            (sidea, sideb) = sck.socketpair()
                            try:
                                # there's a lot of things that need protection like this
                                # in the central
                                x = ib.send(connect_addr, ("have-a-connection", from_addr))
                            except Exception as x:
                                ib.send(from_addr, ("connection-error", f"send: process not found {x.addr}"))
                            else:
                                # todo: any of these 3 sends can fail because a process
                                # has exited in the meantime, central should not break
                                # when this happens, and if the calling process (from_addr)
                                # is up, it should get notified
                                ib.send_socket(connect_addr, sideb)
                                ib.send(from_addr, ("have-a-connection", connect_addr))
                                ib.send_socket(from_addr, sidea)
                                logger.info(("connection", from_addr, connect_addr))
                            finally:
                                try:
                                    sidea.detach_close()
                                except:
                                    logger.info("closing socketpair for connection in central 1", exc_info=1)
                                try:
                                    sideb.detach_close()
                                except:
                                    logger.info("closing socketpair for connection in central 2", exc_info=1)

                        case _:
                            logger.error(f"unrecognised message sent to central: {x}")

            # kill any running processes
            def kill_it(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except:
                    logger.info(("kill process on exit", pid), exc_info=1)
            [kill_it(pid) for pid in processes.keys()
             if not (pid == process_zero and start_val[0] == "top-level")]

            match start_val:
               case ("function", _, res_sock):
                   res_sock.send_value(process_zero_exit)
            
    except:
        logger.exception("central exiting with unexpected exception")
        raise
    finally:
        try:
            logger.info(("central_stop", os.getpid()))
            if ib is not None:
                safe_send(ib, "_logging", "exit")
        except:
            logger.exception("central final exiting")
    
##############################################################################

# spawn
    
# this is the function that is called by user code and runs in the user
# process
def _spawn_fun(central_addr, ib, f):
    ib.send(central_addr, (ib.addr, "spawn", f))
    def m(x):
        match x:
            case ("spawned-ok", addr):
                return addr
            case ("spawn-error", e):
                raise e
    return ib.receive(match=m)

def _spawn_monitor(central_addr, ib, f):
    ib.send(central_addr, (ib.addr, "spawn-monitor", f))
    def m(x):
        match x:
            case ("spawned-ok", addr, mref):
                return (addr,mref)
            case ("spawn-error", e):
                raise e
    return ib.receive(match=m)

######################################

# wrapper for the launched processes

def make_user_process_inbox(central_address, csck):
    new_ib = inbox.make_with_socket(csck, central_address, os.getpid())
    new_ib.connect = bind(inbox.Inbox.connect_using_central,
                          new_ib, central_address)
    new_ib.central = central_address
    new_ib.spawn_inbox = bind(_spawn_fun, central_address, new_ib)
    new_ib.spawn_inbox_monitor = bind(_spawn_monitor, central_address, new_ib)
    return new_ib
    

# this runs in the newly launched process to set things up and launch
# the user function
def _spawned_wrapper(central_address, f, csck):
    occ.logging.initialize_logging()
    new_ib = make_user_process_inbox(central_address, csck)
    inbox_connections = list(new_ib.get_connections())
    # close any uninvited sockets hanging around from pre-fork
    scks = flatten(get_referenced_sockets(f) + inbox_connections)
    logger.info(("spawn-keep-handles", scks))
    _close_extra_filehandles(scks)
    return f(new_ib)

#####################################

# there's no way to set a file handle as noinherit on fork, only on exec
# boooo
def _close_extra_filehandles(scks):
    dont_close = [0,1,2]
    for s in scks:
        dont_close.append(s._socket.fileno())
    to_close = []
    for fdp in os.listdir(f"/proc/{os.getpid()}/fd/"):
          fd = int(os.path.basename(fdp))
          if fd not in dont_close:
              try:
                  to_close.append(fd)
              except OSError as e:
                  if e.errno != 9:
                      raise
    if len(to_close) > 0:
        logger.info(("spawn-close-handles", to_close))
        for i in to_close:
            try:
                os.close(i)
                pass
            except OSError as e:
                if e.errno != 9:
                    raise

def flatten(a):
    ret = []
    for x in a:
        if type(x) is list:
            ret = ret + flatten(x)
        else:
            ret.append(x)
    return ret
        
# go through an f and args, and find any referenced sockets
# it knows how to look through the args of functions to see if they're sockets
# it also knows how to descend into functools.partial
# it doesn't know how to look inside arrays or objects
def get_referenced_sockets(x):
    if isinstance(x, functools.partial):
        return get_referenced_sockets(x.func) + \
                      [get_referenced_sockets(a) for a in x.args]
    elif type(x) == sck.Socket:
        return [x]
    else:
        return []



##############################################################################

# implicit inbox api

def _set_global_inbox(ib):
    # todo: check there isn't one there already
    if hasattr(sys.modules[__name__], "_occasional_inbox"):
        raise Exception("trying to create a second global inbox")
               
    setattr(sys.modules[__name__], "_occasional_inbox", ib)

def _del_global_inbox():
    return delattr(sys.modules[__name__], "_occasional_inbox")

def _ib():
    return getattr(sys.modules[__name__], "_occasional_inbox")
    
def _global_wrapper(f, ib):
    # something doesn't work with the global thing
    # maybe related to dill or multiprocessing or something
    # todo: test it again now not using multiprocessing any more
    #global occasional_inbox
    #occasional_inbox = ib
    _set_global_inbox(ib)
    f()

def _w(f):
    return bind(_global_wrapper, f)

def spawn_inbox(f):
    return _ib().spawn_inbox(f)

def spawn_inbox_monitor(f):
    return _ib().spawn_inbox_monitor(f)

def spawn(f):
    return spawn_inbox(_w(f))

def spawn_monitor(f):
    return spawn_inbox_monitor(_w(f))


def send(addr,msg):
    return _ib().send(addr, msg)

def receive(match=None, timeout=inbox.Infinity()):
    return _ib().receive(match=match, timeout=timeout)

def slf():
    return _ib().addr

def central_addr():
    return _ib().central


##############################################################################

# launcher

# start a new occasional instance
# f is the starting user process
# if it exits, the whole system exits
#   (this could be modified in the future if needed)
# the return valueof the start call is the exit value
# of the f process
# start blocks until f exits

def run_inbox(f):
    (retvala, retvalb) = sck.socketpair()
    p = mspawn.spawn_basic(target=_central, args=[retvalb,"function", f])
    retvalb.detach_close()
    p.join()
    ret = retvala.receive_value()
    match ret:
        case None:
            raise Exception("internal error: expected an exit value")
        case ("error", ("exitcode", n)):
            raise Exception(f"occasional main process exited with exit code {n}")
        case ("error", ("signal", nm)):
            raise Exception(f"occasional main process exited with signal {nm}")
        case ("error", e):
            raise Exception(f"Main process exited with {e}") from e
        case ("ok", _):
            return ret
        case _:
            raise Exception(f"internal error: expected (ok,_) or (error,_), got {ret}")

def run(f):
   return run_inbox(_w(f))
        
"""
support for running from the repl
---------------------------------

TODO: anomaly testing:
try all the functions before doing occasional.run
try them all after doing occasional.stop
try doing occasional.run a second time after calling stop make sure it
  works
check all these in the repl also
-> needs some more sophisticated testing utils

check the central exits when the calling process exits for whatever reason
  or when it closes the socket

"""

def start():
    (loc,rem) = sck.socketpair()
    p = mspawn.spawn_basic(target=_central, args=[rem,"top-level", os.getpid()])
    rem.detach_close()
    central_address = "central" # todo: get from central
    ib = make_user_process_inbox(central_address, loc)
    ib.central_process = p
    _set_global_inbox(ib)
    # exit occasional on exit if running in repl
    # otherwise the repl hangs when you exit and you have to also
    # press ctrl-c and see a bunch of tracebacks
    if hasattr(sys, 'ps1'):
        atexit.register(stop)

def stop():
    send(central_addr(), ("top-level-exit",))
    _ib().central_process.join()
    _ib().close()
    _del_global_inbox()

