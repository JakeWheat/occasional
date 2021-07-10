
import sys
from tblib import pickling_support

import traceback

import logging
logger = logging.getLogger(__name__)

@pickling_support.install
class ContextException(Exception):
    def __init__(self, c):
        super().__init__(c)
        self.ctx = c

def reraise_with_context(ctx):
    e = sys.exc_info()[1]
    # TODO: what about type(e): e.msg for the first item
    raise ContextException((str(e), ctx)) from e

def format_exception(e):
    return "".join(traceback.format_exception(type(e), e, e.__traceback__))
