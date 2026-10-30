"""Each bot's plugins: loading them from plugin_dir, and finding their commands and listeners.

Every bot has its own registry, so two bots in one process never share plugins.
"""
import importlib.util
import json
import os
import re
import sys
import types

from . import plugin
from .store import write_json


class LoadError(Exception):
    """A plugin file that can't be loaded alongside the others."""


class Handler:
    """A command or a listener, registered by a plugin file.

    Attributes:
        kind: 'command' or 'listener'.
        name: a command's name without a prefix, or a listener's name.
        trigger: for a 1.x command whose word doesn't start with one of the bot's
            prefixes, like '.weather', the word it answers to. None otherwise.
        plugin: the plugin file's name, which names its store and config section.
        func: the function to call.
    """

    def __init__(self, kind, name, plugin_name, func, trigger=None, help_text='N/A', ops=False,
                 ops_msg='', hide=False):
        self.kind = kind
        self.name = name
        self.trigger = trigger
        self.plugin = plugin_name
        self.func = func
        self.help_text = help_text
        self.ops = ops
        self.ops_msg = ops_msg
        self.hide = hide

    def label(self, prefix):
        """How the bot writes it in logs and !help: the word that runs a command."""
        if self.kind == 'listener':
            return self.name
        return self.trigger or prefix + self.name


def module_name(name):
    # bot nicks can hold characters an import can't, like - and [
    return re.sub(r'\W', '_', name).lower()


class Registry:
    """The commands and listeners one bot's plugins registered.

    Args:
        bot_name: the bot's nick, which names its plugins' modules.
        prefixes: the command prefixes, like ['!'].
        reserved: names plugins can't use, the bot's own commands.
        logger: the bot's logger.
    """

    def __init__(self, bot_name, prefixes, reserved, logger):
        self.package = 'pinhook_plugins.' + module_name(bot_name)
        self.prefixes = list(prefixes)
        self.reserved = set(reserved)
        self.logger = logger
        self.clear()

    def clear(self):
        self.commands = {}
        self.literals = {}
        self.listeners = {}
        # plugin file name: its handlers
        self.plugins = {}

    def load(self, plugin_dir):
        """Load every .py file in plugin_dir, replacing whatever was loaded before."""
        self.logger.info('clearing plugin cache')
        self.clear()
        self.logger.info('checking plugin directory')
        if not os.path.exists(plugin_dir):
            self.logger.info('plugin directory {} not found, creating'.format(plugin_dir))
            os.makedirs(plugin_dir)
        self.make_packages()
        for file_name in sorted(os.listdir(plugin_dir)):
            if not file_name.endswith('.py'):
                continue
            name = file_name[:-3]
            self.logger.info('loading plugin {}'.format(name))
            try:
                self.add(name, self.import_file(name, os.path.join(plugin_dir, file_name)))
            except Exception:
                self.logger.exception('could not load plugin {}'.format(name))
        for handler in self.handlers():
            self.logger.debug('adding {} {}'.format(handler.kind, handler.name))

    def make_packages(self):
        # so a plugin can import another as pinhook_plugins.<bot>.<name>
        for package in ('pinhook_plugins', self.package):
            if package not in sys.modules:
                module = types.ModuleType(package)
                module.__path__ = []
                sys.modules[package] = module

    def import_file(self, name, path):
        # compiled from the source every time: python's bytecode cache goes by the file's
        # size and mtime in whole seconds, so a quick edit before !reload could load the old code
        spec = importlib.util.spec_from_file_location(self.package + '.' + name, path)
        module = importlib.util.module_from_spec(spec)
        with open(path, 'rb') as f:
            code = compile(f.read(), path, 'exec')
        # the decorators in pinhook.plugin record what the file registers while it runs
        with plugin._lock:
            plugin._collector = []
            try:
                sys.modules[spec.name] = module
                exec(code, module.__dict__)
                return plugin._collector
            finally:
                plugin._collector = None

    def add(self, plugin_name, registered):
        # check the whole file first, so a clash leaves none of it half loaded
        handlers = [self.handler(plugin_name, *entry) for entry in registered]
        taken = {}
        for handler in handlers:
            key = (handler.kind, handler.trigger or handler.name)
            if key in taken:
                raise LoadError('plugin {} registers {} {} twice'.format(
                    plugin_name, handler.kind, handler.label(self.prefixes[0])))
            taken[key] = handler
            owner = self.owner(handler)
            if owner:
                raise LoadError('plugin {} registers {} {}, which {} already has'.format(
                    plugin_name, handler.kind, handler.label(self.prefixes[0]), owner))
        for handler in handlers:
            if handler.kind == 'listener':
                self.listeners[handler.name] = handler
            elif handler.trigger:
                self.literals[handler.trigger] = handler
            else:
                self.commands[handler.name] = handler
        self.plugins[plugin_name] = handlers

    def handler(self, plugin_name, kind, name, func, options):
        if kind == 'listener':
            return Handler(kind, name, plugin_name, func)
        command, trigger = self.split_trigger(name)
        return Handler(kind, command, plugin_name, func, trigger=trigger, **options)

    def split_trigger(self, word):
        # 1.x commands are written with their prefix, like '!roll'. One of the bot's
        # prefixes is dropped, and a word with no prefix uses the bot's prefixes
        for prefix in sorted(self.prefixes, key=len, reverse=True):
            if word.startswith(prefix) and len(word) > len(prefix):
                return word[len(prefix):], None
        if word[:1].isalnum():
            return word, None
        return word, word

    def owner(self, handler):
        # who already has this name, if anyone
        if handler.kind == 'listener':
            other = self.listeners.get(handler.name)
        elif handler.trigger:
            other = self.literals.get(handler.trigger)
        else:
            if handler.name in self.reserved:
                return 'the bot itself'
            other = self.commands.get(handler.name)
        return 'plugin ' + other.plugin if other else None

    def handlers(self):
        return [h for handlers in self.plugins.values() for h in handlers]

    def find(self, word, addressed=False):
        """The command a message's first word runs, or None.

        A word written with one of the bot's prefixes runs the command of that
        name. Addressing the bot by nick also runs one without a prefix.
        """
        if word in self.literals:
            return self.literals[word]
        name = self.strip_prefix(word)
        if name is None and addressed:
            name = word
        return self.commands.get(name) if name else None

    def strip_prefix(self, word):
        for prefix in sorted(self.prefixes, key=len, reverse=True):
            if word.startswith(prefix) and len(word) > len(prefix):
                return word[len(prefix):]
        return None


class Switches:
    """Where plugins are on: plugin_channels from the config, with !enable and !disable on top.

    A name is a plugin file, a command or a listener. For a message in a channel,
    the channel's own !enable or !disable wins, then an "all" one, then
    plugin_channels, which keeps a name to the channels it lists. Private
    messages only follow "all".

    Args:
        limits: plugin_channels, {name: [channel, ...]}.
        path: where !enable and !disable are saved, or None to keep them in memory.
        fold: the server's case folding, so #Games and #games are one channel.
    """

    def __init__(self, limits, path, fold):
        self.limits = {name: list(channels) for name, channels in (limits or {}).items()}
        self.path = path
        self.fold = fold
        self.saved = self.load()

    def load(self):
        if not self.path or not os.path.exists(self.path):
            return {}
        with open(self.path) as f:
            try:
                saved = json.load(f)
            except ValueError as e:
                raise ValueError("couldn't read {}: {}".format(self.path, e))
        if not isinstance(saved, dict):
            raise ValueError('{} should hold a JSON object'.format(self.path))
        return saved

    def save(self):
        if self.path:
            write_json(self.path, self.saved)

    def is_on(self, names, channel=None):
        """True if none of names is off where the message is. channel is None if it's private."""
        return all(self.name_on(name, channel) for name in names)

    def name_on(self, name, channel):
        entry = self.saved.get(name, {})
        if channel is not None:
            for saved_channel, on in entry.get('channels', {}).items():
                if self.fold(saved_channel) == self.fold(channel):
                    return on
        if entry.get('all') is not None:
            return entry['all']
        if channel is not None and name in self.limits:
            return self.fold(channel) in {self.fold(c) for c in self.limits[name]}
        return True

    def set(self, name, on, channel=None):
        """Turn name on or off in channel, or everywhere when channel is None."""
        entry = self.saved.setdefault(name, {'all': None, 'channels': {}})
        if channel is None:
            entry['all'] = on
            entry['channels'] = {}
        else:
            channels = entry.setdefault('channels', {})
            for saved_channel in list(channels):
                if self.fold(saved_channel) == self.fold(channel):
                    del channels[saved_channel]
            channels[channel] = on
        self.save()
