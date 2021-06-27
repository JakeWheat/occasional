
import multiprocessing
import multiprocessing_wrap
import functools
import os
import sys
import traceback
import dill
import signal

import spawn
import inbox
import sck

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

forkit = multiprocessing.get_context('forkserver')

class SendNotFoundException(Exception):
    def __init__(self, addr):
        self.addr = addr

def central(res_sock, user_f):
    try:
        central_address = "central"
        def no_connect(_, connect_addr):
            raise SendNotFoundException(connect_addr)
             
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
                (p, sck) = spawn.spawn(functools.partial(spawned_wrapper, central_address, f),
                                       ctx=forkit)
                ib.attach_socket(p.pid, sck)
                processes[p.pid] = (p, None)
                return p.pid

            def add_monitor(addr,monitored_addr):
                nonlocal next_mref
                mref = next_mref
                next_mref += 1
                process_monitoring.append((addr, monitored_addr, mref))
                return mref

            process_zero_exit = None
            try:
                process_zero = spawn_process_internal(user_f)
            except:
                # how to keep this in sync with spawn?
                process_zero_exit = ("error", (sys.exc_info()[1], "".join(traceback.format_tb(sys.exc_info()[2]))))

            if process_zero_exit is None:
                while True:
                    x = ib.receive()
                    match x:
                        case ("process-exit", addr, v0, v1):
                            # todo: check the process is in the table
                            # check it doesn't already have a first exit val
                            processes[addr] = (processes[addr][0], (v0,v1))
                        case ("client-disconnected", addr):
                            pe = processes[addr]
                            pe[0].join()
                            process_exit_val = pe[1]
                            if process_exit_val is None:
                                match spawn.get_process_exitval(pe[0]):
                                    case ("process-exit", _, v0, v1):
                                        process_exit_val = (v0,v1)
                                    case _:
                                        print(f"bad exit val: {x}")
                            # if process zero, exit the central services
                            if addr == process_zero:
                                process_zero_exit = process_exit_val
                                break
                            # ping all the monitoring processes
                            any_monitors = False
                            for i in process_monitoring:
                                if i[1] == addr:
                                    any_monitors = True
                                    ib.send(i[0], ("down", i[2], i[1], process_exit_val))
                            if process_exit_val[0] == 'error' and any_monitors == False:
                                # debug print
                                print(f"process exited with {process_exit_val}")
                            # clean up the process table
                            del processes[addr]
                            # clean up the monitoring table
                            process_monitoring = [(p,m,r) for (p,m,r) in process_monitoring
                                                  if p != addr and m != addr]
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


                        case _:
                            print(x)

            # kill any running processes
            def kill_it(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except:
                    print(sys.exc_info()[1])
            [kill_it(pid) for pid in processes.keys()]
                            
            res_sock.send_value(process_zero_exit)
            
    except:
        #print("HERE")
        #print(sys.exc_info()[1])
        traceback.print_exc()
        raise

    
##############################################################################

# spawn
    
# this is the function that is called by user code and runs in the user
# process
def spawn_fun(central_addr, ib, f):
    ib.send(central_addr, (ib.addr, "spawn", f))
    def m(x):
        match x:
            case ("spawned-ok", addr):
                return addr
            case ("spawn-error", e):
                raise e
    return ib.receive(match=m)

def spawn_monitor(central_addr, ib, f):
    ib.send(central_addr, (ib.addr, "spawn-monitor", f))
    def m(x):
        match x:
            case ("spawned-ok", addr, mref):
                return (addr,mref)
            case ("spawn-error", e):
                raise e
    return ib.receive(match=m)


# this runs in the newly launched process to set things up and launch
# the user function
def spawned_wrapper(central_address, f, csck):
    new_ib = inbox.make_with_socket(csck, central_address, os.getpid())
    new_ib.connect = functools.partial(inbox.Inbox.connect_using_central,
                                            new_ib, central_address)
    new_ib.central = central_address
    new_ib.spawn = functools.partial(spawn_fun, central_address, new_ib)
    new_ib.spawn_monitor = functools.partial(spawn_monitor, central_address, new_ib)
    return f(new_ib)


##############################################################################

# launcher

# start a new occasional instance
# f is the starting user process
# if it exits, the whole system exits
#   (this could be modified in the future if needed)
# the return valueof the start call is the exit value
# of the f process
# start blocks until f exits

def run(f):
    (retvala, retvalb) = sck.socketpair()
    # protext against the user code that called this having threads
    # and stuff that isn't fork friendly
    ctx = multiprocessing.get_context('spawn')
    p = multiprocessing_wrap.start_process(target=central, args=[retvalb,f])
    p.join()
    ret = retvala.receive_value()
    match ret:
        case None:
            raise Exception("internal error: expected an exit value")
        case ("error", ("exitcode", n)):
            raise Exception(f"occasional main process exited with exit code {n}")
        case ("error", ("signal", nm)):
            raise Exception(f"occasional main process exited with signal {nm}")
        case ("error", (e, tb)):
            s = "".join(traceback.format_exception_only(type(e), e))
            raise Exception(s + tb)
        case ("ok", _):
            return ret
        case _:
            raise Exception(f"internal error: expected (ok,_) or (error,_), got {ret}")

