

import logging
import occasional
import traceback

class OccasionalLogHandler(logging.Handler):
    def __init__(self):
        logging.Handler.__init__(self)
        self.ib = None
        # temporarily buffer messages
        self.buf = []

    def emit(self, record):
        try:
            if self.ib is None:
                self.buf.append(record)
            else:
                self.ib.send("_logging", record)
        except:
            print(f"logging failed {record}:")
            traceback.print_exc()
            print(f"logging stopped")
            # todo: start outputting log messages on stderr in this case
            self.ib = None

    def set_inbox(self, ib):
        self.ib = ib
        for record in self.buf:
            self.ib.send("_logging", record)
        self.buf.clear()
        

# function that's called in the occasional system to initalize the logging
# it's called for the central process, every spawned process
# and for the open top level process
def initialize_logging():
    logger = logging.getLogger()
    #logger.setLevel(logging.INFO)
    while logger.hasHandlers():
        logger.removeHandler(logger.handlers[0])
    #logger.addHandler(logging.StreamHandler())
    logger.addHandler(OccasionalLogHandler())

def set_logging_inbox(ib):
    logger = logging.getLogger()
    if type(logger.handlers[0]) is OccasionalLogHandler:
        logger.handlers[0].set_inbox(ib)

def stop_logging(ib):
    logger = logging.getLogger()
    if type(logger.handlers[0]) is OccasionalLogHandler:
        logger.handlers[0].set_inbox(None)
