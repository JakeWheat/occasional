#!/usr/bin/env python3

"""x

Tests todo

large netstring split success and errors
  -> try with 1MB
test sending super large netstrings and then the other side fails
while the sending side is blocked on a partial send



timeouts: what can block, what should have timeout support?
  timeout in the middle of receiving a message
    -> should it timeout the total time trying to receive
       or just when it's idle without getting any new bytes?
  it doesn't timeout idle connections
connect, sendall and recv all have a timeout in the python api
  can this be used?

other things that could time out:
get (and put?) on queues
joining threads, processes
which socket api calls are like this?
running test cases/suites
starting to listen?


anomaly tests: send part of a netstring then close the connection
can stop:
during the size digits at the start
after the :
in the middle of the bytes
just before writing the ,

test regular and anomaly behaviours in sequence on the same processes
-> also see if can find a way to compose them randomly


reason about all the error conditions that are regarded as normal
-> this should not be reported anywhere usually, but there should
  be a trace mode that future user code can use to see all of these
  for debugging - e.g. there are a few places it catches exceptions
    and ignores them

reason about the blanket thing which returns any error when closing
  as a value instead of raising it. is this the best approach?


test trying to listen on an in use socket
then check the previous server still works
ask it to stop listening and start listening on same port quickly,
  check it works
and then check the server which failed while in use
  can start listening on another port and it works
  and can start listening on the original port and it works
    after making it available

check code for race conditions
  -> main ones to fix right now are the vars shared across threads


check code for exception vulnerability:
  run_listener
    handle_receiving
  main server process loop
  client handle receive
  main client process loop
->
  create a wrapper for exceptions other than the network ones
    what should it do here?
    can just log and rethrow?
    in the real system, there's an obvious answer which isn't
    obvious for this demo code
  want to protect as best as possible about programming errors in the implementation
    as well as user code issues - so at least it gives sensible errors and behaviour
    that you can troubleshoot, and if the error only affects some code, the rest
    of the code has the best chance of limping on instead of definitely going wrong
  - throw exceptions from lots of different places to see the system
    behaves nicely still
     -> start by making a list of these locations
  if the client socket is open - there is the main loop
    and the receive loop which must not exit
    exiting these and the socket stopping being open for business
    should be the same thing
  similar comments for the server, but it has the additional listener
    aspect too
  how can this be automated?


try to get a connection reset error and make sure it gets cleaned up
  write a test that loops trying to get it
  and finishes after a timeout with a fail
    or the instant it notices the reset error and can check
    the behaviour of the system after this


not testing for stuff that can happen on the network, since all the
testing right now is local
-> this includes timeouts
not sure under which situations you will get a synchronous notification
  of a connection issue, and what situations it can disappear or hang,
  and the system will hang with it or wait for a timeout somewhere
  in the stack
  a general solution here can be application level timeouts
    which should work whatever the issue
    these can include timeouts in this library code,
      or user timeouts in the code that uses this library
can port the tests to run on two machines with one process on each machine
have to do some research to see how to simulate network issues that
aren't straight forward to automate like this - maybe there's some
simulation techniques available using containers? or just virtual networking?
 -> this needs an explicit and accurate simulation for each kind of
   error that can happen in the real world:
   if you can't simulate it, you can't really test or prepare for it
   if you don't explicitly know about it, you're not likely to come across
     it by accident no matter how much random simulation you try to do
this will be a lot easier than having to pull an ethernet cable
  or move a laptop out of wireless range during automated tests ...
  and a lot cheaper than trying to find flakey network hardware
  or exotic network hardware that can simulate issues



do some stability/resource leak tests:
  run stuff for a long time, mix of regular stuff and anomalies
    which don't crash the processes
  check that it doesn't leak sockets or file descriptors, or other resources
  check that it doesn't keep increasing mem
  check that the performance stays the same
  check that it doesn't crash


come up with some denial of service/flood/swamp style activities, and
write some tests to see what happens when you do them

anomaly testing: check using the socket_wrapper api wrong

review - see if doing all of these that should be done:
check for basic errors in interacting with the processes
check asking to listen twice
check asking to unlisten when not listening
ask to disconnect when not connected
check send when not listening
check send when client not connected
  -> catch before trying to do this
     and after doing them, then stopping them
run through all the other anomalies already implemented
  or written in the design docs below

it sends an error to the other side of the socket when there's an error
that causes it to close the socket, such as a bad netstring, bad pickle,
  and this will include timeout
-> do some anomaly testing where there is a problem sending this error
   message
  try to set it up so both sides send an error for a malformed netstring
    at the same time, check it's behaviour


do testing for multiple clients and servers, especially anomaly
  concurrently with normal operations

benchmark throughputs

do some reference benchmarks for performance regressions?

use classes for status messages? use an enum because there's a lot of
them. check this works with match

Some categories of anomalies:

1. sending a bad netstring
2. timeout during send or receive
3. timeout during connect
4. disconnection
   two aspects: when and how
   when:
     connection idle
     in the middle of sending a netstring
     in the middle of receiving a netstring
       (for both these, there is small and large variants,
       and the sender can be the client or the server
   how - most of these can happen on either end - the client, or the server
      close the socket nicely
      close the socket without using shutdown
      exit the thread with the socket without closing the socket
        what are the different ways a thread can exit?
      exit the process without closing the socket:
        python exit 0 or other
        _exit 0 or other
        uncaught exception
        leaving end of code (implicit 0 exit)
        signals

do a matrix of these to test the other side gets the right errors and
status updates
and also check the other side continues to work fine with a new
connection

spam client/server:
  run both
  the client will keep connecting and disconnecting,
    maybe a variant with some message sending also
  and one or the other keeps getting killed
  and then it's restarted and does the same
  we're checking the other side continues to work and doesn't
    leak resources
  do a range of random number ranges for sleeps in the kill
    and in the connect/message/disconnect loops
  need to be able to recover from any error with this, and
  log all the information so it can be reproduced and the fix
  verified


server stop listening when client is connected
  -> this should not disconnect?
check client connect
then server stops listening
then exchange messages
then disconnect client
do the same, but try to connect with another client, check it
  errors
do the same, but start the server listening while the client
  remains connected
  try connecting with another client, check it fails
  disconnect the first client
  try connecting again, check it succeeds



"""


import threading
import socket
import dill
import sys
import traceback
import multiprocessing
import time
import os
import datetime
import inspect
import signal
import contextlib
import random
import tempfile
import socket_wrapper
import test_framework
import get_proc_socket_info
import yeshup

short_wait = 0.001

# todo: don't fix this in a global
socket_type = socket.AF_INET
#socket_type = socket.AF_UNIX


##############################################################################

def handle_net_exception(rec_queue, sock):
    ev = ("error", sysinfo_to_value(sys.exc_info()))
    rec_queue.put(ev)
    try:
        sock.send_value(ev)
    except:
        pass
        # rec_queue.put(("error", sysinfo_to_value(sys.exc_info())))

        
def server_process_fn(server_receive_queue, server_send_queue):
    yeshup.yeshup_me()

    # socket for an incoming active connection. this demo supports max one of
    # these at a time
    connection_sock = None
    listener = None

    def connection_open():
        nonlocal connection_sock
        return connection_sock is not None and connection_sock.is_open()

    def listen_open():
        nonlocal listener
        return listener is not None and listener.is_running()

    def accept_fn(sock, _):
        nonlocal connection_sock, server_receive_queue
        try:
            connection_sock = socket_wrapper.ValueSocket(sock)
            server_receive_queue.put(("client-connected",))
            while True:
                try:
                    msg = connection_sock.receive_value()
                    if msg is None:
                        break
                    server_receive_queue.put(msg)
                except:
                    handle_net_exception(server_receive_queue, connection_sock)
                    break
        except:
            print("exception in acceptor")
            traceback.print_exc()
        finally:
            connection_sock.close()
            connection_sock = None
            server_receive_queue.put(("disconnected",))
    
    def exit_listener():
        nonlocal connection_sock, listener
        if connection_sock is not None:
            connection_sock.close()
            connection_sock = None
        if listener is not None:
            listener.close()
            listener = None


    # exception handling:
    # if we get any exception leaking out, this is a programming error
    # in the code. ideally, we want to try to clean up as much as possible
    # and exit the process, this allows any following tests in the same
    # run the best chance of executing properly
    while True:
        x = server_send_queue.get()
        match x:
            case ("listen",):
                # check if already listening
                if listen_open():
                    server_receive_queue.put(("error", "already-listening"))
                else:
                    listener = socket_wrapper.SocketServer(accept_fn, daemon=True)
                    server_receive_queue.put(("listen-addr", listener.addr))
            case ("unlisten",):
                if not listen_open():
                    server_receive_queue.put(("error", "not-listening"))
                else:
                    exit_listener()
                    server_receive_queue.put(("unlistening",))
            case ("send", msg):
                if not connection_open():
                    server_receive_queue.put(("error", "not-connected"))
                else:
                    try:
                        connection_sock.send_value(msg)
                    except:
                        server_receive_queue.put(("error", sysinfo_to_value(sys.exc_info())))
                        connection_sock.close()
            case ("send-special", msg):
                if not connection_open():
                    server_receive_queue.put(("error", "not-connected"))
                else:
                    try:
                        connection_sock.send_raw(msg)
                    except:
                        server_receive_queue.put(("error", sysinfo_to_value(sys.exc_info())))
                        connection_sock.close()
            case ("close",):
                exit_listener()
                break
            case x:
                raise Exception(f"unknown message {x}")
    # todo: put this in a finally?
    # if there's an exception at this point, put it on the server receive queue
    exit_listener()
    server_receive_queue.put(("closed",))

multiprocessing_spawn = 'fork'
    
def run_server():
    server_receive_queue = multiprocessing.Queue()
    server_send_queue = multiprocessing.Queue()

    ctx = multiprocessing.get_context(multiprocessing_spawn)
    p = ctx.Process(target=server_process_fn, args=[server_receive_queue, server_send_queue])
    p.daemon=True
    p.start()

    return (p, server_receive_queue, server_send_queue)



# helper function to start listening and get the port

# todo: add special case for the server already listening error

def start_server_listening(server_receive_queue, server_send_queue):
    server_send_queue.put(("listen",))
    match server_receive_queue.get():
        case (("listen-addr", a)):
            return a
        case x:
            raise Exception(f"expected listen-add, got {x}")

@contextlib.contextmanager
def server_manager():
    srv = run_server()
    try:
        yield srv
    finally:
        try:
            os.kill(srv[0].pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        srv[0].join()

##############################################################################
    
def client_process_fn(client_receive_queue, client_send_queue):
    yeshup.yeshup_me()

    connection_sock = None
    receive_thread = None

    def handle_receive():
        nonlocal connection_sock, client_receive_queue
        while True:
            try:
                msg = connection_sock.receive_value()
                if msg is None:
                    break
            except:
                handle_net_exception(client_receive_queue, connection_sock)
                break
            client_receive_queue.put(msg)
        connection_sock.close()
        
        client_receive_queue.put(("disconnected",))
        # todo: check for exceptions leaking out here
        # -> best effort clean up, and report on the status queue

    def stop_connection():
        nonlocal connection_sock, receive_thread
        if connection_sock is not None:
            connection_sock.close()
        if receive_thread is not None:
            receive_thread.join()
            receive_thread = None
        
    def connection_open():
        nonlocal connection_sock
        return connection_sock is not None and connection_sock.is_open()
            
    while True:
        msg = client_send_queue.get()
        match msg:
            case ("connect", addr):
                if connection_open():
                    client_receive_queue.put(("error", "already-connected"))
                else:
                    try:
                        connection_sock = socket_wrapper.ValueSocket(socket_type=socket_type)
                        connection_sock.connect(addr)
                        # can this fail? in what situations?
                        receive_thread = threading.Thread(target=handle_receive)
                        receive_thread.daemon = True
                        receive_thread.start()
                        client_receive_queue.put(("connected",))
                    except:
                        client_receive_queue.put(("error", sysinfo_to_value(sys.exc_info())))
                        connection_sock.close()
            case ("disconnect",):
                if not connection_open():
                    client_receive_queue.put(("error", "not-connected"))
                else:
                    stop_connection()
            case ("close",):
                stop_connection()
                break
            case ("send", msg):
                if not connection_open():
                    client_receive_queue.put(("error", "not-connected"))
                else:
                    try:
                        connection_sock.send_value(msg)
                    except:
                        client_receive_queue.put(("error", sysinfo_to_value(sys.exc_info())))
                        connection_sock.close()
            case ("send-special", msg):
                if not connection_open():
                    client_receive_queue.put(("error", "not-connected"))
                else:
                    try:
                        connection_sock.send_raw(msg)
                    except:
                        client_receive_queue.put(("error", sysinfo_to_value(sys.exc_info())))
                        connection_sock.close()
    client_receive_queue.put(("closed",))
    # todo: catch any exceptions that leak out
    # in these cases, it should make a best effort to report these somewhere
    # and to clean up any resources

def run_client():
    
    client_receive_queue = multiprocessing.Queue()
    client_send_queue = multiprocessing.Queue()

    ctx = multiprocessing.get_context(multiprocessing_spawn)
    p = ctx.Process(target=client_process_fn, args=[client_receive_queue, client_send_queue])
    p.daemon=True
    p.start()

    return (p, client_receive_queue, client_send_queue)

@contextlib.contextmanager
def client_manager():
    cl = run_client()
    try:
        yield cl
    finally:
        try:
            os.kill(cl[0].pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        cl[0].join()

@contextlib.contextmanager
def connected_client_server(trp):
    with server_manager() as srv, \
         client_manager() as cl:

        addr = start_server_listening(srv[1], srv[2])
        cl[2].put(("connect", addr))

        trp.assert_equal("client connected status", (("connected",)), cl[1].get())
        trp.assert_equal("server registers connect", ("client-connected",), srv[1].get())

        yield (srv,cl,addr)

##############################################################################

# some testing support utils

def is_process_running(pid):
    try:
        os.kill(pid,0)
        # ...
        try:
            f = open(f"/proc/{pid}/status", 'r')
            for line in f:
                if line.startswith("State:"):
                    if line.endswith("(zombie)\n"):
                        return False
        except FileNotFoundError:
            return False
        return True
    except ProcessLookupError:
        return False

def sysinfo_to_value(e):
    return ("".join(traceback.format_exception(*e, 0)),
            f"{type(e[0])}: {str(e[0])}",
            traceback.extract_tb(e[2]))

# ...
def sort_list(l):
    l1 = l.copy()
    l1.sort()
    return l1

# todo: refactor all this better in to the module

def summarize_sockets(s):
    ret = []
    for i in s:
        ret.append(i['type'])
    return ret

def get_sockets(pid):
    x = summarize_sockets(get_proc_socket_info.get_socket_info(pid))
    # hack to remove the connection for the test framework
    if 'connection' in x:
        x.remove('connection')
    return x

def assert_sockets(trp, p, pid, ts):
    sv = get_sockets(pid)
    if sort_list(sv) != sort_list(ts):
        trp.fail(f"{p} sockets expected {ts} got {sv}")
    else:
        trp.tpass(f"{p} sockets check {ts}")
    
def pred_listening_server_sockets(s):
    if s != ['listen']:
        return f"one server socket is listen {s}"
    
    
def check_sockets_predicate_retry(trp, msg, pred, pid):
    # check if pred(sockets) is true
    # if not, retry a few times after a short sleep before giving up
    # possibly most useful after killing a process to avoid races where you
    # see the socket still open before the kernel has completed the
    # kill and resource cleanup
    p = None
    for i in range(5):
        #s = get_proc_socket_info.get_socket_info(pid)
        s = get_sockets(pid)
        p = pred_listening_server_sockets(s)
        if p is None:
            trp.tpass(msg)
            return True
        time.sleep(short_wait)
    trp.fail(p)

def error_contains(err, pat):
    match err:
        case ("error", y):
            return pat in str(y)
        case _:
            return False

def check_bad_message_send(trp, q, error_text):
    trp.assert_pred("gets error",
                    lambda x: error_contains(x, error_text),
                    q.get())

    trp.assert_equal("disconnected after error",
                     ("disconnected",),
                     q.get())

def is_process_exited_race(pid):
    for i in range(5):
        if not is_process_running(pid):
            return True
        else:
            time.sleep(short_wait)
    return False
    
        
##############################################################################

# test some simple sockets stuff

def test_trivial_sockets(trp):

    def my_server_callback(s,_):
        s1 = socket_wrapper.ValueSocket(s)
        v = s1.receive_value()
        s1.send_value(("got", v))
        v = s1.receive_value()
    
    # create a server
    srv = socket_wrapper.SocketServer(my_server_callback, daemon=True)

    if True:
        # connect with a client
        c = socket_wrapper.ValueSocket(socket_wrapper.SafeSocket())
        c.connect(srv.addr)

        # exchange messages using object socket
        c.send_value(("hello", True))
        # check the return
        r = c.receive_value()
        trp.assert_equal("server client exchange", ("got", ("hello", True)), r)

        #print(f"client got {r}")

        # close the client connection
        c.close()
    # close the server
    srv.close()
    # check no exceptions


# TODO: this needs a bit more work to turn it into a reliable test
def test_socket_accept_exit(trp):

    sock = None

    def accept_it():
        nonlocal sock
        try:
            sock = socket.socket()
            sock.bind((socket.gethostname(), 0))
            sock.listen()
            x = sock.accept()
            raise Exception("didn't work")
        except OSError as e:
            if e.errno != 22:
                raise
        except:
            traceback.print_exc()

    thd = threading.Thread(target=accept_it)
    thd.start()
    time.sleep(short_wait)
    sock.shutdown(socket.SHUT_RDWR)
    sock.close()
    trp.tpass("close socket")



######################################

# test the server and client setup, then do some anomaly testing
# on the sockets and processes behaviour

def test_server_trivial_connect(trp):
    """
    start the server process
    check can connect to it using a raw socket connection
    """
    # start the server
    (server_p, server_receive_queue, server_send_queue) = run_server()
    trp.assert_true("check server pid running", is_process_running(server_p.pid))
    trp.assert_equal("server has no sockets", [], get_sockets(server_p.pid))

    # ask it to listen
    # check the status
    # check the socket connections
    addr = start_server_listening(server_receive_queue, server_send_queue)

    assert_sockets(trp, "server", server_p.pid, ['listen'])
    

    # connect to the port
    # check the status message
    # check the socket connections

    with socket.socket(family=socket_type) as sock:
        sock.connect(addr)
        trp.assert_equal("check connected status", ("client-connected",), server_receive_queue.get())
        assert_sockets(trp, "server", server_p.pid, ['listen', 'connection'])

    # disconnect
    # check the status message
    trp.assert_equal("check disconnected status", ("disconnected",), server_receive_queue.get())

    assert_sockets(trp, "server", server_p.pid, ['listen'])

    # ask the server to stop listening
    # check the status
    # check the socket connections

    server_send_queue.put(("unlisten",))
    trp.assert_equal("unlistening status", ("unlistening",), server_receive_queue.get())
    trp.assert_equal("server has no sockets", [], get_sockets(server_p.pid))

    server_send_queue.put(("close",))
    # close the server, check the status return
    trp.assert_equal("server close status", (("closed",)), server_receive_queue.get())
    # something weird is happening here, todo: remove the kill
    # and get to the bottom of it
    os.kill(server_p.pid, signal.SIGKILL)
    server_p.join()

    # check the process is not running
    trp.assert_true("check server pid not running", not is_process_running(server_p.pid))



def test_client_trivial_connect(trp):
    """
    run the server, run the client
    connect from the client to the server
    send a message from the client
    send a message from the server
    disconnect and close everything down
    
    """
    (server_p, server_receive_queue, server_send_queue) = run_server()
    addr = start_server_listening(server_receive_queue, server_send_queue)

    (client_p, client_receive_queue, client_send_queue) = run_client()
    trp.assert_true("check client pid running", is_process_running(client_p.pid))
    trp.assert_equal("client has no sockets", [], get_sockets(client_p.pid))


    # connect the client
    # check the status
    # check the sockets
    client_send_queue.put(("connect", addr))
    trp.assert_equal("client connected status", (("connected",)), client_receive_queue.get())

    trp.assert_equal("server registers connect", ("client-connected",), server_receive_queue.get())

    assert_sockets(trp, "server", server_p.pid, ['listen', 'connection'])
    assert_sockets(trp, "client", client_p.pid, ['connection'])


    # send a message
    # check it comes through on the server
    client_send_queue.put(("send", "hello"))
    trp.assert_equal("server gets message from client", "hello", server_receive_queue.get())

    # send a message from the server to the client
    # check it comes through on the client
    server_send_queue.put(("send", "hello2"))
    trp.assert_equal("client gets message from server", "hello2", client_receive_queue.get())

    # disconnect the client
    # check the client and server statuses
    # check the sockets
    client_send_queue.put(("disconnect",))
    trp.assert_equal("client disconnected status", (("disconnected",)), client_receive_queue.get())
    trp.assert_equal("client has no sockets", [], get_sockets(client_p.pid))

    trp.assert_equal("server registers disconnect", ("disconnected",), server_receive_queue.get())

    assert_sockets(trp, "server", server_p.pid, ['listen'])
    
    # close the client
    client_send_queue.put(("close",))
    trp.assert_equal("client close status", (("closed",)), client_receive_queue.get())
    client_p.join()
    trp.assert_true("check client pid not running", not is_process_running(client_p.pid))
    

    # stop the server, drain the statuses
    server_send_queue.put(("close",))
    trp.assert_equal("server close status", (("closed",)), server_receive_queue.get())
    server_p.join()


def test_send_two(trp):
    """
    check connecting and sending two messages each way on the connection
    """
    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), _):

        client_send_queue.put(("send", "hello1"))
        client_send_queue.put(("send", "hello2"))
        server_send_queue.put(("send", "hello3"))
        server_send_queue.put(("send", "hello4"))

        # how to make this work without sleep?
        # I think the sensible way is to read the receive queues before
        # disconnecting

        time.sleep(short_wait)
        client_send_queue.put(("disconnect",))
        time.sleep(short_wait)
        client_send_queue.put(("close",))
        server_send_queue.put(("close",))

        trp.assert_equal("client two 1", ("hello3"), client_receive_queue.get())
        trp.assert_equal("client two 2", ("hello4"), client_receive_queue.get())
        trp.assert_equal("client two 3", ("disconnected",), client_receive_queue.get())
        trp.assert_equal("client two 4", ("closed",), client_receive_queue.get())

        trp.assert_equal("server two 2", ("hello1"), server_receive_queue.get())
        trp.assert_equal("server two 3", ("hello2"), server_receive_queue.get())
        trp.assert_equal("server two 4", ("disconnected",), server_receive_queue.get())
        trp.assert_equal("server two 5", ("closed",), server_receive_queue.get())

def test_connect_send_disconnect_repeat(trp):
    """
    check connection, then send a message,
    then disconnect, the connect again, and send another message
    """
    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), \
          addr):

        client_send_queue.put(("send", "hello1"))
        server_send_queue.put(("send", "hello2"))

        trp.assert_equal("server sdr", ("hello1"), server_receive_queue.get())
        trp.assert_equal("client sdr", ("hello2"), client_receive_queue.get())

        client_send_queue.put(("disconnect",))

        trp.assert_equal("client two 3", ("disconnected",), client_receive_queue.get())
        trp.assert_equal("server two 4", ("disconnected",), server_receive_queue.get())

        client_send_queue.put(("connect", addr))
        trp.assert_equal("client connected status", (("connected",)), client_receive_queue.get())
        trp.assert_equal("server registers connect", ("client-connected",), server_receive_queue.get())

        client_send_queue.put(("send", "hello3"))
        server_send_queue.put(("send", "hello4"))
        
        trp.assert_equal("server sdr", ("hello3"), server_receive_queue.get())
        trp.assert_equal("client sdr", ("hello4"), client_receive_queue.get())
    
        
def test_server_close(trp):
    """
    check the sockets and status messages when the server is asked to close
    """
    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), _):

        server_send_queue.put(("close",))
        server_p.join()
        trp.assert_equal("client disconnected status", (("disconnected",)), client_receive_queue.get())
        trp.assert_equal("client has no sockets", [], get_sockets(client_p.pid))


def test_client_close(trp):
    """
    check the sockets and status messages when the client is asked to close
    """
    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), _):

        client_send_queue.put(("close",))
        client_p.join()
        trp.assert_equal("server registers client closed disconnect", ("disconnected",), server_receive_queue.get())
        assert_sockets(trp, "client", client_p.pid, [])
        assert_sockets(trp, "server", server_p.pid, ['listen'])
    

def test_server_send_after_disconnect(trp):
    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), _):

        client_send_queue.put(("close",))
        client_p.join()
        server_send_queue.put(("send", "hello"))

        trp.assert_equal("server registers client closed disconnect", ("disconnected",), server_receive_queue.get())
        trp.assert_equal("server gives error when send after client disconnects", ("error","not-connected",), server_receive_queue.get())

        assert_sockets(trp, "server", server_p.pid, ['listen'])

def test_client_send_after_disconnect(trp):
    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), _):

        server_send_queue.put(("close",))
        server_p.join()
        client_send_queue.put(("send", "hello"))

        trp.assert_equal("client registers server disconnect", ('disconnected',), client_receive_queue.get())
        trp.assert_equal("client gives error sending after server disconnect", ('error', 'not-connected'), client_receive_queue.get())

        trp.assert_equal("client has no sockets", [], get_sockets(client_p.pid))


def test_send_malformed_netstring_from_client(trp):

    with server_manager() as (server_p, server_receive_queue, server_send_queue), \
         client_manager() as (client_p, client_receive_queue, client_send_queue):
        addr = start_server_listening(server_receive_queue, server_send_queue)

        def test_bad_netstring(x):
            client_send_queue.put(("connect", addr))
            trp.assert_equal("client connected status", (("connected",)), client_receive_queue.get())
            trp.assert_equal("server registers connect", ("client-connected",), server_receive_queue.get())

            client_send_queue.put(("send-special", x))

            check_bad_message_send(trp, client_receive_queue, "read_netstring")
            check_bad_message_send(trp, server_receive_queue, "read_netstring")

            assert_sockets(trp, "client", client_p.pid, [])
            assert_sockets(trp, "server", server_p.pid, ['listen'])

        # doesn't start with digits
        test_bad_netstring(bytes("hello", "ascii"))
        # digits not followed by :
        test_bad_netstring(bytes("5", "ascii") + bytes("hello", "ascii") + bytes(",", "ascii"))
        # data not followed by ,
        test_bad_netstring(bytes("5:", "ascii") + bytes("hello", "ascii") + bytes(";", "ascii"))

def test_send_malformed_netstring_from_server(trp):

    with server_manager() as (server_p, server_receive_queue, server_send_queue), \
         client_manager() as (client_p, client_receive_queue, client_send_queue):
        addr = start_server_listening(server_receive_queue, server_send_queue)

        def test_bad_netstring(x):
            client_send_queue.put(("connect", addr))
            trp.assert_equal("client connected status", (("connected",)), client_receive_queue.get())
            trp.assert_equal("server registers connect", ("client-connected",), server_receive_queue.get())

            server_send_queue.put(("send-special", x))

            check_bad_message_send(trp, client_receive_queue, "read_netstring")
            check_bad_message_send(trp, server_receive_queue, "read_netstring")

            assert_sockets(trp, "client", client_p.pid, [])
            assert_sockets(trp, "server", server_p.pid, ['listen'])

        test_bad_netstring(bytes("hello", "ascii"))
        test_bad_netstring(bytes("5", "ascii") + bytes("hello", "ascii") + bytes(",", "ascii"))
        test_bad_netstring(bytes("5:", "ascii") + bytes("hello", "ascii") + bytes(";", "ascii"))

def test_client_sends_non_dill_message(trp):

    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), _):

        msg = "hello"
        x = bytes(str(len(msg)), 'ascii') + bytes(':', 'ascii') + \
            bytes(msg, 'ascii') + bytes(',', 'ascii')
        client_send_queue.put(("send-special", x))

        check_bad_message_send(trp, client_receive_queue, "UnpicklingError")
        check_bad_message_send(trp, server_receive_queue, "UnpicklingError")
        
        assert_sockets(trp, "client", client_p.pid, [])
        assert_sockets(trp, "server", server_p.pid, ['listen'])

def test_server_sends_non_dill_message(trp):
    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), _):

        msg = "hello"
        x = bytes(str(len(msg)), 'ascii') + bytes(':', 'ascii') + \
            bytes(msg, 'ascii') + bytes(',', 'ascii')
        server_send_queue.put(("send-special", x))

        check_bad_message_send(trp, client_receive_queue, "UnpicklingError")
        check_bad_message_send(trp, server_receive_queue, "UnpicklingError")
        
        assert_sockets(trp, "client", client_p.pid, [])
        assert_sockets(trp, "server", server_p.pid, ['listen'])

    
def test_server_sigkill_disconnect(trp):
    """
    sigkill the server process when connected
    check the client gets the status update
    """
    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), _):

        os.kill(client_p.pid, signal.SIGKILL)
        # it needs a moment to process the signal?
        #time.sleep(short_wait)

        trp.assert_true("client process not running", is_process_exited_race(client_p.pid))
        trp.assert_equal("server disconnnected status",
                         (("disconnected",)), server_receive_queue.get())

        assert_sockets(trp, "server", server_p.pid, ['listen'])
    
def test_client_sigkill_disconnect(trp):
    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), _):

        os.kill(server_p.pid, signal.SIGKILL)

        trp.assert_true("server process not running", is_process_exited_race(server_p.pid))
        trp.assert_equal("client disconnnected status",
                         (("disconnected",)), client_receive_queue.get())
        trp.assert_equal("client has no sockets", [], get_sockets(client_p.pid))
    

def test_split_message(trp):
    """
    try to send half the dill encoded message in one network write
    and the other half in a second network write to sanity check
    the receive code handles this fine
    """
    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), _):
        # sanity check
        # send a message in two halfs
    
        msg_p = dill.dumps("hello")
        x = bytes(str(len(msg_p)), 'ascii') \
            + bytes(':', 'ascii') + \
            msg_p + bytes(',', 'ascii')
        mid = int(len(x) / 2)
        #print(f"whole: {x}")
        #print(f"send {x[0:mid]}")
        client_send_queue.put(("send-special", x[0:mid]))
        # this will like, flush it and stuff, right?
        time.sleep(short_wait)
        #print(f"send {x[mid:]}")
        client_send_queue.put(("send-special", x[mid:]))

        trp.assert_equal("check message", "hello", server_receive_queue.get())

def test_client_sends_half_message_kill_client(trp):
    """
    anomaly test the server when the client sends half a message then disappears
    """
    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), _):

        msg_p = dill.dumps("hello")
        x = bytes(str(len(msg_p)), 'ascii') + bytes(':', 'ascii') + \
            msg_p + bytes(',', 'ascii')
        mid = int(len(x) / 2)
        client_send_queue.put(("send-special", x[0:mid]))
        time.sleep(short_wait)

        os.kill(client_p.pid, signal.SIGKILL)

        trp.assert_true("client process not running", is_process_exited_race(client_p.pid))

        check_sockets_predicate_retry(trp, "server listening", pred_listening_server_sockets, server_p.pid)

        check_bad_message_send(trp, server_receive_queue, "read_netstring")

def test_client_sends_half_message_kill_server(trp):
    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), _):

        msg_p = dill.dumps("hello")
        x = bytes(str(len(msg_p)), 'ascii') + bytes(':', 'ascii') + \
            msg_p + bytes(',', 'ascii')
        mid = int(len(x) / 2)
        client_send_queue.put(("send-special", x[0:mid]))
        time.sleep(short_wait)

        os.kill(server_p.pid, signal.SIGKILL)

        trp.assert_true("server process not running", is_process_exited_race(server_p.pid))
        
        time.sleep(short_wait)
        client_send_queue.put(("send-special", x[mid:]))

        trp.assert_equal("client has no sockets", [], get_sockets(client_p.pid))

        trp.assert_equal("client gets disconnected status",
                        ("disconnected",),
                        client_receive_queue.get())
        trp.assert_equal("client gets error sending",
                        ("error", "not-connected",),
                        client_receive_queue.get())

def test_server_sends_half_message_kill_server(trp):
    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), _):

        msg_p = dill.dumps("hello")
        x = bytes(str(len(msg_p)), 'ascii') + bytes(':', 'ascii') + \
            msg_p + bytes(',', 'ascii')
        mid = int(len(x) / 2)
        server_send_queue.put(("send-special", x[0:mid]))
        time.sleep(short_wait)

        os.kill(server_p.pid, signal.SIGKILL)

        trp.assert_true("server process not running", is_process_exited_race(server_p.pid))
        time.sleep(short_wait)

        trp.assert_equal("client has no sockets", [], get_sockets(client_p.pid))

        check_bad_message_send(trp, client_receive_queue, "read_netstring")

def test_server_sends_half_message_kill_client(trp):
    with connected_client_server(trp) as \
         ((server_p, server_receive_queue, server_send_queue), \
          (client_p, client_receive_queue, client_send_queue), _):

        msg_p = dill.dumps("hello")
        x = bytes(str(len(msg_p)), 'ascii') + bytes(':', 'ascii') + \
            msg_p + bytes(',', 'ascii')
        mid = int(len(x) / 2)
        server_send_queue.put(("send-special", x[0:mid]))
        time.sleep(short_wait)

        os.kill(client_p.pid, signal.SIGKILL)

        time.sleep(short_wait)
        server_send_queue.put(("send-special", x[mid:0]))

        trp.assert_true("client process not running", is_process_exited_race(client_p.pid))

        assert_sockets(trp, "server", server_p.pid, ['listen'])

        trp.assert_equal("server disconnnected status",
                         (("disconnected",)), server_receive_queue.get())
        trp.assert_equal("server disconnnected status",
                         (("error","not-connected")), server_receive_queue.get())


def test_connect_to_missing_server(trp):
    """
    check the behaviour when the client tries to connect to a server which
    is no longer there
    """
    with server_manager() as (server_p, server_receive_queue, server_send_queue), \
         client_manager() as (client_p, client_receive_queue, client_send_queue):
        addr = start_server_listening(server_receive_queue, server_send_queue)

        server_send_queue.put(("unlisten",))

        client_send_queue.put(("connect", addr))
        
        match client_receive_queue.get():
            case ("error", x) if ("ConnectionRefusedError" in str(x)) or ("ConnectionResetError" in str(x)):
                trp.tpass("client connected status")
            case x:
                trp.fail(f"client connected status expected ConnectionRefusedError or ConnectionResetError, got {x}")

######################################

"""

demo showing accepting a connection, then passing the open socket to
another process
this is e.g. so you can have N processes ready to handle network connections,
but only need to listen on one port

"""

def test_socket_passing(trp):

    get_addr_queue = multiprocessing.Queue()
    
    def server_server():
        yeshup.yeshup_me()
        #print(f"server server, pid: {os.getpid()}")

        def server(subserver_c):
            yeshup.yeshup_me()
            #print(f"server, pid: {os.getpid()}")
            # get the client socket from the socket connection to the
            # server server
            client_sock = socket_wrapper.ValueSocket(subserver_c.receive_sock())
            # interact with the client
            v = client_sock.receive_value()
            if v == ("hello",):
                client_sock.send_value(("hello", os.getpid()))
            else:
                client_sock.send_value(("error", v))

        # communication between the server server and server
        (subserver_s, subserver_c) = socket_wrapper.socketpair()
        server_p = multiprocessing.Process(target=server, args=[subserver_c])
        server_p.start()
        
        def accept_handler(client_sock, _):
            # print("accept in server server")
            # get a connection, pass it to the server
            subserver_s.send_sock(client_sock)
        srv = socket_wrapper.SocketServer(accept_handler, daemon=True)
        get_addr_queue.put(srv.addr)
            
    server_server_p = multiprocessing.Process(target=server_server)
    server_server_p.start()

    def client():
        #print(f"client, pid: {os.getpid()}")
        addr = get_addr_queue.get()
        c = socket_wrapper.ValueSocket(socket_wrapper.SafeSocket())
        c.connect(addr)
        c.send_value(("hello",))
        x = c.receive_value()
        match x:
           case ("hello", _):
               trp.tpass("handshake via passed socket")
           case _:
               trp.fail("handshake via passed socket, expected ('hello',_), got {x}")
        c.close()

    client()

                
##############################################################################


all_tests = [ \
              test_trivial_sockets,
              test_socket_accept_exit,
              test_server_trivial_connect,
              test_client_trivial_connect,
              test_send_two,
              test_connect_send_disconnect_repeat,
              test_server_close,
              test_client_close,
              test_server_send_after_disconnect,
              test_client_send_after_disconnect,
              test_send_malformed_netstring_from_client,
              test_send_malformed_netstring_from_server,
              test_client_sends_non_dill_message,
              test_server_sends_non_dill_message,
              test_server_sigkill_disconnect,
              test_client_sigkill_disconnect,
              test_split_message,
              test_client_sends_half_message_kill_client,
              test_client_sends_half_message_kill_server,
              test_server_sends_half_message_kill_server,
              test_server_sends_half_message_kill_client,
              test_connect_to_missing_server,
              test_socket_passing,
             ]
