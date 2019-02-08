from enum import Enum
from functools import wraps


cmds = {}
lstnrs = {}


class OutputType(Enum):
    Message = 'message'
    Action = 'action'


class Output:
    def __init__(self, msg_type, msg):
        self.msg_type = msg_type
        self.msg = self.sanitize(msg)

    def sanitize(self, msg):
        try:
            return msg.splitlines()
        except AttributeError:
            return msg


def action(msg):
    return Output(OutputType.Action, msg)


def message(msg):
    return Output(OutputType.Message, msg)


def _add_plugin(command, help_text, func):
    if command not in cmds:
        cmds[command] = {}
    cmds[command].update({
        'run': func,
        'help': help_text
    })

def _ops_plugin(command, ops_msg, func):
    if command not in cmds:
        cmds[command] = {}
    cmds[command].update({
        'ops': True,
        'ops_msg': ops_msg,
    })


def _add_listener(name, func):
    lstnrs[name] = func


def clear_plugins():
    cmds.clear()
    lstnrs.clear()


def register(command, help_text=None):
    @wraps(command)
    def register_for_command(func):
        _add_plugin(command, help_text, func)
        return func
    return register_for_command


def listener(name):
    def register_as_listener(func):
        _add_listener(name, func)
        return func
    return register_as_listener

def ops(command, msg=None):
    @wraps(command)
    def register_ops_command(func):
        _ops_plugin(command, msg, func)
        return func
    return register_ops_command
