"""x

What are some main features of Erlang process inboxes?

1. you can send messages very quickly - this is the one that this
project isn't concerned about particularly since we send pickled
Python objects over Posix sockets which is not going to compete with
local message passing speed in Erlang

2. messages are "copied" - you don't pass shared variables/memory
around

3. there's no explicit connecting: you have an address, you send
messages to it without connecting first, there's no concept of
connecting or disconnecting independently of sending messages

4. there's one input end ("socket") that a process reads to get
messages for it's inbox regardless of where they are from -> there
isn't something like a different socket for each connection/connected
client, you can only ever read from all inputs multiplexed into one
linear stream, you read everything from a single thread

5. selective receive - this allows you to read messages from your
inbox that match a predicate, and skip over any that don't match until
the next time you call receive

6. you can send the address of your inbox or an address you received
from someone else in a message, then the receiver of the message can
send messages to that address

"""

import socket_wrapper
import contextlib
import queue
import datetime

class Inbox:
    def __init__(self, addr, q):
        self.addr = addr
        # todo: find a better name for q
        self.q = q
        self.q_buffer = []

    # hack to allow sending an 'inbox' as a message
    # instead of e.g having to remember to send ib.addr
    def __getstate__(self):
        state = self.__dict__.copy()
        del state['q']
        del state['q_buffer']
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)


# todo: add a version which can be used without with
# it will have a make_inbox, and a close function
        
@contextlib.contextmanager
def make_inbox():
    q = queue.Queue()

    def accept_handler(sock, _):
        while True:
            x = sock.receive_value()
            if x is None:
                break
            q.put(x)

    srv = socket_wrapper.make_socket_server(accept_handler, daemon=True)
    try:
        yield Inbox(srv.addr, q)
    finally:
        srv.close()

def send(ib, msg):
    sock = socket_wrapper.connected_socket(ib.addr)
    sock.send_value(msg)
    sock.close()


"""

attempt to do an erlang style condition receive with optional
timeout. it would be a lot nicer with macros but the macro systems
that I found weren't compatible with python 3.10. The ux is fairly
error prone. At least you can use match.


receive spec:
unconditional receive, no timeout:

match receive():
    case ...

if the message doesn't match a branch, it will be silently ignored
instead of failing (and it won't leave the message in the inbox)

timeouts:

you can check the return value from receive for timeouts:
x = receive(timeout=5)
if isinstance(x,ReceiveTimeout):
        ....

also works:

receive(timeout=0) - onyl get messages that are already in the inbox,
don't wait

receive(timeout=Infinity()) - the default written explicity


selective receive:

create an auxiliary function

if it returns None, this signals to buffer (skip) the current message
and go to the next one

    def match1(x):
        match x:
            case ("message2",):
                return (1,x)
            case ("message1.5",):
                return (2,x)
    x = receive(match=match1)

another possible style:

    def match1(x):
        match x:
            case ("message2",):
                # do stuff
                return True
            case ("message1.5",):
                # do other stuff
                return True
    x = receive(match=match1)

the following is probably a bad idea but possible:
    def match1(x):
        match x:
            case ("message2",):
                # do stuff on a message which will be returned
                # to the buffer, mu ha ha ha
                return None
    x = receive(match=match1)


Mixing selective receive and timeouts:
    x = receive(match=match1, timeout=5)

you can catch the timeouts in the match function:

    def match1(x):
        match x:
            case ("message2",):
                return (1,x)
            case ("message1.5",):
                return (2,x)
            case ReceiveTimeout():
                return "timeout"

or in the return value as above, whichever is convenient

It's much less convenient than Erlang, but possibly a working simple
macro system or other approach can recreate something much closer to
Erlang (less boilerplate, less error prone) in Python based on this
code

 """

    
class Infinity:
    def __eq__(self, other):
        return isinstance(other, Infinity)

class ReceiveTimeout:
    def __eq__(self, other):
        return isinstance(other, ReceiveTimeout)

def receive(ib, timeout=Infinity(), match=None):

    # handle the timeout properly when we do repeated gets
    # on non matching items
    st = datetime.datetime.now()
    def remaining_time():
        if timeout is None or timeout == Infinity() or timeout == 0:
            return timeout
        since_started = (datetime.datetime.now() - st).total_seconds()
        return timeout - since_started
    
    if ib.q is None:
        raise Exception("cannot receive from non local inbox")

    def receive_unconditional():
        nonlocal ib
        if ib.q_buffer != []:
            return ib.q_buffer.pop(0)

        match timeout:
            case Infinity():
                ret = ib.q.get()
            case _:
                try:
                    t = remaining_time()
                    if t >= 0:
                        ret = ib.q.get(timeout=t)
                    else:
                        ret = ReceiveTimeout()
                except queue.Empty as e:
                    ret = ReceiveTimeout()
        return ret

    if match is None:
        return receive_unconditional()

    # handle looping until get a matching message, buffering
    # any unmatching ones

    ctu = True
    mid_receive_buffer = []
    while ctu:
        ctu = False
        m = receive_unconditional()
        mx = match(m)
        if mx is None:
            # if it was a timeout, return that
            # test after mx, so the user can either catch the timeout
            # in the cases, or as the return value
            if isinstance(m,ReceiveTimeout):
                #trace_print(f"received {m}")
                ib.q_buffer = mid_receive_buffer + ib.q_buffer
                return m
            mid_receive_buffer.append(m)
            ctu = True
        else:
            #trace_print(f"received {m}")
            ib.q_buffer = mid_receive_buffer + ib.q_buffer
            return mx
