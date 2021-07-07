

import logging

# function that's called in the occasional system to initalize the logging
# it's called for the central process, every spawned process
# and for the open top level process
def initialize_logging():
    logger = logging.getLogger()
    #logger.setLevel(logging.INFO)
    while logger.hasHandlers():
        logger.removeHandler(logger.handlers[0])
    logger.addHandler(logging.StreamHandler())
