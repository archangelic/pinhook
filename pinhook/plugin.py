from enum import Enum
from functools import wraps

plugins = {}
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

class _BasePlugin:
    enabled = True

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False


class Listener(_BasePlugin):
    def __init__(self, name, run=None):
        self.name = name
        if run:
            self.run = run

    def __str__(self):
        return self.name

    def run(self):
        pass

    def add_listener(self):
        lstnrs[self.name] = self
        plugins[self.name] = self


class Command(_BasePlugin):
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.help_text = kwargs.get('help_text', 'N/A')
        self.ops = kwargs.get('ops', False)
        self.ops_msg = kwargs.get('ops_msg', '')
        self.run = kwargs.get('run', self.run)

    def __str__(self):
        return self.cmd
    
    def run(self, msg):
        pass

    def enable_ops(self, ops_msg):
        self.ops = True
        self.ops_msg = ops_msg

    def update_plugin(self, **kwargs):
        self.help_text = kwargs.get('help_text', 'N/A')
        self.run = kwargs.get('run', self.run)

    def add_command(self):
        cmds[self.cmd] = self
        plugins[self.cmd] = self


def action(msg):
    return Output(OutputType.Action, msg)


def message(msg):
    return Output(OutputType.Message, msg)


def _add_command(command, help_text, func):
    if command not in cmds:
        Command(command, help_text=help_text, run=func).add_command()
    else:
        cmds[command].update_plugin(help_text=help_text, run=func)


def _ops_plugin(command, ops_msg, func):
    if command not in cmds:
        Command(command, ops=True, ops_msg=ops_msg).add_command()
    else:
        cmds[command].enable_ops(ops_msg)


def _add_listener(name, func):
    Listener(name, run=func).add_listener()


def clear_plugins():
    cmds.clear()
    lstnrs.clear()


def register(command, help_text='N/A'):
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
