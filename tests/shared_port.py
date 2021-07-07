
"""x

Demos of having 'server servers' which listen on a port, and can send
connections to one of many subserver processes. This is so you can
connect to a lot of different processes, without having to listen on a
lot of ports, and without any forwarding/copying.

A key way the code here differs from the full system implementation in
that connections are explicit, and each connection is still handled by
a separate thread in the servers.

TODO:
finish the tests

add some checking to see threads, processes and sockets cleaned up
properly

"""

import occ.yeshup as yeshup
import multiprocessing
import occ.sck as sck
import os
import time

from occ.utils import format_exception

import sys
import socket
import threading

import functools
bind = functools.partial


##############################################################################

# simple demo showing passing socket connections between processes

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
            client_sock = subserver_c.receive_sock()
            # interact with the client
            v = client_sock.receive_value()
            if v == ("hello",):
                client_sock.send_value(("hello", os.getpid()))
            else:
                client_sock.send_value(("error", v))

        # communication between the server server and server
        (subserver_s, subserver_c) = sck.socketpair()
        server_p = multiprocessing.Process(target=server, args=[subserver_c])
        server_p.start()
        
        def accept_handler(client_sock, _):
            # print("accept in server server")
            # get a connection, pass it to the server
            subserver_s.send_sock(client_sock)
        srv = sck.make_unix_socket_server(accept_handler, daemon=True)
        get_addr_queue.put(srv.addr)
            
    server_server_p = multiprocessing.Process(target=server_server)
    server_server_p.start()

    def client():
        #print(f"client, pid: {os.getpid()}")
        addr = get_addr_queue.get()
        c = sck.connected_unix_socket(addr)
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

"""x

main demo
----------

starts a server

you can then connect to this server

then you can ask the server to start a subserver, this starts new code
in a different process each subserver

you can open connections to these subservers via the single port for
the main server

it works by passing the server server side socket connection to the
appropriate subserver

this simulates non local processes being able to connect to a choice of many processes on a machine, using only one listening port, and without forwarding messages or using some clever virtual networking stuff, etc.

"""

def spawn(f):
    p = multiprocessing.Process(target=f, daemon=True)
    p.start()
    return p

"""

the wrapper for a subserver, it only supports exiting the subserver
completely,

and accepting a socket then starting a thread running the accept
handler with this socket

"""
def runsubserver(sock, handle_f):
    try:
        while True:
            x = sock.receive_value()
            match x:
               case None:
                   break
               case "exit":
                   break
               case "connectionx":
                   conn = sock.receive_sock()
                   accept_thread = threading.Thread(target=handle_f,
                                                    args=[conn],
                                                    daemon=True)
                   accept_thread.start()
                   # it should probably save and manage the threads and stuff
               case _:
                   print(f"runsubserver unrecognised message {x}")
    except:
        print("exception in runsubserver")
        print(format_exception(sys.exc_info()[1]))
           

def start_server():

    subservers = {}
    
    def accept_handler(sock,_):
        try:
            nonlocal subservers
            while True:
                m = sock.receive_value()
                # what does it get when the socket is closed from the other side?
                match m:
                   case None:
                       # client disconnected
                       # todo: bookkeeping update
                       break
                   case "exit":
                       # exit all the processes
                       # exit all the accept handlers by closing the socket
                       # and expecting all the threads to exit
                       break
                   case ("start-subserver", nm, f):
                       # how does f have shared state if it's an accept handler
                       # and each one runs in a new thread in a different process?
                       (conna, connb) = sck.socketpair()
                       p = spawn(bind(runsubserver, connb, f))
                       subservers[nm] = (p,conna)
                       sock.send_value("subserver-started")
                   case ("stop-subserver", nm):
                       print("stop server not implemented")
                       pass
                   case ("connect", nm):
                       x = subservers[nm]
                       if x is None:
                           print(f"subserver not found {nm}")
                       x[1].send_value("connectionx")
                       x[1].send_sock(sock)
                       break
                   case "list-subservers":
                       sock.send_value(list(subservers.keys()))
                   case _:
                       print(f"xx unsupported message {m}")
        except:
            print("exception in main server accept handler")
            print(format_exception(sys.exc_info()[1]))

    srv = sck.make_socket_server(accept_handler, daemon=True)
    return srv.addr

##############################################################################

# sanity tests:

# start the server
# connect to it, list the subservers, then disconnect

def test_connect_list(trp):
    addr = start_server()

    sock = sck.connected_socket(addr)

    sock.send_value("list-subservers")
    x = sock.receive_value()
    trp.assert_equal("empty list subserver", [], x)
    sock.send_value("exit")


# connect to it, start a subserver, list subservers,
# connect to subserver, exchange a message,
def test_connect_start_list(trp):
    addr = start_server()
    
    sock = sck.connected_socket(addr)

    def my_server(sock):
        try:
            while True:
                x = sock.receive_value()
                if x is None:
                    break
                sock.send_value(("hello", x))
        except:
            print("exception in my_server")
            print(format_exception(sys.exc_info()[1]))


    sock.send_value(("start-subserver", "srv", my_server))
    x = sock.receive_value()
    if x != "subserver-started":
        raise Exception(f"server didn't start: {x}")

    sock.send_value("list-subservers")
    x = sock.receive_value()
    trp.assert_equal("one subserver", ["srv"], x)
    

    sock.send_value(("connect", "srv"))

    sock.send_value("stuff")
    x = sock.receive_value()
    trp.assert_equal("message from subserver", ("hello", "stuff"), x)

    srv_sock = sck.connected_socket(addr)
    srv_sock.send_value("exit")



##############################################################################

"""

slighty bigger test

start a subserver
exchange messages with it
start another one and exchange messages with it
exchange messages with the first one
stop a subserver
then try to connect to it -> see it error
  and also check its pid - check it before it's exited too
get the pid of the server and all the running subservers
  check the pids are running
exit the server
  check all the pids are not running

for now:
start a server, exchange a message
start another server, exchange message with that
then exchange message with first server

"""

def test_shared_port_server(trp):

    addr = start_server()
    sock = sck.connected_socket(addr)

    def my_server1(sock):
        try:
            while True:
                x = sock.receive_value()
                if x is None:
                    break
                sock.send_value(("hello", x))
        except:
            print("exception in my_server")
            print(format_exception(sys.exc_info()[1]))

    def my_server2(sock):
        try:
            while True:
                x = sock.receive_value()
                if x is None:
                    break
                sock.send_value(("greetings", x))
        except:
            print("exception in my_server")
            print(format_exception(sys.exc_info()[1]))

    sock.send_value(("start-subserver", "srv1", my_server1))
    x = sock.receive_value()
    if x != "subserver-started":
        raise Exception(f"server didn't start: {x}")

    sock.send_value(("start-subserver", "srv2", my_server2))
    x = sock.receive_value()
    if x != "subserver-started":
        raise Exception(f"server didn't start: {x}")

    sock.send_value("list-subservers")
    x = sock.receive_value()
    trp.assert_equal("list subservers", ["srv1", "srv2"], x)

    sock1 = sck.connected_socket(addr)
    sock1.send_value(("connect", "srv1"))
    sock1.send_value("stuff")
    x = sock1.receive_value()
    trp.assert_equal("message from subserver", ("hello", "stuff"), x)

    sock2 = sck.connected_socket(addr)
    sock2.send_value(("connect", "srv2"))
    sock2.send_value("stuff1")
    x = sock2.receive_value()
    trp.assert_equal("message from subserver", ("greetings", "stuff1"), x)

    sock3 = sck.connected_socket(addr)
    sock3.send_value(("connect", "srv1"))
    sock3.send_value("stuff2")
    x = sock3.receive_value()
    trp.assert_equal("message from subserver", ("hello", "stuff2"), x)
    

    sock.send_value("exit")


##############################################################################

"""

keep starting clients
keep starting and stopping subservers
have the clients talking to the same subservers
how to test things work when they should:
  each client needs to know how a server will respond
how to reliably test when subservers might exit at any time
  1. prevent clients from trying to talk to an exited server
  2. let a client try to talk, if it gets a connection error,
     then log enough to check if this is expected or not after?

"""
def test_shared_port_server_heavy(trp):
    pass
