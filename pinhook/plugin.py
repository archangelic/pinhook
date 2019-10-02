from enum import Enum
from functools import wraps
import importlib
import os

from .log import logger

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
    logger = logger

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False


class Listener(_BasePlugin):
    def __init__(self, name, run=None):
        self.name = name
        if run:
            self.run = run
        self._add_listener()

    def __str__(self):
        return self.name

    def run(self):
        pass

    def _add_listener(self):
        lstnrs[self.name] = self
        plugins[self.name] = self


class Command(_BasePlugin):
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.help_text = kwargs.get('help_text', 'N/A')
        self.ops = kwargs.get('ops', False)
        self.ops_msg = kwargs.get('ops_msg', '')
        self.run = kwargs.get('run', self.run)
        self._add_command()

    def __str__(self):
        return self.cmd
    
    def run(self, msg):
        pass

    def _enable_ops(self, ops_msg):
        self.ops = True
        self.ops_msg = ops_msg

    def _update_plugin(self, **kwargs):
        self.help_text = kwargs.get('help_text', 'N/A')
        self.run = kwargs.get('run', self.run)

    def _add_command(self):
        cmds[self.cmd] = self
        plugins[self.cmd] = self


def action(msg):
    return Output(OutputType.Action, msg)

def message(msg):
    return Output(OutputType.Message, msg)

def _add_command(command, help_text, func,  ops=False, ops_msg=''):
    if command not in cmds:
        Command(command, help_text=help_text, ops=ops, ops_msg=ops_msg, run=func)
    else:
        cmds[command]._update_plugin(help_text=help_text, run=func)

def _ops_plugin(command, ops_msg, func):
    if command not in cmds:
        Command(command, ops=True, ops_msg=ops_msg)
    else:
        cmds[command]._enable_ops(ops_msg)

def _add_listener(name, func):
    Listener(name, run=func)

def clear_plugins():
    cmds.clear()
    lstnrs.clear()

def load_plugins(plugin_dir, use_prefix=False, cmd_prefix='!'):
    # i'm not sure why i need this but i do
    global cmds
    global plugins
    global lstnrs
    #check for all the disabled plugins so that we don't re-enable them
    disabled_plugins = [i for i in plugins if not plugins[i].enabled]
    logger.debug(disabled_plugins)
    # clear plugin list to ensure no old plugins remain
    logger.info('clearing plugin cache')
    clear_plugins()
    # ensure plugin folder exists
    logger.info('checking plugin directory')
    if not os.path.exists(plugin_dir):
        logger.info('plugin directory {} not found, creating'.format(plugin_dir))
        os.makedirs(plugin_dir)
    # load all plugins
    for m in os.listdir(plugin_dir):
        if m.endswith('.py'):
            try:
                name = m[:-3]
                logger.info('loading plugin {}'.format(name))
                spec = importlib.machinery.PathFinder().find_spec(name, [plugin_dir])
                spec.loader.load_module()
            except Exception:
                logger.exception('could not load plugin')
    # gather all commands and listeners
    if use_prefix: # use prefixes if needed
        cmds = {cmd_prefix + k: v for k,v in cmds.items()}
    for p in plugins:
        if p in disabled_plugins:
            plugins[p].disable()
    for cmd in cmds:
        logger.debug('adding command {}'.format(cmd))
    for lstnr in lstnrs:
        logger.debug('adding listener {}'.format(lstnr))

def command(command, help_text='N/A', ops=False, ops_msg=''):
    @wraps(command)
    def register_for_command(func):
        _add_command(command, help_text, func, ops=ops, ops_msg=ops_msg)
        return func
    return register_for_command

def register(command, help_text='N/A'):
    logger.warn('@register decorator has been deprecated in favor of @command. This will cause errors in future versions.')
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
    logger.warn('use of the @ops decorator has been deprecated in favor of using the @command decorator with the ops and ops_msg options. Use will cause errors in future versions.')
    @wraps(command)
    def register_ops_command(func):
        _ops_plugin(command, msg, func)
        return func
    return register_ops_command
