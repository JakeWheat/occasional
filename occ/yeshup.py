"""x

yeshup: make a child process exit when the parent process exits

todo: add a command line wrapper version

"""

import prctl
import signal

"""
call this in the child process
one option is to fork, call this, then exec something, it's inherited
when exec'ing (but could be reset by the exec'd code)

I think there's a race
it should check it's original parent still exists
just after setting the deathsig, otherwise kill itself

"""
def yeshup_me():
    prctl.set_pdeathsig(signal.SIGKILL)
