#!/usr/bin/env python3

import occasional
from occasional import spawn, send, receive, slf

def say_hello():
    while True:
        match receive():
            case (frm, nm):
                send(frm, f"hello {nm}")

def f():
    h = spawn(say_hello)

    send(h, (slf(), "foo"))
    x = receive()
    assert(x == "hello foo")
    print(x)

    send(h, (slf(), "bar"))
    x = receive()
    assert(x == "hello bar")
    print(x)

if __name__ == "__main__":
    occasional.run(f)
