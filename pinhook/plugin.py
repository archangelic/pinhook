"""Decorators and replies for writing plugins.

A plugin is a .py file in the bot's plugin folder. Mark its functions with
`command` or `listener`, and return `message` or `action` to reply.
See https://archangelic.github.io/pinhook/latest/plugins/
"""
from enum import Enum
from functools import wraps
import importlib.util
import os
import sys
import warnings

from .log import logger

plugins: dict[str, '_BasePlugin'] = {}
cmds: dict[str, 'Command'] = {}
lstnrs: dict[str, 'Listener'] = {}


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


class _BasePlugin:
    enabled = True
    logger = logger

    @property
    def file_name(self):
        # the plugin file this came from, which names its store and config section
        module = getattr(self.run, '__module__', None) or 'plugin'
        return module[len('pinhook_plugins.'):] if module.startswith('pinhook_plugins.') else module

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
        self.hide = kwargs.get('hide', False)
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


def _add_command(command, help_text, func, ops=False, ops_msg='', hide=False):
    if command not in cmds:
        Command(command, help_text=help_text, ops=ops, ops_msg=ops_msg, hide=hide, run=func)
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
    plugins.clear()


def load_plugins(plugin_dir, use_prefix=False, cmd_prefix='!', logger=logger):
    # i'm not sure why i need this but i do
    global cmds
    global plugins
    global lstnrs
    # check for all the disabled plugins so that we don't re-enable them
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
                # load under our own name, so a plugin called json.py can't replace the json module
                spec = importlib.util.spec_from_file_location(
                    'pinhook_plugins.' + name, os.path.join(plugin_dir, m))
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
            except Exception:
                logger.exception('could not load plugin')
    # gather all commands and listeners
    if use_prefix:  # use prefixes if needed
        cmds = {cmd_prefix + k: v for k, v in cmds.items()}
    for p in plugins:
        if p in disabled_plugins:
            plugins[p].disable()
    for cmd in cmds:
        logger.debug('adding command {}'.format(cmd))
    for lstnr in lstnrs:
        logger.debug('adding listener {}'.format(lstnr))


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
    @wraps(command)
    def register_for_command(func):
        _add_command(command, help_text, func, ops=ops, ops_msg=ops_msg, hide=hide)
        return func
    return register_for_command


def register(command, help_text='N/A'):
    """Deprecated, will be removed in 2.0. Use `command` instead."""
    message = ("@register is deprecated and will be removed in 2.0, "
               "use @command('{}') instead".format(command))
    logger.warning(message)
    warnings.warn(message, DeprecationWarning, stacklevel=2)

    @wraps(command)
    def register_for_command(func):
        _add_command(command, help_text, func)
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
        _add_listener(name, func)
        return func
    return register_as_listener


def ops(command, msg=None):
    """Deprecated, will be removed in 2.0. Use `command` with ops=True instead."""
    message = ("@ops is deprecated and will be removed in 2.0, "
               "use @command('{}', ops=True, ops_msg=...) instead".format(command))
    logger.warning(message)
    warnings.warn(message, DeprecationWarning, stacklevel=2)

    @wraps(command)
    def register_ops_command(func):
        _ops_plugin(command, msg, func)
        return func
    return register_ops_command
