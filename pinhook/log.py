from datetime import datetime, timezone
import json
import logging
import os
import sys

# values that came from ${...} in the config, kept out of the log
secrets: set[str] = set()
# a shorter value would mask common words all through the log
SHORTEST_SECRET = 4


def hide(value):
    """Show value as *** in log lines from now on."""
    if len(value) >= SHORTEST_SECRET:
        secrets.add(value)


def mask(text):
    """text with every hidden value replaced by ***, longest first."""
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, '***')
    return text


class MaskingFormatter(logging.Formatter):
    """Formats log lines with hidden values masked, tracebacks included."""

    def format(self, record):
        return mask(super().format(record))


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for log collectors: time, level, bot and message, with
    "audit": true on changes to who can do what, and the traceback as error."""

    def format(self, record):
        line = {
            'time': datetime.fromtimestamp(record.created, timezone.utc)
                            .isoformat(timespec='milliseconds'),
            'level': record.levelname.lower(),
            'bot': record.name.partition('.')[2] or record.name,
            'message': mask(record.getMessage()),
        }
        if getattr(record, 'audit', False):
            line['audit'] = True
        if record.exc_info:
            line['error'] = mask(self.formatException(record.exc_info))
        return json.dumps(line)


logger = logging.getLogger('bot')
formatter = MaskingFormatter(
    '%(asctime)s - %(levelname)s - %(name)s - %(module)s - %(message)s')
# Set console logger
streamhandler = logging.StreamHandler()
streamhandler.setFormatter(formatter)
logger.addHandler(streamhandler)
FORMATS = {'text': formatter, 'json': JsonFormatter()}


def get_bot_logger(nickname):
    # each bot gets its own child of the 'bot' logger so it can have its own
    # level and log file, console output still goes through the parent
    bot_logger = logger.getChild(nickname)
    # a new bot with the same nick replaces the old one's log file
    for handler in list(bot_logger.handlers):
        bot_logger.removeHandler(handler)
        handler.close()
    bot_logger.propagate = True
    return bot_logger


def set_log_file(filename, target=logger, log_format='text'):
    """Log to filename, or to stdout when it's '-', as text or json."""
    if filename == '-':
        handler: logging.Handler = logging.StreamHandler(sys.stdout)
        # the console handler on the parent writes to stderr, and once is enough
        target.propagate = False
    else:
        # make the logs folder the first time
        folder = os.path.dirname(filename)
        if folder:
            os.makedirs(folder, exist_ok=True)
        handler = logging.FileHandler(filename)
    handler.setFormatter(FORMATS[log_format])
    target.addHandler(handler)
