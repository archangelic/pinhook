import logging
import os

logger = logging.getLogger('bot')
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(module)s - %(message)s')
# Set console logger
streamhandler = logging.StreamHandler()
streamhandler.setFormatter(formatter)
logger.addHandler(streamhandler)


def get_bot_logger(nickname):
    # each bot gets its own child of the 'bot' logger so it can have its own
    # level and log file, console output still goes through the parent
    bot_logger = logger.getChild(nickname)
    # a new bot with the same nick replaces the old one's log file
    for handler in list(bot_logger.handlers):
        bot_logger.removeHandler(handler)
        handler.close()
    return bot_logger


def set_log_file(filename, target=logger):
    # make the logs folder the first time
    folder = os.path.dirname(filename)
    if folder:
        os.makedirs(folder, exist_ok=True)
    # Set file logger
    filehandler = logging.FileHandler(filename)
    filehandler.setFormatter(formatter)
    target.addHandler(filehandler)
