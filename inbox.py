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


Some tweakables:

option to put a message on the queue when there's a disconnection
callback for an alternative connection supplied externally
callback to handle the sock reading thread to do special
  behaviour, used to implement the socket passing stuff
  this is connection specific
potentially a callback to act on messages in a different thread
  before they are posted to the queue (a global handler, not
  connection specific)
  this is probably needed for some erlang-like features
when it moves to not using threads, then there will be a choice
  whether to run these things in background threads or not
  default will be not, but it will be strongly suggested
    to run them in background threads if you're not sure they
    are really fast, plus best practices on how to do this



"""

import sck
import contextlib
import queue
import datetime
import functools
import threading

    
class Infinity:
    def __eq__(self, other):
        return isinstance(other, Infinity)

class ReceiveTimeout:
    def __eq__(self, other):
        return isinstance(other, ReceiveTimeout)


class Inbox:
    def __init__(self, disconnect_notify=False, connect=None):
        self.q = queue.Queue()
        self.q_buffer = []
        # the connection cache is used to reuse outgoing connections
        # - if you send to an address a second time, it reuses
        # the previous connection
        # and to reuse incoming connections to send to since
        # the connection handshake tells it the address of the
        # connecting process
        self.connection_cache = {}
        self.srv = None
        self.addr = None
        self.lock = threading.RLock()
        self.disconnect_notify = disconnect_notify
        if connect is None:
            self.connect = functools.partial(Inbox.default_connect, self)
        else:
            self.connect = connect

    def close(self):
        if self.srv is not None:
            self.srv.close()
        with self.lock:
            l = list(self.connection_cache.values())
        for i in l:
            i.close()
        # todo: wipe the queue, close all the cached connections
        # join all the background threads

    # give error message when try to pickle the inbox instead
    # of sending the address
    def __getstate__(self):
        raise Exception("send inbox.addr and not the inbox")

    # set up the background thread which reads from the socket
    # and adds to the inbox queue
    # todo: save the threads and join them when the inbox is closed
    # join them when the socket is closed
    def setup_read_handler(self, sock, raddr):
        t = threading.Thread(target=Inbox.connection_handler,
                             args=[self, sock, raddr],
                             daemon=True)
        t.start()
        

    # attach an already connected socket
    # this means this socket can be used to send messages to
    # it's address, and it will be read from using the usual thread
    def attach_socket(self, raddr, sock):
        with self.lock:
            self.connection_cache[raddr] = sock
        self.setup_read_handler(sock, raddr)
        
    # connection handler is used for outgoing and incoming connections
    # to read incoming messages
    def connection_handler(self, sock, raddr):
        while True:
            x = sock.receive_value()
            match x:
                case None:
                    sock.close()
                    with self.lock:
                        del self.connection_cache[raddr]
                    if self.disconnect_notify:
                        self.q.put(("client-disconnected", raddr))
                    break
                case _:
                    self.q.put(x)

            
        
    """
move the accept handler here
when it creates an outbound connection, it should start
an accept handler on it
the accept handle q,cc should be inbox members
this means that all the init in make_inbox
  moves to the ctor of this class
the only thing left there is yield the created inbox
and call close in the finally
"""

    def default_connect(self,my_addr, connect_addr):
        sock = sck.connected_socket(connect_addr)
        sock.send_value(("hello my name is", my_addr))
        self.setup_read_handler(sock, connect_addr)
        return sock

    # used for new incoming connections made using the default
    # connect and handshake
    def default_accept_handler(self, sock, _):
        # save the connection to the cache
        # so it will be used to send outgoing messages
        # the handshake tells us what address it's for
        match sock.receive_value():
            case ("hello my name is", raddr):
                with self.lock:
                    self.connection_cache[raddr] = sock
                # read incoming messages
                self.connection_handler(sock, raddr)
            case x:
                # todo: how to handle this properly
                print(f"got bad handshake: {x}")

    def send(self, tgt, msg):
        if tgt == self.addr:
            # self send, skip pickling and sending over a socket
            self.q.put(msg)
        else:
            connect = False
            with self.lock:
                if tgt not in self.connection_cache:
                    connect = True
            if connect == True:
                sock = self.connect(self.addr, tgt)
                with self.lock:
                    self.connection_cache[tgt] = sock
            else:
                with self.lock:
                    sock = self.connection_cache[tgt]
            sock.send_value(msg)

        
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


        
    def receive(self, timeout=Infinity(), match=None):

        # handle the timeout properly when we do repeated gets
        # on non matching items
        st = datetime.datetime.now()
        def remaining_time():
            if timeout is None or timeout == Infinity() or timeout == 0:
                return timeout
            since_started = (datetime.datetime.now() - st).total_seconds()
            return timeout - since_started

        if self.q is None:
            raise Exception("cannot receive from non local inbox")

        def receive_unconditional():
            nonlocal self
            if self.q_buffer != []:
                return self.q_buffer.pop(0)

            match timeout:
                case Infinity():
                    ret = self.q.get()
                case _:
                    try:
                        t = remaining_time()
                        if t >= 0:
                            ret = self.q.get(timeout=t)
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
                    self.q_buffer = mid_receive_buffer + self.q_buffer
                    return m
                mid_receive_buffer.append(m)
                ctu = True
            else:
                #trace_print(f"received {m}")
                self.q_buffer = mid_receive_buffer + self.q_buffer
                return mx

    def __enter__(self):
        return self

    def __exit__(self,exception_type, exception_value, traceback):
        self.close()

def make_with_server(disconnect_notify=False):
    s = Inbox(disconnect_notify=disconnect_notify)
    s.srv = sck.make_socket_server(
        functools.partial(Inbox.default_accept_handler,s),
        daemon=True)
    s.addr = s.srv.addr
    return s

        
