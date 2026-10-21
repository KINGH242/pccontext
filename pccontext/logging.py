import logging

__all__ = ["logger"]

# create logger
logger = logging.getLogger("PyCardano Chain Context")

# create console handler and set level to debug
ch = logging.StreamHandler()

# create formatter
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# add formatter to ch
ch.setFormatter(formatter)

# add ch to logger
logger.addHandler(ch)
