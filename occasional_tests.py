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

def test_monitoring_proc_exits(trp):
    def monitored_proc(ib):
        x = ib.receive()
        ib.send(x, "leaving now")
    def monitoring_proc(main_addr, ib):
        (addr,_) = ib.spawn_monitor(monitored_proc)
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
        monitoring = ib.spawn(functools.partial(monitoring_proc, ib.addr))
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
    v = occasional.run(main_proc)
    trp.assert_equal("test_monitoring_proc_exits", ("ok", ("pong",)), v)
            
# sketchy, but you get something usable for troubleshooting for the
# time being
def test_send_after_process_exited(trp):
    def g(ib):
        return "exit"
        
    def f(ib):
        (addr,_) = ib.spawn_monitor(g)
        x = ib.receive()
        # todo: check it's exit?
        ib.send(addr,"hello")
        # see what happens
        #print("here")
    v = occasional.run(f)
    match v:
        case ("error", x) if "process not found" in str(x):
            trp.tpass("test_send_after_process_exited")
        case _:
            trp.fail(f"test_send_after_process_exited {v}")


def test_send_to_wrong_address1(trp):
        
    def f(ib):
        ib.send((1,2),"hello")
        # see what happens
    v = occasional.run(f)
    match v:
        case ("error", x) if "process not found" in str(x):
            trp.tpass("test_send_to_wrong_address1")
        case _:
            trp.fail(f"test_send_to_wrong_address1 {v}")
