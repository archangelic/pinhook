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


class Command:
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.help_txt = kwargs.get('help_txt', '')
        self.ops = kwargs.get('ops', False)
        self.ops_msg = kwargs.get('ops_msg', '')
        self.enabled = True
        self.run = kwargs.get('run', self.run)
    
    def run(self, msg):
        pass

    def enable_ops(self, ops_msg):
        self.ops = True
        self.ops_msg = ops_msg

    def update_plugin(self, **kwargs):
        self.help_text = kwargs.get('help_text')
        self.run = kwargs.get('run', self.run)

    def add_command(self):
        cmds[self.cmd] = self

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False

    def __str__(self):
        return self.cmd


def action(msg):
    return Output(OutputType.Action, msg)


def message(msg):
    return Output(OutputType.Message, msg)


def _add_command(command, help_text, func):
    if command not in cmds:
        cmds[command] = Command(command, help_txt=help_text, run=func)
    else:
        cmds[command].update_plugin(help_text=help_text, run=func)
    print(cmds)


def _ops_plugin(command, ops_msg, func):
    if command not in cmds:
        cmds[command] = Command(command, ops=True, ops_msg=ops_msg)
    else:
        cmds[command].enable_ops(ops_msg)


def _add_listener(name, func):
    lstnrs[name] = func


def clear_plugins():
    cmds.clear()
    lstnrs.clear()


def register(command, help_text=None):
    @wraps(command)
    def register_for_command(func):
        _add_command(command, help_text, func)
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
