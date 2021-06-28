#!/usr/bin/env python3

import area_server
import occasional
from occasional import send,receive,slf

"""
can't use 

occasional.start()
def f():
   ...
spawn(f)
...
at the top level, because of how send functions remotely works
-> it will reexecute the top level code remotely and will run the top
   level code twice (not sure why it doesn't do it repeatedly)

so you have to use:

def f():
   ...

if __name__ == "__main__":
    # or f can be defined here
    occasional.start()
    spawn(f)
    ...

it's supposed to be a wrapper for quick scripts and beginners,
but it's littered with traps that will fail in weird ways ...

at least it mostly works in the repl:

$ python3
Python 3.10.0b3 (default, Jun 22 2021, 10:29:20) [GCC 10.2.1 20210110] on linux
Type "help", "copyright", "credits" or "license" for more information.
>>> import area_server
>>> import occasional
>>> from occasional import w,send,receive,slf,spawn
>>> occasional.start()
>>> h = area_server.start()
>>> area_server.area(h,("rectangle", 3,4))
12


$ python3
Python 3.10.0b3 (default, Jun 22 2021, 10:29:20) [GCC 10.2.1 20210110] on linux
Type "help", "copyright", "credits" or "license" for more information.
>>> import occasional
>>> from occasional import w,send,receive,slf,spawn
>>> def f(ib):
...         print("hello")
... 
>>> occasional.start()
>>> spawn(f)
927412
>>> hello
[the hello was output from the spawned function]

"""

if __name__ == "__main__":

    occasional.start()

    h = area_server.start()

    s1 = ("rectangle", 3,4)
    area1 = area_server.area(h,s1)
    assert(area1 == 12)
    print(f"{s1}: {area1}")


    s2 = ("circle", 5)
    area2 = area_server.area(h,s2)
    assert(abs(78.53975 - area2) < 0.001)
    print(f"{s2}: {area2}")

    s3 = "rhombicosidodecahedron"
    area3 = area_server.area(h,s3)
    assert(area3 == ("error", "rhombicosidodecahedron"))
    print(f"{s3}: {area3}")

    area_server.stop(h)

    occasional.stop()
