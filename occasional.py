
import multiprocessing
import functools
import os
import sys
import traceback
import dill

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

def central(res_sock, puser_f):
    try:
        user_f = dill.loads(puser_f)
        central_address = "central"
        with inbox.make_simple(central_address, disconnect_notify=True) as ib:

            processes = {}

            def spawn_process_internal(f):

                def spawned_wrapper(f, csck):
                    new_ib = inbox.make_with_socket(csck, central_address, os.getpid())
                    new_ib.connect = functools.partial(inbox.Inbox.connect_using_central,
                                                            new_ib, central_address)
                    new_ib.central = central_address
                    new_ib.spawn = functools.partial(spawn_fun, central_address, new_ib)
                    return f(new_ib)
                (p, sck) = spawn.spawn(functools.partial(spawned_wrapper, f),ctx=forkit)
                ib.attach_socket(p.pid, sck)
                processes[p.pid] = p
                return p.pid

            process_zero = spawn_process_internal(user_f)
            process_zero_exit = None

            while True:
                x = ib.receive()
                match x:
                    case ("process-exit", v0, v1):
                        process_zero_exit = (v0,v1)
                        # todo: only set if it's the first user process
                        # have to add the addr to the process exit message
                        # or something
                    case ("client-disconnected", addr):
                        # get the process corresponding to the addr
                        p = processes[addr]
                        p.join()
                        # todo: process the exit val
                        if addr == process_zero:
                            x = spawn.get_process_exitval(p)
                            match x:
                                case ("process-exit", v0, v1):
                                    if process_zero_exit is None:
                                        process_zero_exit = (v0,v1)
                            break
                    case (ret, "ping"):
                        #print(f"cs got ping from {ret}")
                        ib.send(ret, ("pong",))
                    case (ret, "spawn", f):
                        new = spawn_process_internal(f)
                        ib.send(ret, ("spawned-ok", new))
                    case (from_addr, "connect-to", connect_addr):
                        (sidea, sideb) = sck.socketpair()
                        ib.send(connect_addr, ("have-a-connection", from_addr))
                        ib.send_socket(connect_addr, sideb)
                        ib.send(from_addr, ("have-a-connection", connect_addr))
                        ib.send_socket(from_addr, sidea)
                    case _:
                        print(x)

            res_sock.send_value(process_zero_exit)
            
    except:
        #print("HERE")
        #print(sys.exc_info()[0])
        traceback.print_exc()
        raise
        
def spawn_fun(central_addr, ib, f):
    ib.send(central_addr, (ib.addr, "spawn", f))
    def m(x):
        match x:
            case ("spawned-ok", addr):
                return addr
    return ib.receive(match=m)

##############################################################################

# launcher

# start a new occasional instance
# f is the starting user process
# if it exits, the whole system exits
#   (this could be modified in the future if needed)
# the return valueof the start call is the exit value
# of the f process
# start blocks until f exits

def start(f):
    (retvala, retvalb) = sck.socketpair()
    # protext against the user code that called this having threads
    # and stuff that isn't fork friendly
    ctx = multiprocessing.get_context('spawn')
    uf = dill.dumps(f)
    p = ctx.Process(target=central, args=[retvalb,uf])
    p.start()
    p.join()
    ret = retvala.receive_value()
    if ret is None:
        raise Exception("internal error: expected an exit value")
    return ret

