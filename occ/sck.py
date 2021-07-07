#!/usr/bin/env python3

"""x

wrapper for Python sockets (which are a thin wrapper around Posix
sockets) with the following additions:

* reliable closing is easier
* anomaly handling is easier
* high level interface where you can pass python objects to sockets,
  and get them back, using the dill library
* simple callback wrapper for socket servers
* simple to use wrapper for sending sockets on sockets (sendmsg)

"""


import socket
import dill
import sys
import threading
import ctypes
import tempfile

from tblib import pickling_support

dill.settings['recurse'] = True

AF_UNIX = socket.AF_UNIX
AF_INET = socket.AF_INET

##############################################################################

@pickling_support.install
class NetstringException(Exception):
    def __init__(self, msg):
        self.msg = msg
    def __str__(self):
        return f"{self.msg}"

def write_netstring(sock,s):
    if type(s) is not bytes:
        raise NetstringException(f"write_netstring: expected bytes got {type(s)}")
    l = str(len(s))
    msg = bytes(l, 'ascii') + bytes(':', 'ascii') + s + bytes(',', 'ascii')
    sock.sendall(msg)

def read_netstring(sock):
    data_length = []
    try:
        c = sock.recv(1)
        # it should probably catch a few more errors here -
        # if the connection is closed at a message boundary,
        # the behaviour if this function should be to return 0
    except ConnectionResetError:
        return 0
    # tcp socket has been closed
    if len(c) == 0:
        return 0
    if c < bytes('0', 'ascii') or c > bytes('9', 'ascii'):
        raise NetstringException(f"read_netstring expected digit got {c}")
    data_length.append(str(c, 'ascii'))
    while True:
        c = sock.recv(1)
        if len(c) == 0:
            raise NetstringException(f"expected digit or ':', connection was closed")
        if c >= bytes('0','ascii') and c <= bytes('9', 'ascii'):
            data_length.append(str(c, 'ascii'))
        elif c == bytes(':', 'ascii'):
            break
        else:
            raise NetstringException(f"read_netstring expected digit or ':', got {c}")
    l = int(''.join(data_length))
    bs = sock.recv(l, socket.MSG_WAITALL)
    if bs == 0:
        raise NetstringException(f"expected payload of {l} bytes, connection was closed")
    if len(bs) != l:
        raise NetstringException(f"expected payload of {l} bytes, but only got {len(bs)}")
    c = sock.recv(1)
    if len(c) == 0:
        raise NetstringException(f"expected ',', connection was closed")
    if c != bytes(',', 'ascii'):
        raise NetstringException(f"read_netstring expected ',', got {c}")
    return bs

##############################################################################

class Socket:
    def __init__(self, sock=None, is_open=False,socket_type=None):
        if sock is None:
            if socket_type is None:
                sock = socket.socket()
            else:
                sock = socket.socket(family=socket_type)
        self._socket = sock
        self._is_open = is_open

    def send_raw(self, bs):
        self._socket.sendall(bs)

    def is_open(self):
        return self._is_open

    def close(self):
        if self._is_open:
            err = None
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except:
                err = sys.exc_info()
            try:
                self._socket.close()
            except:
                if err is None:
                    err = sys.exc_info()
                else:
                    # trace it or something? maybe it will never be useful?
                    pass
            self._is_open = False
            # returns the error because I think it's common to not be
            # interested if there's an error
            return err


    def connect(self,addr):
        try:
            self._is_open = True
            self._socket.connect(addr)
        except:
            self.close()
            raise

    # no idea if a file handle in linux is always the size of a c int
    c_int_size = ctypes.sizeof(ctypes.c_int)

    # send a socket connection over a socket using sendmsg, receivemsg
    def receive_sock(self):
        msg, ancdata, flags, addr = self._socket.recvmsg(1, socket.CMSG_LEN(Socket.c_int_size))
        if len(ancdata) != 1:
            raise Exception(f"expected to get ancdata of length 1 in recvmsg, got {ancdata}")
        (cmsg_level, cmsg_type, cmsg_data) = ancdata[0]
        if cmsg_level != socket.SOL_SOCKET:
            raise Exception(f"recvmsg, expected to get {socket.SOL_SOCKET}, got {cmsg_level}")
        if cmsg_type != socket.SCM_RIGHTS:
            raise Exception(f"recvmsg, expected to get {socket.SCM_RIGHTS}, got {cmsg_type}")
        rs = socket.socket(fileno=int.from_bytes(cmsg_data, byteorder='little'))
        # todo: should it close the self socket if there's an exception?
        return Socket(rs, True)


    def send_sock(self,sock_to_send):
        self._socket.sendmsg([bytes("S", "ascii")],
                             [(socket.SOL_SOCKET,
                               socket.SCM_RIGHTS,
                               sock_to_send._socket.fileno() \
                                 .to_bytes(Socket.c_int_size, byteorder='little')
                               )])
        # todo: what are you supposed to do here to release the socket
        # resources in the local process, while leaving the socket
        # connected fine in the recipient process
        # sock_to_send.close()
        # maybe it's as simple as closing the socket without doing a shutdown

    # sending and receiving python values using dill
    def receive_value(self):
        try:
            ns = read_netstring(self._socket)
            if ns == 0:
                self.close()
                return None
            v = dill.loads(ns)
            return v
        except NetstringException:
            raise
        except (dill.PicklingError, dill.UnpicklingError):
            raise
        except:
            self.close()
            raise

    def send_value(self, val):
        try:
            pickled = dill.dumps(val)
            write_netstring(self._socket, pickled)
        except NetstringException:
            raise
        except (dill.PicklingError, dill.UnpicklingError):
            raise
        except:
            self.close()
            raise

def connected_socket(addr, socket_type=None):
    sock = Socket(socket_type=socket_type)
    sock.connect(addr)
    return sock

def connected_unix_socket(addr):
    sock = Socket(socket_type=AF_UNIX)
    sock.connect(addr)
    return sock


##############################################################################
    

"""
socket server abstracts the bind, listen, accept process

you supply a callback, and it calls the callback in a new thread with
the socket when a connection is made

"""
class SocketServer:
    def __init__(self, callback, socket_type, addr, daemon):
        self.listen_sock = Socket(socket.socket(socket_type), True)
        self.addr = addr
        self.accept_thread = None
        try:
            if self.addr is None:
                if socket_type == socket.AF_INET:
                    self.listen_sock._socket.bind((socket.gethostname(), 0))
                    self.addr = self.listen_sock._socket.getsockname()
                elif socket_type == socket.AF_UNIX:
                    tmp = tempfile.NamedTemporaryFile()
                    tmp.close()
                    self.listen_sock._socket.bind(tmp.name)
                    self.addr = tmp.name
            else:
                self.listen_sock._socketbind(self.addr)
            self.listen_sock._socket.listen()
        except:
            self.listen_sock.close()
            raise

        def acceptor():
            nonlocal self, callback
            try:
                while True:
                    (s,a) = self.listen_sock._socket.accept()
                    s1 = Socket(s, True)
                    tr = threading.Thread(target=callback,
                                          args=[s1, a],
                                          daemon=daemon)
                    tr.start()
                    # todo: who joins this thread and when?
            except:
                # todo: figure out what to do with exceptions
                self.listen_sock.close()
        self.accept_thread = threading.Thread(target=acceptor,
                                         args=[],
                                         daemon=daemon)
        self.accept_thread.start()

    def is_running(self):
        return self.listen_sock.is_open()

    def close(self):
        if self.listen_sock is not None:
            self.listen_sock.close()
        if self.accept_thread is not None:
            self.accept_thread.join()

def make_socket_server(callback, addr=None, daemon=False):
    return SocketServer(callback, socket_type=AF_INET, addr=addr, daemon=daemon)

def make_unix_socket_server(callback, addr=None, daemon=False):
    return SocketServer(callback, socket_type=AF_UNIX, addr=addr, daemon=daemon)

            
def socketpair():
    (a,b) = socket.socketpair()
    return (Socket(a, True), Socket(b, True))
