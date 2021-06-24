
"""

launch a process
it returns a value
check the value

launch a process
it throws an exception
check the value

launch a process
it launches a second process
exchange values
return

check nested occasional -> this is important for the testing
  do the test above:
    launch a process
      it launches another process
        asks that process to start
          that process does the test above
        then sends a message back to the original process


test spawn_monitor with a few different exits
  -> value, exception, signal



"""

import occasional
import functools

def test_trivial_run(trp):
    def my_process(ib):
        return "hello"

    v = occasional.start(my_process)
    trp.assert_equal("return val", ("ok", "hello"), v)

def test_ping_cs(trp):
    def my_process(ib):
        #print(f"send to {cs.addr}")
        ib.send(ib.central, (ib.addr, "ping"))
        x = ib.receive()
        return x
        #trp.assert_equal("pong", ("pong",), x)
    v = occasional.start(functools.partial(my_process))
    trp.assert_equal("pong return val", ("ok", ("pong",)), v)

def test_simple_spawn(trp):
    def my_sub_process(ib):
        (addr, msg) = ib.receive()
        ib.send(addr, ("return", msg))
    def my_process(ib):
        msp = ib.spawn(my_sub_process)
        ib.send(msp, (ib.addr, "test"))
        x = ib.receive()
        return x
        #trp.assert_equal("spawn return", ("return", "test"), x)
    v = occasional.start(my_process)
    trp.assert_equal("simple spawn exit", ("ok", ("return", "test")), v)
