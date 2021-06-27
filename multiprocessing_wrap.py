
"""x

dill is able to pickle all sorts of things

the multiprocessing module uses the default pickling which fails on a
lot of the functions in this code

but//
if you create a socketpair, multiprocessing can pass a socket as an argument
but you can't pass a socket by pickling it with dill (or any other
pickling approach, practically)

so: create a wrapper to start a process, which passes the sockets as
multiprocessing args, and manually pickles the rest using dill

it doesn't automatically detect which args are sockets
this could be added if needed, but the code only has two patterns:
no sockets are passed
the first or first two arguments are sockets

"""

import multiprocessing
import dill
import sck

def undill_wrapper0(tgtw,argsw):
    tgt = dill.loads(tgtw)
    args = dill.loads(argsw)
    tgt(*args)

def undill_wrapper1(tgtw,sw,argsw):
    tgt = dill.loads(tgtw)
    args = dill.loads(argsw)
    tgt(sw,*args)

def undill_wrapper2(tgtw,sw,sw1,argsw):
    tgt = dill.loads(tgtw)
    args = dill.loads(argsw)
    tgt(sw,sw1,*args)

    
def start_process(target, args, daemon=False,ctx=None):
    tgtw = dill.dumps(target)
    if ctx is None:
        pf = multiprocessing.Process
    else:
        pf = ctx.Process
    if len(args) > 1 and type(args[0]) is sck.Socket and type(args[1]) is sck.Socket:
        sw = args[0]
        sw1 = args[1]
        argsw = dill.dumps(args[2:])
        p = pf(target=undill_wrapper2, args=[tgtw,sw,sw1,argsw], daemon=daemon)
    elif len(args) > 0 and type(args[0]) is sck.Socket:
        sw = args[0]
        argsw = dill.dumps(args[1:])
        p = pf(target=undill_wrapper1, args=[tgtw,sw,argsw], daemon=daemon)
    else:
        argsw = dill.dumps(args)
        wrap = undill_wrapper0
        p = pf(target=undill_wrapper0, args=[tgtw,argsw], daemon=daemon)
    p.start()
    return p
