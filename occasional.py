
import os
import sys
import traceback
import dill
import signal
import atexit
import logging
import setproctitle
import types

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
        logger.info(("central_start", os.getpid()))
        setproctitle.setproctitle(f"python3 spawn {get_name(_central)}")
        # ignore these because this is a 'background process'
        # this process should have been spawned with these signals
        # masked
        # they should be inherited by processes spawned
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGQUIT, signal.SIG_IGN)
        # it doesn't ignore stop and continue, because we do
        # want this and spawned processes to stop and continue
        # with a foreground app if they are being run interactively
        
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
        central_address = "_central"
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

            process_zero = None

            # simple name registration
            # todo: expose it to user code to add and remove registrations
            #   avoid processes making more than one connection because the
            #   other process has more than one name (including its pid)
            #   should add types to distinguish between the pid addresses
            #   and names
            #   if you can name processes, the list needs to be maintained
            #   when processes exit

            process_name_registry = {"_central":os.getpid()}
            def lookup_proc_by_name(nm):
                if nm in process_name_registry:
                    nm = process_name_registry[nm]
                elif nm not in processes:
                    raise Exception(f"process not found {nm} {processes}")
                p_names = []
                for k in process_name_registry:
                    if process_name_registry[k] == nm:
                        p_names.append(k)
                return (nm,p_names)
            
            def spawn_process_internal(f):
                if not callable(f):
                    raise Exception(f"spawn function is not callable {type(f)} {f}")
                (p, sock) = mspawn.spawn_with_socket(bind(_spawned_wrapper, central_address, f))
                logger.info(("spawn", p.pid, get_name_from_f(f)))
                ib.attach_socket(p.pid, sock, [], True)
                processes[p.pid] = (p, None)
                return p.pid

            def add_monitor(addr,monitored_addr):
                nonlocal next_mref
                mref = next_mref
                next_mref += 1
                process_monitoring.append((addr, monitored_addr, mref))
                return mref

            ##########################

            log_addr = spawn_process_internal(logging_process)
            process_name_registry["_logging"] = log_addr
            ib.add_socket_name(log_addr, "_logging")

            occ.logging.set_logging_inbox(ib)

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
                    ib.attach_socket(pid, sock, [], True)
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
                            if addr in processes:
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
                                cold = connect_addr
                                (connect_addr, to_p_names) = lookup_proc_by_name(connect_addr)
                                (_,from_p_names) = lookup_proc_by_name(from_addr)
                                if connect_addr == os.getpid():
                                    raise Exception(f"bad connect to central using {cold}")
                                x = ib.send(connect_addr, ("have-a-connection", from_addr, from_p_names))
                                ib.send_socket(connect_addr, sideb)
                            except Exception as x:
                                # there's a lot of things that need protection like this
                                # in the central
                                ib.send(from_addr, ("connection-error", f"send: process not found {connect_addr}"))
                            else:
                                # todo: any of these 3 sends can fail because a process
                                # has exited in the meantime, central should not break
                                # when this happens, and if the calling process (from_addr)
                                # is up, it should get notified
                                ib.send(from_addr, ("have-a-connection", connect_addr, to_p_names))
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
             if (not (pid == process_zero and start_val[0] == "top-level")) \
             and (not (pid == process_name_registry["_logging"]))]

            match start_val:
               case ("function", _, res_sock):
                   res_sock.send_value(process_zero_exit)
            occ.logging.stop_logging(ib)
            
            
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
    new_ib = inbox.make_with_socket(csck, central_address, os.getpid(), ["_central"])
    new_ib.connect = bind(inbox.Inbox.connect_using_central,
                          new_ib, central_address)
    new_ib.spawn_inbox = bind(_spawn_fun, central_address, new_ib)
    new_ib.spawn_inbox_monitor = bind(_spawn_monitor, central_address, new_ib)
    return new_ib
    

# this runs in the newly launched process to set things up and launch
# the user function
def _spawned_wrapper(central_address, f, csck):
    occ.logging.initialize_logging()
    setproctitle.setproctitle(f"python3 spawn {get_name(f)}")
    new_ib = make_user_process_inbox(central_address, csck)
    new_ib.make_connection("_logging")
    occ.logging.set_logging_inbox(new_ib)

    # close any uninvited sockets hanging around from pre-fork
    inbox_connections = list(new_ib.get_connections())
    scks = flatten(get_referenced_sockets(f) + inbox_connections)
    logger.info(("spawn-keep-handles", scks))
    _close_extra_filehandles(scks)

    return f(new_ib)

#####################################

"""
function to get a good process name for a spawned process

this code uses a lot of functools.partial
strategy is:
if the f is a function, return the function name
  it's good style in this code to launch a process by using functools.partial
    instead of passing an args
    -> make this mandatory
if f is a functools.partial, then iterate through the args
  if an args is a function not in the black list, choose that
  if args is a partial, recurse into its args
  otherwise skip it
if nothing is found, use the str(f)

the blacklist is:
spawned_process_wrapper
_spawned_wrapper
_global_wrapper
testcase_worker_wrapper

not sure how to maintain this blacklist well ...


"""
blacklist = ["spawned_process_wrapper",
             "_spawned_wrapper",
             "_global_wrapper",
             "testcase_worker_wrapper",
             "wrap_f",
             "ignore_f"]

def get_name_from_f(f):
    if isinstance(f, functools.partial):
        x = get_name_from_f(f.func)
        if x is not None:
            return x
        for i in f.args:
            x = get_name_from_f(i)
            if x is not None:
                return x
    elif type(f) == types.FunctionType:
        if f.__name__ not in blacklist:
            return f"{f.__module__}.{f.__name__} {f.__code__.co_filename}:{f.__code__.co_firstlineno}"
        else:
            pass
    else:
        #print(type(f))
        return None

def get_name(f):
    x = get_name_from_f(f)
    if x is None:
        return str(f)
    else:
        return x


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

##############################################################################

# logging

def log_prefix(s):
    # print(f"LOG: **** {type(s)}")
    if type(s) is str:
        lines = s.splitlines()
    elif type(s) is list:
        splt = [l.splitlines() for l in s]
        lines = [y for x in splt for y in x]
    else:
        lines = str(s).splitlines()
    l1 = [f"LOG: {l}" for l in lines]
    return "\n".join(l1)
        
# TODO: why is the logging process getting have-a-connection messages
#   when running tests
#   these should not leak out of the inbox internals

def logging_process(ib):
    # temp hack
    ib.add_self_name("_logging")
    while True:
        try:
            x = ib.receive()
            if x == "exit":
                break
            s1 = str(x)
            print(log_prefix(x))
            try:
                if x.exc_info is not None:
                    print(log_prefix(traceback.format_exception(*x.exc_info)))
            except AttributeError:
                pass #print(f"ATT: {x}")
            
            print(f"LOG: {x}")
        except:
            print(f"exception in logging process")
            traceback.print_exc()

##############################################################################

# launcher

"""

set up signal stuff
want to ignore siginit and sigquit in this process
and all the spawned processes
so it only gets delivered to the foreground process when you run occasional
if the foreground process decides to ignore these signals, nothing will happen to any part of the system
if the foreground process exits when it gets these signals, because of yeshup, it should exit all the rest of the launched occasional system
this relies on:
yeshup
whatever internal spawn implementation used inherits the signal handlers for these signals
for it to work completely, any exes spawned which aren't in the system, and use another method to launch additional processes, need to make sure these signal handlers are inherited, and need to make sure they use some sort of yeshup approach or are ok leaving orphaned processes

"""

def _spawn_central(args):
    """x
avoid race conditions
block the signals before spawning the central process
this will then ignore the signals
the current process will then unblock
-> no chance of getting these signals delivered to the central process

no chance of missing them in the current process (except for the usual
duplicate signal thing if you multiples of the same signal too
quickly?)

the mask is inherited when forking

    """
    try:
        #occ.logging.initialize_logging()
        signal.pthread_sigmask(signal.SIG_BLOCK, [signal.SIGINT, signal.SIGQUIT])
        # TODO: protect against the user code that called this having threads
        # and stuff that isn't fork friendly?
        p = mspawn.spawn_basic(bind(_central,*args))
        return p
    finally:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, [signal.SIGINT, signal.SIGQUIT])

# start a new occasional instance
# f is the starting user process
# if it exits, the whole system exits
#   (this could be modified in the future if needed)
# the return valueof the start call is the exit value
# of the f process
# start blocks until f exits

def run_inbox(f):
    (retvala, retvalb) = sck.socketpair()
    p = _spawn_central([retvalb,"function", f])
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
    p = _spawn_central([rem,"top-level", os.getpid()])
    rem.detach_close()
    central_address = "_central" # todo: get from central
    ib = make_user_process_inbox(central_address, loc)
    ib.central_process = p
    _set_global_inbox(ib)
    # exit occasional on exit if running in repl
    # otherwise the repl hangs when you exit and you have to also
    # press ctrl-c and see a bunch of tracebacks
    if hasattr(sys, 'ps1'):
        atexit.register(stop)

def stop():
    send("_central", ("top-level-exit",))
    _ib().central_process.join()
    _ib().close()
    _del_global_inbox()

