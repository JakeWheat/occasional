import functools
import os
import signal
import time
import sys

import occasional

def test_trivial_run(trp):
    def f(ib):
        return "hello"

    v = occasional.run(f)
    trp.assert_equal("return val", ("ok", "hello"), v)

def test_system_exit_0(trp):
    def f(ib):
        sys.exit(0)

    v = occasional.run(f)
    trp.assert_equal("return val", ("ok", ("exitcode", 0)), v)

    
def test_ping_cs(trp):
    def f(ib):
        #print(f"send to {cs.addr}")
        ib.send(ib.central, (ib.addr, "ping"))
        x = ib.receive()
        return x
        # todo: restore this here when the test framework
        # is updated
        #trp.assert_equal("pong", ("pong",), x)
    v = occasional.run(f)
    trp.assert_equal("pong return val", ("ok", ("pong",)), v)

def test_simple_spawn(trp):
    def g(ib):
        (addr, msg) = ib.receive()
        ib.send(addr, ("return", msg))
    def f(ib):
        msp = ib.spawn(g)
        ib.send(msp, (ib.addr, "test"))
        x = ib.receive()
        return x
        #trp.assert_equal("spawn return", ("return", "test"), x)
    v = occasional.run(f)
    trp.assert_equal("simple spawn exit", ("ok", ("return", "test")), v)


"""
TODO
check nested occasional -> this is important for the testing
  do the test above:
    launch a process
      it launches another process
        asks that process to start
          that process does the test above
        then sends a message back to the original process
"""

def test_check_right_exit(trp):
    # start a process, then exit it, then exit the main
    # process, check get the right exit value
    def f(ib):
        return "inner exit"
    def g(ib):
        ib.spawn(f)
        time.sleep(0.1)
        return "outer exit"
    v = occasional.run(g)
    trp.assert_equal("spawn_monitor_exit_0", ("ok", "outer exit"), v)

def check_down_message(trp,msg,exp,got):
    match got:
       case ('down', _, _, x):
           trp.assert_equal(msg, exp, x)
       case _:
           trp.fail(f"{msg} {got}")
    
def check_monitor_exit(trp, msg, exit_val, got):
    match got:
       case ('ok', x):
           check_down_message(trp, msg, exit_val, x)
       case _:
           trp.fail(f"{msg} {got}")

def test_spawn_monitor_exit_0(trp):
    def g(ib):
        sys.exit(0)
    def f(ib):
        ib.spawn_monitor(g)
        x = ib.receive()
        return x
    v = occasional.run(f)
    check_monitor_exit(trp, "spawn_monitor_exit_0",
                       ('ok', ('exitcode', 0)), v)


def test_spawn_monitor_sigterm(trp):
    def g(ib):
        os.kill(os.getpid(), signal.SIGTERM)
    def f(ib):
        x = ib.spawn_monitor(g)
        return ib.receive()
    v = occasional.run(f)
    check_monitor_exit(trp, "spawn_monitor_sigterm",
                       ('error', ('signal', 'Terminated')), v)

def test_spawn_monitor_return_val(trp):
    def g(ib):
        return "exit value"
    def f(ib):
        x = ib.spawn_monitor(g)
        return ib.receive()
    v = occasional.run(f)
    check_monitor_exit(trp, "spawn_monitor_return_val",
                       ("ok", "exit value"), v)

def test_spawn_monitor_uncaught_exception(trp):
    def g(ib):
        raise Exception("hello")
    def f(ib):
        x = ib.spawn_monitor(g)
        return ib.receive()
    v = occasional.run(f)

def test_spawn_monitor_exit_delay(trp):
    def g(ib):
        match ib.receive():
           case (addr,v):
               ib.send(addr,("hello", v))
           case x:
               print(x)
               raise Exception(str(x))
        
    def f(ib):
        (addr,_) = ib.spawn_monitor(g)
        ib.send(addr,(ib.addr, "hello"))
        x = ib.receive()
        y = ib.receive()
        return (x,y)
    v = occasional.run(f)
    match v:
        case ('ok', (('hello','hello'), ('down', _, _, v))):
            trp.assert_equal("test_spawn_monitor_exit_delay",
                             ('ok', ('exitcode', 0)),v)
            
        case _:
            trp.fail("test_spawn_monitor_exit_delay {v}")

