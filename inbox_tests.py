
import multiprocessing
import functools
import time
import datetime
import yeshup

from inbox import *

SHORT_WAIT = 0.01

#############################################################################

# utility functions

# this runs f in another process, passes it a inbox
# it returns the inbox address to send to that server
def spawn(f):
    q = multiprocessing.Queue()
    def wrap_f(q,f):
        yeshup.yeshup_me()
        with make_inbox() as ib:
            q.put(ib)
            f(ib)
        
    p = multiprocessing.Process(target=wrap_f, args=[q,f])
    p.start()
    addr = q.get()
    return (addr, p)

def delayed_send_process(addr, msg, tm, ib):
    time.sleep(tm)
    ib.send(addr, msg)

def send_after_delay(addr, msg, tm):
    (_, p) = spawn(functools.partial(delayed_send_process, addr, msg, tm))
    return p

    
# read everything already in the inbox
def read_all_inbox(ib):
    ret = []
    while True:
        x = ib.receive(timeout=0)
        if x == ReceiveTimeout():
            break
        ret.append(x)
    return ret

# batteries included?
def sort_list(l):
    l1 = l.copy()
    l1.sort()
    return l1

# remove all messages from inbox and throw away
def flush_buffer(ib):
    while True:
        x = ib.receive(timeout=0)
        if x == ReceiveTimeout():
            break

def assert_is_instance(trp, nm, exp,got):
    if isinstance(got,exp):
        trp.tpass(nm)
    else:
        trp.fail(f"{nm} expected instance of {exp}, got {got} :: {type(got)}")

def assert_inbox_empty(trp, ib):
    x = read_all_inbox(ib)
    trp.assert_equal("inbox empty", [], x)

        
#############################################################################

# test cases

# create a inbox, send a message to it, read the message out of the inbox

def test_self_send(trp):
    with make_inbox() as ib:
        ib.send(ib, "hello")
        msg = ib.receive()
        trp.assert_equal("send and receive message in same process", "hello", msg)


# create a inbox in another process, send a message to it,
# get a reply
def test_send_other_process(trp):
    def srv(trp, ib):
        x = ib.q.get()
        match x:
            case (ret, v):
                ib.send(ret, ("got", v))
            case _:
                #print(f"expected (ret,v), got {x}")
                trp.fail(f"expected (ret,v), got {x}")
                # how to exit the test reliably when this happens?
                # the other side will deadlock
    # extend test framework to figure out how can pass trp to the
    # other process? update: it magically works, no idea how ...
    # use it for now and come back to it
    # usually it gives an error when you try to pickle a socket
    # if the socket is being passed, this is not reliable
    # since now there are two processes writing to the same socket
    # so there's a chance of messages being interleaved and therefore
    # corrupted

    (addr,p) = spawn(functools.partial(srv,trp))
    with make_inbox() as ib:
        ib.send(addr, (ib, "stuff"))
        msg = ib.receive()
        trp.assert_equal("exchange messages with another process", ("got", "stuff"), msg)
    p.join()                       
    
        
# create a inbox in another process
# create several client processes which all send messages
#   to the server process and get replies
#   make sure the test fails if the client messages aren't
#     received interleaved in the server -> this checks the
#     test is good enough quality

def test_many_clients(trp):

    def client_process(trp, addr, nm, n, ib):
        failed = False
        for i in range(0,n):
            ib.send(addr, (ib, i))
            x = ib.receive()
            match x:
                case ("got", m) if m == i:
                    # print(f"client {nm} {i}")
                    pass
                case _:
                    trp.fail(f"expected {('got', n)}, got {x}")
                    failed = True
        if not failed:
            trp.tpass(f"client {nm}")
        

    def server_process(trp, ib):
        while True:
            x = ib.receive()
            match x:
                case "exit":
                    # todo: check requests were interleaved
                    break
                case (addr, y):
                    #print(f"client {addr} {y}")
                    ib.send(addr, ("got", y))
                case _:
                    trp.fail(f"expected exit or (addr,x), got {x}")

    (saddr,sp) = spawn(functools.partial(server_process,trp))

    n = 50
    clis = []
    for i in range(0,10):
        (_,cp) = spawn(functools.partial(client_process, trp, saddr, f"client {i}", n))
        clis.append(cp)

    for i in clis:
        i.join()
    with make_inbox() as ib:
        ib.send(saddr, "exit")
    sp.join()

# a client sends all messages then reads the responses
# todo: do a test with a extra process per client to read the responses

def test_many_clients_pipelined(trp):

    def client_process(trp, addr, nm, n, ib):

        failed = False
        for i in range(0,n):
            ib.send(addr, (ib, i))
        expect_in_order = False
        if expect_in_order:
            for i in range(0,n):
                x = ib.receive()
                match x:
                    case ("got", m) if m == i:
                        # print(f"client {nm} {i}")
                        pass
                    case _:
                        trp.fail(f"expected {('got', n)}, got {x}")
                        failed = True
        else:
            l = []
            for i in range(0,n):
                l.append(ib.receive())
            for i in range(0,n):
                l.remove(("got", i))
            if len(l) > 0:
                trp.fail(f"wrong messages received: {l}")
                failed = True
            
        if not failed:
            trp.tpass(f"client {nm}")
        

    def server_process(trp, ib):
        while True:
            x = ib.receive()
            match x:
                case "exit":
                    # todo: check requests were interleaved
                    break
                case (addr, y):
                    #print(f"client {addr} {y}")
                    ib.send(addr, ("got", y))
                case _:
                    trp.fail(f"expected exit or (addr,x), got {x}")

    (saddr,sp) = spawn(functools.partial(server_process,trp))

    n = 50
    clis = []
    for i in range(0,10):
        (_,cp) = spawn(functools.partial(client_process, trp, saddr, f"rpcs {i}", n))
        clis.append(cp)

    for i in clis:
        i.join()
    with make_inbox() as ib:
        ib.send(saddr, "exit")
    sp.join()

    
######################################

# timeout tests

def test_timeout0_empty(trp):
    with make_inbox() as ib:
        msg = ib.receive(timeout=0)
        trp.assert_equal("receive timeout 0 empty inbox", ReceiveTimeout(), msg)


def test_timeout0_nonempty(trp):
    with make_inbox() as ib:
        ib.send(ib, "xx")
        time.sleep(SHORT_WAIT)
        msg = ib.receive(timeout=0)
        trp.assert_equal("receive timeout 0 non empty inbox", "xx", msg)


# timeout with posting a message too late to check it times out
# then it reads the message without a timeout to make sure it comes through

def test_timeout_timesout(trp):
    with make_inbox() as ib:
        send_after_delay(ib, "xxx", SHORT_WAIT * 2)
        st = datetime.datetime.now()
        msg = ib.receive(timeout=SHORT_WAIT)
        trp.assert_equal("receive timeout times out", ReceiveTimeout(), msg)

        elapsed = (datetime.datetime.now() - st).total_seconds()
        trp.assert_true("timeout time", (elapsed - SHORT_WAIT) < 0.01)

        msg = ib.receive()
        trp.assert_equal("receive timeout get after timeout", "xxx", msg)



def test_timeout_explicit_infinity(trp):
    with make_inbox() as ib:
        send_after_delay(ib, "xxx", SHORT_WAIT * 2)
        msg = ib.receive(timeout=Infinity())
        trp.assert_equal("timeout explicit infinity", "xxx", msg)

def test_read_all_inbox(trp):
    with make_inbox() as ib:
        msgs = ['a', 'b', 'c']
        for i in msgs:
            ib.send(ib, i)
        time.sleep(SHORT_WAIT)
        res = read_all_inbox(ib)
        trp.assert_equal("read all buffer", sort_list(msgs), sort_list(res))
        time.sleep(SHORT_WAIT)
        res2 = read_all_inbox(ib)
        trp.assert_equal("read all buffer empty", [], res2)

def test_flush_buffer(trp):
    with make_inbox() as ib:
        msgs = ['a', 0, True]
        for i in msgs:
            ib.send(ib, i)
        time.sleep(SHORT_WAIT)
        flush_buffer(ib)
        res2 = read_all_inbox(ib)
        trp.assert_equal("read all buffer empty", [], res2)
    
######################################

# selective receive

# test some selective receive stuff

# test get everything matching predicate in buffer


def test_selective_receive1(trp):
    with make_inbox() as ib: 

        ib.send(ib, ("message1",))
        ib.send(ib, ("message1.5",))
        ib.send(ib, ("message2",))

        def match1(x):
            #print(f"match1 {x}")
            match x:
                case ("message2",):
                    #print(f"2 {x}")
                    return (1,x)
                case ("message1.5",):
                    #print(f"1.5 {x}")
                    return (2,x)
        x = ib.receive( match=match1)
        trp.assert_equal("test_selective_receive1 1", x, (2,("message1.5",)))
        x = ib.receive( match=match1)
        trp.assert_equal("test_selective_receive1 2", x, (1,("message2",)))

        x = ib.receive()
        trp.assert_equal("test_selective_receive1 3", x, ("message1",))

        # timeout style one: without a case for this
        x = ib.receive( match=match1, timeout=0)
        assert_is_instance(trp, "test_selective_receive1 4", ReceiveTimeout, x)
        assert_inbox_empty(trp, ib)

def test_selective_receive2(trp):
    with make_inbox() as ib: 
        # timeout style two: using a case in the match function
        def match2(x):
            #print(x)
            #print(f"{x}")
            match x:
                case ("message2",):
                    #print('{("message2",)}')
                    #print(f"2 {x}")
                    return (1,x)
                case ("message1.5",):
                    #print(f"1.5 {x}")
                    return (2,x)
                case ReceiveTimeout():
                    #print(f"timeout")
                    return "timeout"
        x = ib.receive( match=match2, timeout=0)
        trp.assert_equal("test_selective_receive2", "timeout", x)
        assert_inbox_empty(trp, ib)

def test_selective_receive3(trp):
    with make_inbox() as ib: 
        # post a couple of messages that don't match

        ib.send(ib, ("message1",))
        ib.send(ib, ("message1.5",))
        # post another message that does match with delay
        send_after_delay(ib, ("message2",), SHORT_WAIT)
        # post another message that does match (done in a spawned process)
        # then get matching the second
        # then get matching the first
        def match3(x):
            match x:
                case ("message2",):
                    return x
        # check with 0 timeout it times out
        x = ib.receive( match=match3, timeout=0)
        assert_is_instance(trp, "test_selective_receive3 1", ReceiveTimeout, x)
        # check waiting for the matching message to be posted
        x = ib.receive( match=match3)
        trp.assert_equal("test_selective_receive3 2", ("message2",), x)

        # get the other two messages in reverse order
        def match4(x):
            match x:
                case ("message1.5",):
                    return x
        x = ib.receive( match=match4)
        trp.assert_equal("test_selective_receive3 3", ("message1.5",), x)

        x = ib.receive()
        trp.assert_equal("test_selective_receive3 4", ("message1",), x)
        assert_inbox_empty(trp, ib)

def test_timeout_with_unmatching_message(trp):
    """
receive with timeout
  theres a message which doesn't match, which gets
  added to the buffer
  let it timeout
  then do a regular receive
    """
    with make_inbox() as ib:
        ib.send(ib, 1)
        def m(x):
            match x:
                case 2:
                    return 2
        x = ib.receive(timeout=SHORT_WAIT,match=m)
        assert_is_instance(trp, "test_timeout_with_unmatching_message 1", ReceiveTimeout, x)
        x = ib.receive()
        trp.assert_equal("xx", 1, x)

        send_after_delay(ib, 1, SHORT_WAIT)
        def m(x):
            match x:
                case 2:
                    return 2
        x = ib.receive(timeout=SHORT_WAIT * 2,match=m)
        assert_is_instance(trp, "test_timeout_with_unmatching_message 2", ReceiveTimeout, x)
        x = ib.receive()
        trp.assert_equal("xx", 1, x)

        
def test_timeout_with_unmatching_message2(trp):
    """
do a match which matches the second message
then get the first message
"""
    with make_inbox() as ib:
        def m(x):
            match x:
                case 2:
                    return 2
        send_after_delay(ib, 1, SHORT_WAIT)
        send_after_delay(ib, 2, SHORT_WAIT * 2)
        x = ib.receive(timeout=SHORT_WAIT * 3,match=m)
        trp.assert_equal("test_timeout_with_unmatching_message2 1", 2, x)
        x = ib.receive()
        trp.assert_equal("test_timeout_with_unmatching_message2 2", 1, x)

def test_timeout_with_delayed_unmatching_messages(trp):
    """
set a timeout of x seconds
post an unmatching message after x * 0.9
then again after x * 0.9
repeat a few more times
post the matching message at the end so it will match
  and never timeout if there's a timeout bug
check the timeout took how long it's supposed to
instead of continually stretching
"""
    with make_inbox() as ib:
        send_after_delay(ib, 1, SHORT_WAIT * 0.8)
        send_after_delay(ib, 1, SHORT_WAIT * 1.6)
        send_after_delay(ib, 1, SHORT_WAIT * 2.4)
        send_after_delay(ib, 2, SHORT_WAIT * 3.2)
        def m(x):
            match x:
                case 2:
                    return 2
        st = datetime.datetime.now()
        x = ib.receive(timeout=SHORT_WAIT * 2,match=m)
        assert_is_instance(trp,
                           "test_timeout_with_delayed_unmatching_messages 1",
                           ReceiveTimeout,
                           x)
        elapsed = (datetime.datetime.now() - st).total_seconds()
        # todo: fix the fuzz factor properly
        trp.assert_true("test_timeout_with_delayed_unmatching_messages 2",
                        (elapsed - SHORT_WAIT * 1.2) < 0.1)
        ib.receive()
        ib.receive()
        ib.receive()
        ib.receive()



##############################################################################

# all_tests = [ \
#               test_self_send,
#               test_send_other_process,
#               test_many_clients,
#               test_many_clients_pipelined,
#               test_timeout0_empty,
#               test_timeout0_nonempty,
#               test_timeout_timesout,
#               test_timeout_explicit_infinity,
#               test_read_all_inbox,
#               test_flush_buffer,
#               test_selective_receive1,
#               test_selective_receive2,
#               test_selective_receive3,
#               test_timeout_with_unmatching_message,
#               test_timeout_with_unmatching_message2,
#               test_timeout_with_delayed_unmatching_messages,
#              ]
