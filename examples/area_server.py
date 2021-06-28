import sys

import occasional
from occasional import spawn, send, receive, slf

def start():
    return spawn(loop)

def stop(a):
    return rpc(a, "exit")

def area(pid, what):
    return rpc(pid, what)

def rpc(pid, req):
    send(pid, (slf(), req))
    def m(x):
        match x:
            case (pidr,resp) if pid == pidr:
                return resp
    return receive(match=m)

def loop():
    def m(x):
        match x:
            case (frm, ("rectangle", w, h)):
                send(frm, (slf(), w * h))
                return True
            case (frm, ("circle", r)):
                send(frm, (slf(), 3.14159 * r * r))
                return True
            case (frm,"exit"):
                send(frm, (slf(), "exiting"))
                sys.exit(0)
            case (frm, other):
                send(frm, (slf(), ("error", other)))
                return True
    while True:
        receive(match=m)

