import logging

logger = logging.getLogger('bot')
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(module)s - %(message)s')
# Set console logger
streamhandler = logging.StreamHandler()
streamhandler.setFormatter(formatter)
logger.addHandler(streamhandler)

def set_log_file(filename):
    # Set file logger
    filehandler = logging.FileHandler(filename)
    filehandler.setFormatter(formatter)
    logger.addHandler(filehandler)