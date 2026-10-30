"""Decorators and replies for writing plugins the 1.x way.

A plugin is a .py file in the bot's plugin folder. Mark its functions with
`command` or `listener`, and return `message` or `action` to reply.
See https://archangelic.github.io/pinhook/latest/plugins/
"""
from enum import Enum
import threading

# a bot's registry sets this while it imports a plugin file, so the decorators
# below know where to record what the file registers
_collector: list | None = None
_lock = threading.RLock()


class OutputType(Enum):
    Message = 'message'
    Action = 'action'


class Output:
    def __init__(self, msg_type, msg):
        self.msg_type = msg_type
        self.msg = self.sanitize(msg)

    def sanitize(self, msg):
        if isinstance(msg, str):
            return msg.splitlines()
        if isinstance(msg, (list, tuple)):
            # items in a list can have newlines too
            return [line for m in msg for line in str(m).splitlines()]
        return msg


def action(msg):
    """Reply with a /me action, where the message came from.

    Args:
        msg: the text, or a list of lines. Each line is sent separately.
    """
    return Output(OutputType.Action, msg)


def message(msg):
    """Reply with a message, where the message came from.

    Args:
        msg: the text, or a list of lines. Each line is sent separately.
    """
    return Output(OutputType.Message, msg)


def _collect(kind, name, func, **options):
    # outside a bot loading plugins, like a test importing a plugin file, there's nowhere to record
    if _collector is not None:
        _collector.append((kind, name, func, options))


def command(command, help_text='N/A', ops=False, ops_msg='', hide=False):
    """Make a function a command, run when a message starts with its command word.

    The function gets the message as its only argument.

    Args:
        command: the command word, like '!roll'.
        help_text: shown next to the command in !help.
        ops: if True, only bot operators can run it.
        ops_msg: what anyone else is told when they try. Empty means no reply.
        hide: if True, leave it out of !help.
    """
    def register_for_command(func):
        _collect('command', command, func, help_text=help_text, ops=ops, ops_msg=ops_msg,
                 hide=hide)
        return func
    return register_for_command


def listener(name):
    """Make a function a listener, run for every message that isn't a command.

    The function gets the message as its only argument, and returns nothing
    when it has nothing to say.

    Args:
        name: the listener's name, shown in !help and used by !enable and !disable.
    """
    def register_as_listener(func):
        _collect('listener', name, func)
        return func
    return register_as_listener


def register(command, help_text='N/A'):
    """Removed in 2.0, use `command` instead."""
    raise RuntimeError("@register was removed in pinhook 2.0, use @command('{}') instead"
                       .format(command))


def ops(command, msg=None):
    """Removed in 2.0, use `command` with ops=True instead."""
    raise RuntimeError("@ops was removed in pinhook 2.0, use @command('{}', ops=True, "
                       "ops_msg=...) instead".format(command))
