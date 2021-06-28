import functools
import os
import signal
import time
import sys
import traceback

import occasional

def test_trivial_run(trp):
    def f(ib):
        return "hello"

    v = occasional.run_inbox(f)
    trp.assert_equal("return val", ("ok", "hello"), v)

def test_system_exit_0(trp):
    def f(ib):
        sys.exit(0)

    v = occasional.run_inbox(f)
    trp.assert_equal("return val", ("ok", ("exitcode", 0)), v)

    
def test_ping_cs(trp):
    def f(trp, ib):
        ib.send(ib.central, (ib.addr, "ping"))
        x = ib.receive()
        trp.assert_equal("pong", ("pong",), x)
    occasional.run_inbox(functools.partial(f, trp))

def test_simple_spawn(trp, mod=""):
    def g(ib):
        (addr, msg) = ib.receive()
        ib.send(addr, ("return", msg))
    def f(trp, ib):
        msp = ib.spawn_inbox(g)
        ib.send(msp, (ib.addr, "test"))
        x = ib.receive()
        trp.assert_equal(f"{mod} spawn return", ("return", "test"), x)
    occasional.run_inbox(functools.partial(f, trp))

# sanity check to see if it looks like running a new occasional
# instance from an occasional process works
def test_nested_occasional(trp):
    def f(trp, ib):
        test_simple_spawn(trp, "nested")
    
    occasional.run_inbox(functools.partial(f, trp))

def test_check_right_exit(trp):
    # start a process, then exit it, then exit the main
    # process, check get the right exit value
    def f(ib):
        return "inner exit"
    def g(ib):
        ib.spawn_inbox(f)
        time.sleep(0.1)
        return "outer exit"
    v = occasional.run_inbox(g)
    trp.assert_equal("spawn_monitor_exit_0", ("ok", "outer exit"), v)

def check_down_message(trp,msg,exp,got):
    match got:
       case ('down', _, _, x):
           trp.assert_equal(msg, exp, x)
       case _:
           trp.fail(f"{msg} didn't get expected down message: {exp} {got}")
    
def check_monitor_exit(trp, msg, exit_val, got):
    match got:
       case ('ok', x):
           check_down_message(trp, msg, exit_val, x)
       case _:
           trp.fail(f"{msg} didn't get expected down message: {got}")

def test_spawn_monitor_exit_0(trp):
    def g(ib):
        sys.exit(0)
    def f(trp, ib):
        ib.spawn_inbox_monitor(g)
        x = ib.receive()
        check_down_message(trp, "spawn_monitor_exit_0",
                           ('ok', ('exitcode', 0)), x)
    occasional.run_inbox(functools.partial(f,trp))


def test_spawn_monitor_sigterm(trp):
    def g(ib):
        os.kill(os.getpid(), signal.SIGTERM)
    def f(trp, ib):
        ib.spawn_inbox_monitor(g)
        x = ib.receive()
        check_down_message(trp, "spawn_monitor_sigterm",
                           ('error', ('signal', 'Terminated')), x)
        
    occasional.run_inbox(functools.partial(f, trp))

def test_spawn_monitor_return_val(trp):
    def g(ib):
        return "exit value"
    def f(ib):
        ib.spawn_inbox_monitor(g)
        x = ib.receive()
        check_down_message(trp, "spawn_monitor_return_val",
                           ("ok", "exit value"), x)
    occasional.run_inbox(f)

def test_spawn_monitor_uncaught_exception(trp):
    def g(ib):
        raise Exception("hello")
    def f(ib):
        x = ib.spawn_inbox_monitor(g)
        return ib.receive()
    v = occasional.run_inbox(f)

def test_spawn_monitor_exit_delay(trp):
    def g(ib):
        match ib.receive():
           case (addr,v):
               ib.send(addr,("hello", v))
           case x:
               print(x)
               raise Exception(str(x))
        
    def f(ib):
        (addr,_) = ib.spawn_inbox_monitor(g)
        ib.send(addr,(ib.addr, "hello"))
        x = ib.receive()
        y = ib.receive()
        return (x,y)
    v = occasional.run_inbox(f)
    match v:
        case ('ok', (('hello','hello'), ('down', _, _, v))):
            trp.assert_equal("test_spawn_monitor_exit_delay",
                             ('ok', ('exitcode', 0)),v)
            
        case _:
            trp.fail("test_spawn_monitor_exit_delay {v}")

def test_monitoring_proc_exits(trp):
    def monitored_proc(ib):
        x = ib.receive()
        ib.send(x, "leaving now")
    def monitoring_proc(main_addr, ib):
        (addr,_) = ib.spawn_inbox_monitor(monitored_proc)
        ib.send(main_addr, addr)
        # exits
    def main_proc(ib):
        # p0 starts a process to do the monitoring
        # it starts a monitored process
        # it sends the monitored process back to p0
        # then it exits
        # the monitored process waits for p0 to send
        # a message, then it sends a reply and exits
        # p0 gets this reply, then pings central services
        # to check it's still going
        monitoring = ib.spawn_inbox(functools.partial(monitoring_proc, ib.addr))
        monitored_addr = ib.receive()
        ib.send(monitored_addr, ib.addr)
        match ib.receive():
            case "leaving now":
                pass
            case x:
                return x
        ib.send(ib.central, (ib.addr, "ping"))
        x = ib.receive()
        return x
    v = occasional.run_inbox(main_proc)
    trp.assert_equal("test_monitoring_proc_exits", ("ok", ("pong",)), v)


def raises_satisfies(trp, msg, f, pred):
    try:
        f()
        trp.fail(f"expected exception {msg} but didn't raise)")
    except Exception as e:
        if pred(e):
            trp.tpass(msg)
        else:
            trp.fail(f"{msg} exception failed predicate {type(e)} {e}")

def exception_matches_text(txt, e):
    return txt in str(e)

def is_process_not_found(e):
    return "process not found" in str(e)
    
# sketchy, but you get something usable for troubleshooting for the
# time being
def test_send_after_process_exited(trp):
    def g(ib):
        return "exit"
        
    def f(ib):
        (addr,_) = ib.spawn_inbox_monitor(g)
        x = ib.receive()
        # todo: check it's exit?
        ib.send(addr,"hello")
        # see what happens
        #print("here")
    raises_satisfies(trp, "test_send_after_process_exited",
                     lambda: occasional.run_inbox(f), is_process_not_found)

def test_send_to_wrong_address1(trp):
        
    def f(ib):
        ib.send((1,2),"hello")
        # see what happens
    raises_satisfies(trp, "test_send_to_wrong_address1",
                     lambda: occasional.run_inbox(f), is_process_not_found)


def test_main_system_exit_nonzero(trp):
    def f(ib):
        os._exit(1)
    raises_satisfies(trp, "test_main_system_exit_nonzero",
                     lambda: occasional.run_inbox(f),
                     functools.partial(exception_matches_text, "exited with exit code"))

def test_main_signal(trp):
    def f(ib):
        os.kill(os.getpid(), signal.SIGTERM)
    raises_satisfies(trp, "test_main_signal",
                     lambda: occasional.run_inbox(f),
                     functools.partial(exception_matches_text, "exited with signal"))

    
    
def test_non_callable_main(trp):
    not_a_function = 5
    raises_satisfies(trp, "test_non_callable_main",
                     lambda: occasional.run_inbox(not_a_function),
                     functools.partial(exception_matches_text, "is not callable"))

    
def test_non_callable_spawn(trp):
    def f(trp, ib):
        not_a_function = 5
        raises_satisfies(trp, "test_non_callable_spawn",
                     lambda: ib.spawn_inbox(not_a_function),
                     functools.partial(exception_matches_text, "is not callable"))
    occasional.run_inbox(functools.partial(f,trp))

def test_too_few_args_main(trp):
    def f(ib, x, y):
        pass
    raises_satisfies(trp, "test_too_few_args_main",
                     lambda: occasional.run_inbox(functools.partial(f,1)),
                     functools.partial(exception_matches_text,
                                       "missing 1 required positional argument"))

def test_too_many_args_main(trp):
    def f(ib, x, y):
        pass
    raises_satisfies(trp, "test_too_many_args_main",
                     lambda: occasional.run_inbox(functools.partial(f,1,2,3)),
                     functools.partial(exception_matches_text,
                                       "takes 3 positional arguments but 4 were given"))

    
def test_too_many_args_spawn(trp):

    def f(trp, ib):
        def g(x,y,ib):
            pass

        ib.spawn_inbox_monitor(functools.partial(g,1,2,3))
        x = ib.receive()
        # doesn't come through as an exception on the spawn
        # can't work out how to do this
        match x:
           case ('down', _, _, ('error', (x,_))) if 'takes 3 positional arguments but 4 were given' in str(x):
               trp.tpass("test_too_many_args_spawn")
           case _:
               trp.tfail(f"test_too_many_args_spawn: expected ('down', _, _, ('error', ('args error', _))) but got {x}")
        
    occasional.run_inbox(functools.partial(f,trp))

def test_error_no_monitor(trp):
    def g(ib):
        raise Exception("goodbye")

    def f(ib):
        ib.spawn_inbox(g)
        time.sleep(0.1)

    occasional.run_inbox(f)
    # TODO: run this test in another process
    # and capture the stdout/stderr and check for the trace message
    trp.tpass("test_error_no_monitor")

def test_sub_process_killed(trp):
    def g(ib):
        raise Exception("goodbye")

    def f(ib):
        ib.spawn_inbox(g)

    occasional.run_inbox(f)
    # if the g keeps running normally after f exits,
    # it will try to send a message to central on a broken socket,
    # because central has exited, want to avoid this
    # the tricky thing is that we want errors if this happens at
    # any other time
    # TODO: run this test in another process
    # and capture the stdout/stderr and check for messages
    trp.tpass("test_error_no_monitor")

from occasional import send, receive, spawn, slf, central_addr
# something weird is happening when you write occasional.receive
# instead of importing it. Maybe dill is doing something really
# odd with the recursive pickling

def test_implicit(trp):
    def g():
        match receive():
            case (frm,x):
               send(frm, ("got", x))
    def f(trp):
        try:
            send(central_addr(), (slf(), "ping"))
            x = receive()
            trp.assert_equal("pong", ("pong",), x)
            gpid = spawn(g)
            send(gpid, (slf(), "hello"))
            x = receive()
            trp.assert_equal("reply", ("got", "hello"), x)
        except:
            print("except in user code")
            traceback.print_exc()
            raise
    occasional.run(functools.partial(f,trp))

def test_top_level(trp):
    def g():
        match receive():
            case (frm,x):
               send(frm, ("got", x))
    try:
        occasional.start()
        send(central_addr(), (slf(), "ping"))
        x = receive()
        trp.assert_equal("pong", ("pong",), x)
        gpid = spawn(g)
        send(gpid, (slf(), "hello"))
        x = receive()
        trp.assert_equal("reply", ("got", "hello"), x)
    finally:
        occasional.stop()

# todo: test code which mixes implicit and explicit inbox

