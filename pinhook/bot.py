"""The bots: Bot for IRC servers and TwitchBot for Twitch chat."""
import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
import difflib
import logging
import os
import shlex
import signal
import ssl
import time
import warnings

import yaml

from . import access
from . import commands
from . import compat
from . import health
from . import log
from . import plugin
from .access import Access
from .context import Context, server_time, text_lines
from .history import Entry, History
from .output import OutputQueue
from . import recipes
from .recipes.engine import RECIPES, run_recipe
from .registry import Handler, Registry, Switches
from .store import PluginConfig, Store
from .transport.base import Event, Outgoing, Source, Transport, is_channel
from .transport.identity import entry_kind
from .transport.irc import IrcTransport, TwitchTransport


def did_you_mean(name, names):
    """", did you mean 'x'?" for the closest of names to a name that's probably a typo,
    or nothing."""
    close = difflib.get_close_matches(name, names, n=1)
    return ", did you mean '{}'?".format(close[0]) if close else ''


@dataclass(frozen=True)
class RunResult:
    """How running a command as someone went, from bot.run_as.

    status is 'ran', 'refused' (no access, banned, or switched off here), 'busy' (their
    last run of it is still going), 'failed' (bad arguments, an error or a timeout) or
    'unknown' (no such command). lines are what it said, when captured. error says
    what went wrong, or is None.
    """
    status: str
    lines: tuple[str, ...]
    error: str | None


class Bot:
    """An IRC bot that loads plugins from a folder and runs them.

    Args:
        channels: channels to join once connected.
        nickname: the bot's nick.
        server: the server to connect to.
        **kwargs: any of the bot's options, like port, ssl_required or ops. See
            https://archangelic.github.io/pinhook/latest/options/
            config_dir is the folder relative paths are in, including bot_dir's: the
            config file's folder when pinhook run starts the bot, and the working
            directory by default.

    Call start() to connect and run until the bot quits.
    """
    internal_commands = {
        'join': 'join a channel',
        'quit': 'force the bot to quit',
        'reload': 'force bot to reload all plugins',
        'enable': 'enable a plugin',
        'disable': 'disable a plugin',
        'op': 'add a user as bot operator',
        'deop': 'remove a user as bot operator',
        'ops': 'list all ops',
        'ban': 'ban a user from using the bot, by account or host when possible',
        'unban': 'remove bot ban for user',
        'banlist': 'list current bans',
        'allow': 'give someone access to a plugin or command',
        'deny': 'keep someone off a plugin or command',
        'revoke': 'take back an allow or deny',
        'access': 'show who can use a plugin or command',
        'recipe': 'add a one-line recipe, or remove a recipe',
    }
    # keyword options Bot understands, subclasses can add their own
    options = {
        'port', 'ops', 'plugin_dir', 'ssl_required', 'ssl_verify', 'ns_pass',
        'nickserv', 'log_level', 'log_file', 'server_pass', 'cmd_prefix',
        'use_prefix_for_plugins', 'disable_help', 'banned_users', 'bot_mode',
        'ban_file', 'require_account', 'bot_dir', 'data_dir', 'plugin_config',
        'sasl_account', 'sasl_password', 'address_by_nick', 'plugin_channels', 'access',
        'history', 'recipe_dir', 'log_format', 'health_port', 'health_host',
        'sasl_mechanism', 'ssl_certfile', 'ssl_keyfile',
    }
    log_levels = {
        'critical': logging.CRITICAL,
        'error': logging.ERROR,
        'warning': logging.WARNING,
        'warn': logging.WARNING,
        'info': logging.INFO,
        'debug': logging.DEBUG,
    }
    transport: Transport
    # how long a plugin can take to answer before the bot stops waiting for it
    handler_timeout = 30
    # how long the bot waits for queued messages to go out when it quits
    shutdown_wait = 5
    # set by the pinhook command, so !reload can read plugin_config from the config file again
    config_file = None
    config_loader = None
    # set by pinhook run --reload, to reload plugins and recipes when their files change,
    # checking every watch_interval seconds
    reload_on_change = False
    watch_interval = 1.0

    def __init__(self, channels, nickname, server, **kwargs):
        self.port = kwargs.get('port', 6667)
        self.ops = kwargs.get('ops', [])
        self.setup_paths(nickname, kwargs)
        self.ssl_required = kwargs.get('ssl_required', False)
        self.ssl_verify = kwargs.get('ssl_verify', True)
        self.ns_pass = kwargs.get('ns_pass', None)
        self.nickserv = kwargs.get('nickserv', 'NickServ')
        self.log_level = kwargs.get('log_level', 'info')
        self.server_pass = kwargs.get('server_pass', None)
        self.cmd_prefix = kwargs.get('cmd_prefix', '!')
        self.use_prefix_for_plugins = kwargs.get('use_prefix_for_plugins')
        self.address_by_nick = kwargs.get('address_by_nick', True)
        self.disable_help = kwargs.get('disable_help', False)
        self.bot_mode = kwargs.get('bot_mode', True)
        self.require_account = kwargs.get('require_account', False)
        self.sasl_password = kwargs.get('sasl_password') or None
        self.sasl_account = kwargs.get('sasl_account') or nickname
        mechanism = str(kwargs.get('sasl_mechanism') or 'auto')
        self.sasl_mechanism = 'auto' if mechanism.lower() == 'auto' else mechanism.upper()
        if self.sasl_mechanism not in ('auto', 'PLAIN', 'SCRAM-SHA-256', 'EXTERNAL'):
            raise ValueError('sasl_mechanism must be auto, PLAIN, SCRAM-SHA-256 or EXTERNAL')
        # a client certificate, for SASL EXTERNAL or a server that wants one
        self.ssl_certfile = kwargs.get('ssl_certfile') or None
        self.ssl_keyfile = kwargs.get('ssl_keyfile') or None
        self.server = server
        self.chanlist = channels
        self.bot_nick = nickname
        self.start_logging()
        self.transport = self.make_transport(server, nickname)
        self.setup_core()
        self.warn_unknown_options(kwargs)
        self.setup_bans(nickname, kwargs)
        self.check_entries()
        if self.sasl_password and not self.ssl_required:
            self.logger.warning('sasl_password will be sent without ssl, '
                                'turn on ssl_required to keep it private')
        self.setup_plugins()

    def warn_deprecated(self, key, message):
        # log each one once per bot, and warn every time so tests show where it came from
        warned = self.__dict__.setdefault('_deprecations_warned', set())
        if key not in warned:
            warned.add(key)
            self.logger.warning(message)
        warnings.warn(message, DeprecationWarning, stacklevel=3)

    def warn_unknown_options(self, kwargs):
        for key in sorted(set(kwargs) - self.options):
            hint = did_you_mean(key, self.options)
            self.logger.warning("unknown option '{}' ignored{}".format(key, hint))

    def setup_paths(self, nickname, kwargs):
        # with bot_dir set, everything lives in one folder: plugins/, data/ and logs/.
        # without it, files go where they did in 1.11. Either way, relative paths start
        # from config_dir, which isn't an option of its own
        self.config_dir = kwargs.pop('config_dir', None) or ''
        bot_dir = kwargs.get('bot_dir')
        self.bot_dir = os.path.join(self.config_dir, os.path.expanduser(bot_dir)) if bot_dir \
            else None
        if self.bot_dir:
            log_file = os.path.join('logs', '{}.log'.format(nickname))
            ban_file = os.path.join('data', '{}.bans.json'.format(nickname))
        else:
            log_file = '{}.log'.format(nickname)
            ban_file = '{}.bans.json'.format(nickname)
        self.plugin_dir = self.path(kwargs.get('plugin_dir', 'plugins'))
        recipe_dir = kwargs.get('recipe_dir', 'recipes')
        self.recipe_dir = self.path(recipe_dir) if recipe_dir else None
        self.data_dir = self.path(kwargs.get('data_dir', 'data'))
        # '-' is stdout, for containers and service managers that collect it
        log_file = kwargs.get('log_file') or log_file
        self.log_file = log_file if log_file == '-' else self.path(log_file)
        self.log_format = kwargs.get('log_format') or 'text'
        # the health endpoint, off unless health_port is set
        self.health_port = kwargs.get('health_port')
        self.health_host = kwargs.get('health_host') or '127.0.0.1'
        ban_file = kwargs.get('ban_file', ban_file)
        self.ban_file = self.path(ban_file) if ban_file else None
        self.stores = {}
        self.plugin_config = dict(kwargs.get('plugin_config') or {})
        self.plugin_channels = dict(kwargs.get('plugin_channels') or {})
        self.access_config = kwargs.get('access')
        self.history_config = kwargs.get('history')

    def path(self, path):
        """Where a path from the options really is: relative ones are inside bot_dir, if
        set, or else config_dir."""
        return os.path.join(self.bot_dir or self.config_dir, os.path.expanduser(path))

    def store(self, name):
        """The saved data for the plugin file called name, the same dict as its msg.store."""
        if name not in self.stores:
            self.stores[name] = self.open_store(name)
        return self.stores[name]

    def config_for(self, name):
        """The plugin_config section for the plugin file called name, as msg.config."""
        return PluginConfig(name, self.plugin_config.get(name), self.plugin_config.get('shared'))

    def reload_plugin_config(self):
        # only when the bot was started from a config file, says what happened for the !reload reply
        if not self.config_loader:
            return ''
        name = os.path.basename(self.config_file)
        try:
            config = self.config_loader()
            self.access.configure(config.get('access'))
        except Exception as e:
            self.logger.error(
                "couldn't read plugin_config and access from {} again, keeping the old settings: "
                "{}".format(self.config_file, e))
            return (", but {} has a problem so plugin_config and access weren't changed, "
                    "see the log".format(name))
        self.plugin_config = dict(config.get('plugin_config') or {})
        return ' (and plugin_config and access from {})'.format(name)

    def setup_plugins(self):
        # cmd_prefix can be one prefix or a list of them, plugin commands use them all
        prefixes = [self.cmd_prefix] if isinstance(self.cmd_prefix, str) else list(self.cmd_prefix)
        if not prefixes or not all(isinstance(p, str) and p for p in prefixes):
            raise ValueError('cmd_prefix must be a prefix like "!", or a list of them')
        self.prefixes = prefixes
        self.cmd_prefix = prefixes[0]
        if self.use_prefix_for_plugins is not None:
            self.logger.warning('use_prefix_for_plugins is retired in pinhook 2.0 and does '
                                'nothing: plugin commands always use cmd_prefix, so write them '
                                'without one')
        # where plugins are on, from plugin_channels and !enable and !disable
        self.switches = Switches(self.plugin_channels, self.switches_path(),
                                 self.transport.casefold)
        # !help isn't listed with the rest, it's shown to everyone
        self.builtins = set(self.internal_commands) | {'help'}
        self.registry = Registry(self.bot_nick, self.prefixes, self.builtins, self.logger)
        # who can use what, from the access config and !allow and !deny
        self.access = Access(self, self.access_config, self.access_path())
        # recent messages, in the channels the history option lists
        self.history = History(self.history_config, self.transport.casefold)
        self.registry.load(self.plugin_dir)
        self.load_recipes()
        self.reset_timers()
        self.check_plugin_config()

    def load_recipes(self):
        """Load the recipes in recipe_dir as commands, replacing any loaded before. A recipe
        that can't load, or whose name another command has, is logged and left out, and a
        store key a recipe reads but none sets is warned about."""
        self.registry.remove_plugin(RECIPES)
        found, problems = recipes.load_recipes(self.recipe_dir)
        handlers = [self.recipe_handler(recipe) for recipe in found.values()]
        problems += self.registry.add_handlers(RECIPES, handlers)
        for problem in problems:
            self.logger.error("couldn't load a recipe: {}".format(problem))
        self.recipes = {h.name: found[h.name] for h in self.registry.plugins[RECIPES]}
        self.recipe_problems = problems
        # recipes share one store, so a key nothing sets is most often a typo
        self.recipe_warnings = recipes.store_warnings(self.recipes)
        for warning in self.recipe_warnings:
            self.logger.warning(warning)
        if found:
            self.logger.info('loaded {} recipes from {}'.format(
                len(self.recipes), self.recipe_dir))

    def recipe_command(self, nick, arg, channel=None):
        # !recipe add <name> <reply template>, and !recipe del <name>
        action, _, rest = arg.strip().partition(' ')
        name, _, template = rest.strip().partition(' ')
        usage = ('{}: usage: {p}recipe add <name> <reply>, like {p}recipe add hug {{nick}} '
                 'hugs {{arg|default:everyone}}, or {p}recipe del <name>'.format(
                     nick, p=self.cmd_prefix))
        if action == 'add' and name and template.strip():
            return self.add_recipe(nick, name, template.strip())
        if action == 'del' and name and not template:
            return self.remove_recipe(nick, name)
        return usage

    def add_recipe(self, nick, name, template):
        if not self.recipe_dir:
            return "{}: this bot has no recipe_dir, so there's nowhere to save it".format(nick)
        if self.registry.find(name) or self.registry.commands.get(name) or \
                name in self.builtins:
            return '{}: {} is already a command'.format(nick, name)
        data = {'version': recipes.loader.VERSION, 'name': name,
                'help': 'added by {}'.format(nick), 'steps': [{'reply': template}]}
        try:
            recipes.parse_recipe(data, name)
        except recipes.RecipeError as e:
            return "{}: that recipe can't be saved: {}".format(nick, str(e).partition(': ')[2])
        path = os.path.join(self.recipe_dir, name + '.yaml')
        if os.path.exists(path):
            return '{}: {} already exists, so {} is taken'.format(nick, path, name)
        os.makedirs(self.recipe_dir, exist_ok=True)
        with open(path, 'w') as f:
            yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
        self.load_recipes()
        return '{}: added {}{}'.format(nick, self.cmd_prefix, name)

    def remove_recipe(self, nick, name):
        recipe = getattr(self, 'recipes', {}).get(name)
        if recipe is None or not recipe.path:
            return "{}: there's no recipe called {}".format(nick, name)
        folder = os.path.realpath(self.recipe_dir)
        if os.path.dirname(os.path.realpath(recipe.path)) != folder:
            return "{}: {} isn't in the recipe folder, so it's left alone".format(nick, name)
        os.remove(recipe.path)
        self.load_recipes()
        return '{}: removed {}{}'.format(nick, self.cmd_prefix, name)

    def recipe_handler(self, recipe):
        # a recipe is a command with one free-text argument, given to it as {arg}
        async def run(ctx, arg=''):
            await run_recipe(self, recipe, ctx, arg)
        return Handler('command', recipe.name, RECIPES, run, help_text=recipe.help,
                       ops=recipe.access == 'ops', restricted=recipe.access == 'restricted',
                       native=True, params=[commands.Param(
                           'arg', str, '', 'what the recipe is given, as {arg}')])

    def switches_path(self):
        # where !enable and !disable are saved
        return os.path.join(self.data_dir, '{}.plugins.json'.format(self.bot_nick))

    def access_path(self):
        # where !allow and !deny are saved
        return os.path.join(self.data_dir, '{}.access.json'.format(self.bot_nick))

    def check_plugin_config(self):
        for plugin_name, command, group in self.access.missing_groups():
            where = plugin_name if command is None else '{} {}'.format(plugin_name, command)
            self.logger.warning("!allow or !deny saved group {} for {}, but the config has no "
                                "group called that, so it matches no one".format(group, where))
        # a section for a plugin that isn't loaded is probably a typo
        loaded = set(self.registry.plugins) - {RECIPES}
        sections = [('plugin_config', set(self.plugin_config) - {'shared'}),
                    ('access.plugins', set(self.access.rules) - {RECIPES})]
        for setting, names in sections:
            for name in sorted(names - loaded):
                hint = did_you_mean(name, loaded)
                self.logger.warning("{} has settings for '{}', but there's no plugin called "
                                    "that{}".format(setting, name, hint))
        recipe_rule = self.access.rules.get(RECIPES)
        for name in sorted(set(recipe_rule.commands) if recipe_rule else ()):
            if name not in self.recipes:
                hint = did_you_mean(name, self.recipes)
                self.logger.warning("access.recipes has settings for '{}', but there's no "
                                    "recipe called that{}".format(name, hint))
        for name, rule in sorted(self.access.rules.items()):
            if name not in loaded:
                continue
            mine = {h.name for h in self.registry.plugins[name] if h.kind == 'command'}
            for command in sorted(set(rule.commands) - mine):
                hint = did_you_mean(command, mine)
                self.logger.warning("access.plugins.{}.commands has settings for '{}', but plugin "
                                    "{} has no command called that{}".format(name, command, name,
                                                                             hint))

    def open_store(self, name):
        return Store(name, os.path.join(self.data_dir, name + '.json'))

    def setup_bans(self, nickname, kwargs):
        self.config_bans = list(kwargs.get('banned_users', []))
        self.banned_users = list(self.config_bans)
        saved = access.load_bans(self.ban_file)
        for entry in saved:
            if not self.nick_in(entry, self.banned_users):
                self.banned_users.append(entry)
        if saved:
            self.logger.info('loaded {} bans from {}'.format(len(saved), self.ban_file))
        # recent nicks and who they are, so !ban troll can ban their account or host
        self.seen = OrderedDict()

    def check_entries(self):
        # ops and bans from the config, which have to be entries this platform uses
        access.check_entries(self.transport, self.ops, 'ops')
        access.check_entries(self.transport, self.config_bans, 'banned_users')

    def save_bans(self):
        # bans from the config stay in the config, the file keeps the ones made with !ban
        saved = [b for b in self.banned_users if not self.nick_in(b, self.config_bans)]
        access.save_bans(self.ban_file, saved)

    def remember(self, nick, user, host, account):
        key = self.transport.casefold(nick)
        self.seen[key] = (nick, user, host, account)
        self.seen.move_to_end(key)
        while len(self.seen) > 1000:
            self.seen.popitem(last=False)

    def last_seen(self, nick):
        """Who was last seen using nick, as a Source, or None."""
        seen = self.seen.get(self.transport.casefold(nick))
        return Source(*seen) if seen else None

    def ban_entry(self, target):
        # a nick on its own is easy to change, so the transport says what's harder to
        # dodge, like an account or a user and host. !allow and !deny use it too
        if entry_kind(target) != 'nick':
            return target, target
        seen = self.last_seen(target)
        if not seen:
            if self.transport.strongest_entry(Source(target)) == target:
                # on a platform where the nick is as good as it gets
                return target, target
            description = "{} (nick only, they haven't spoken since the bot started)"
            return target, description.format(target)
        entry = self.transport.strongest_entry(seen)
        if entry_kind(entry) == 'account':
            return entry, '{} (account {})'.format(target, entry[len('$a:'):])
        if entry_kind(entry) == 'nick':
            return entry, entry
        return entry, '{} ({})'.format(target, entry)

    def remove_bans(self, target):
        # the entry itself, plus anything banning the person last seen as target
        seen = self.last_seen(target)
        removed = [b for b in self.banned_users
                   if self.nick_in(b, [target]) or (seen and self.transport.matches(b, seen))]
        self.banned_users = [b for b in self.banned_users if b not in removed]
        return removed

    def ssl_context(self):
        """The ssl settings the bot connects with: checks certificates unless ssl_verify is off."""
        context = ssl.create_default_context()
        if not self.ssl_verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        if getattr(self, 'ssl_certfile', None):
            context.load_cert_chain(self.path(self.ssl_certfile),
                                    self.path(self.ssl_keyfile) if self.ssl_keyfile else None)
        return context

    def is_op(self, source):
        """True if the sender of a message is one of the bot's ops."""
        return access.matches_any(self.transport, self.ops, source)

    def nick_in(self, nick, nicks):
        # irc nicks are case insensitive, so Troll and troll are the same person
        fold = self.transport.casefold
        return any(fold(n) == fold(nick) for n in nicks)

    def start_logging(self):
        self.logger = log.get_bot_logger(self.bot_nick)
        log_level = str(self.log_level).lower()
        if log_level == 'off':
            self.logger.disabled = True
            return
        if log_level not in self.log_levels:
            raise ValueError("log_level must be one of: off, {}".format(', '.join(self.log_levels)))
        if self.log_format not in log.FORMATS:
            raise ValueError('log_format must be text or json')
        self.logger.disabled = False
        log.set_log_file(self.log_file, self.logger, self.log_format)
        self.logger.setLevel(self.log_levels[log_level])
        self.logger.info('Logging started!')

    # the network, through the transport

    def make_transport(self, server, nickname):
        return IrcTransport(
            self.logger, server, self.port, nickname, password=self.server_pass,
            ssl_context=self.ssl_context() if self.ssl_required else None,
            sasl_account=self.sasl_account, sasl_password=self.sasl_password,
            nickserv=self.nickserv, ns_pass=self.ns_pass, bot_mode=self.bot_mode,
            sasl_mechanism=self.sasl_mechanism,
            client_cert=bool(self.ssl_certfile) and self.ssl_required,
            sts_path=os.path.join(self.data_dir, 'sts.json'))

    def setup_core(self):
        # set once the bot is running, plugins in worker threads send through it
        self.loop = None
        # messages being handled, and the (nick, command) pairs still running
        self.handlers = set()
        self.running = set()
        # each 1.x plugin's thread, by plugin name
        self.workers = {}
        self.stopping = False
        self.quit_reason = ''
        # set while connected, timers only run then
        self.online = False
        # plugins already warned that their notices can't be sent here
        self.notice_warned = set()
        # each @every timer: when it's next due, and the ones still running
        self.timer_due = {}
        self.timer_busy = set()
        self.quitting = asyncio.Event()
        self.output = OutputQueue(self.send_out, self.transport.limits, self.logger,
                                  clock=lambda: self.clock(), sleep=lambda s: self.pause(s),
                                  exempt=getattr(self.transport, 'exempt', None))

    def start(self):
        """Connect, and run until the bot quits."""
        asyncio.run(self.run())

    async def run(self):
        """Connect, and run until the bot quits, or gets SIGTERM."""
        self.loop = asyncio.get_running_loop()
        try:
            self.loop.add_signal_handler(signal.SIGTERM, self.quit)
        except (NotImplementedError, RuntimeError, ValueError):
            # only the main thread can catch signals, and not on windows
            pass
        async with asyncio.TaskGroup() as core:
            core.create_task(self.transport.run())
            core.create_task(self.read_events())
            sender = core.create_task(self.output.run())
            timers = core.create_task(self.run_timers())
            if self.health_port:
                checks = core.create_task(health.serve(self, self.health_host, self.health_port))
            if self.reload_on_change:
                watcher = core.create_task(self.watch_files())
            await self.quitting.wait()
            try:
                # answers already on their way, then everything waiting to be sent
                async with asyncio.timeout(self.shutdown_wait):
                    if self.handlers:
                        await asyncio.wait(self.handlers)
                    await self.output.drain()
            except TimeoutError:
                self.logger.warning('quitting with {} messages still waiting to be sent'
                                    .format(self.output.waiting()))
            sender.cancel()
            timers.cancel()
            if self.health_port:
                checks.cancel()
            if self.reload_on_change:
                watcher.cancel()
            self.registry.teardown()
            await self.transport.close(self.quit_reason)

    def quit(self, reason=''):
        """Stop taking messages, send what's waiting, and quit with reason."""
        self.stopping = True
        self.quit_reason = reason or "See y'all later!"
        self.in_loop(self.quitting.set)

    def in_loop(self, func, *args):
        # plugins run in worker threads, and the output queue belongs to the event loop
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self.loop is None or running is self.loop:
            func(*args)
        else:
            self.loop.call_soon_threadsafe(func, *args)

    def clock(self):
        return time.monotonic()

    async def pause(self, seconds):
        # the output queue waiting for its rate limit
        await asyncio.sleep(seconds)

    @property
    def account_tag(self):
        """True once the server tags messages with the sender's account."""
        return self.transport.supports('account-tag')

    @property
    def sasl_logged_in(self):
        """True once the bot has logged in to its account with SASL."""
        return getattr(self.transport, 'sasl_logged_in', False)

    async def read_events(self):
        async for event in self.transport.events():
            self.dispatch(event)

    def dispatch(self, event):
        if event.type == 'connected':
            self.online = True
            self.connected()
            self.spawn(self.run_event_handlers(event))
        elif event.type == 'disconnected':
            self.online = False
            # answers to what was asked before the drop would be out of date
            dropped = self.output.clear()
            if dropped:
                self.logger.warning('disconnected, dropping {} messages that were waiting to be '
                                    'sent'.format(dropped))
            self.spawn(self.run_event_handlers(event))
        elif self.stopping:
            return
        elif event.type == 'message':
            self.spawn(self.process_event(event))
        else:
            self.spawn(self.process_other(event))

    def reset_timers(self):
        # each timer's first run is one interval after its plugin loaded
        now = self.clock()
        self.timer_due = {handler: now + handler.interval for handler in self.registry.timers}

    def fire_due_timers(self):
        """Start the timers that are due, and return the seconds until the next one."""
        now = self.clock()
        waits = []
        for handler in self.registry.timers:
            due = self.timer_due.setdefault(handler, now + handler.interval)
            if due <= now:
                if self.online and not self.stopping and handler not in self.timer_busy:
                    self.timer_busy.add(handler)
                    self.spawn(self.run_timer(handler))
                due += handler.interval
                if due <= now:
                    # a long gap, like while disconnected: carry on from now, without catching up
                    due = now + handler.interval
                self.timer_due[handler] = due
            waits.append(due - now)
        return min(waits, default=1.0)

    async def run_timer(self, handler):
        try:
            await self.run_handler(handler, Event('timer'), None, '')
        finally:
            self.timer_busy.discard(handler)

    def reload(self):
        """Load plugins and recipes again, with plugin_config and access from the config
        file. Says what happened to the config, for !reload's reply."""
        config_note = self.reload_plugin_config()
        self.registry.load(self.plugin_dir)
        self.load_recipes()
        self.reset_timers()
        self.check_plugin_config()
        return config_note

    def watched_files(self):
        # what --reload watches: plugin and recipe files, by when each last changed
        found = {}
        for folder, ends in ((self.plugin_dir, ('.py',)), (self.recipe_dir, ('.yaml', '.yml'))):
            if not folder or not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                if name.endswith(ends):
                    try:
                        found[path] = os.stat(path).st_mtime_ns
                    except OSError:
                        # gone between listing and looking, which the next check sees
                        pass
        return found

    async def watch_files(self):
        """For pinhook run --reload: reload when a plugin or recipe file is added, changed or
        removed."""
        seen = self.watched_files()
        while True:
            await asyncio.sleep(self.watch_interval)
            # the watcher runs beside the connection, so nothing in it can stop the bot
            try:
                now = self.watched_files()
                if now != seen:
                    changed = sorted(set(now) ^ set(seen) |
                                     {p for p in now if now[p] != seen.get(p)})
                    self.logger.info('reloading plugins, since {} changed'.format(
                        ', '.join(os.path.basename(p) for p in changed)))
                    seen = now
                    self.reload()
            except Exception:
                self.logger.exception('reloading after a file change failed')

    async def run_timers(self):
        # checks at least once a second, so timers from a !reload start on time
        while True:
            await asyncio.sleep(min(self.fire_due_timers(), 1.0))

    def spawn(self, coroutine):
        # each message or event is handled in its own task
        task = asyncio.get_running_loop().create_task(coroutine)
        self.handlers.add(task)
        task.add_done_callback(self.handled)

    def handled(self, task):
        self.handlers.discard(task)
        if not task.cancelled() and task.exception():
            self.logger.error('issue handling a message', exc_info=task.exception())

    def connected(self):
        if self.require_account and not self.account_tag:
            self.logger.error("require_account is on but this server doesn't tell the bot who is "
                              "logged in (account-tag), so the bot will ignore everyone")
        for channel in self.chanlist:
            self.logger.info('joining channel {}'.format(channel.split()[0]))
            self.transport.join(*channel.split())

    def send_message(self, kind, target, text, tags=None, prefix=''):
        """Queue a message to send. Safe to call from a plugin's thread."""
        self.in_loop(self.output.put, Outgoing(kind, target, text, prefix, dict(tags or {})))

    def send_text(self, kind, target, text, tags=None, prefix=''):
        """Queue text to send, a message per line, each starting with prefix. text can be a
        list of lines too."""
        for line in text_lines(text):
            self.send_message(kind, target, line, tags, prefix)

    def call_help(self, nick, op, arg='', source=None, channel=None):
        # names only, packed into as few messages as fit, and !help <command> for the rest.
        # source is who asked, and channel where, so the list can say what they can't use
        prefix = self.cmd_prefix
        who = source or Source(nick)
        where = channel if is_channel(channel or '') else None
        if arg:
            return self.command_help(nick, op, arg, who, where)
        names = {prefix + 'help': prefix + 'help'}
        for info in self.commands():
            if info.hidden or (info.level == 'ops' and not op):
                continue
            allowed = self.access.allows(who, self.registry.find(info.label), where)
            names[info.label] = info.label + ('' if allowed else ' (no access)')
        if op:
            names.update({prefix + name: prefix + name for name in self.internal_commands})
        groups = [('commands', [names[label] for label in sorted(names)])]
        if self.registry.listeners:
            groups.append(('listeners', sorted(self.registry.listeners)))
        groups.append((None, ['{}help <command> for more'.format(prefix)]))
        target = self.help_target(nick, where)
        self.send_help(target, commands.pack(groups, self.transport.text_room('privmsg', target)))
        return None

    def commands(self, who=None, channel=None):
        """Every command, as CommandInfo: name, help, typed arguments, plugin, access level
        and whether it's hidden, sorted by name. Structured data for code, like a tool
        list, where !help is for people.

        Args:
            who: a Source, to list only what that person can trigger.
            channel: where they'd trigger it, for chanops and voiced, or None if private.
        """
        found = []
        handlers = [h for h in self.registry.handlers() if h.kind == 'command']
        for handler in sorted(handlers, key=lambda h: h.name):
            if who is not None and not self.access.can_run(who, handler, channel):
                continue
            found.append(commands.command_info(handler, self.cmd_prefix,
                                               self.access.level(handler)))
        return found

    def help_target(self, nick, channel):
        # help goes privately, except where the network has no private messages from bots
        if channel and not self.transport.supports('private'):
            return channel
        return nick

    def send_help(self, target, lines):
        for line in lines:
            self.send_message('privmsg', target, line)

    def access_note(self, handler, who, channel):
        # restricted commands show for everyone, so people know to ask for access
        if self.access.allows(who, handler, channel):
            return ''
        if self.access.level(handler) == 'restricted':
            return " (restricted, you don't have access)"
        return " (you don't have access)"

    def command_help(self, nick, op, word, who, channel):
        # !help !roll or !help roll: one command's help, its usage line and what its
        # arguments mean
        prefix = self.cmd_prefix
        target = self.help_target(nick, channel)
        name = self.registry.strip_prefix(word) or word
        if op and name in self.internal_commands:
            line = '{}{} -- {}'.format(prefix, name, self.internal_commands[name])
            self.send_help(target, [line])
            return None
        handler = self.registry.find(word) or self.registry.find(word, addressed=True)
        if handler is None or (self.access.level(handler) == 'ops' and not op):
            self.send_help(target, ["there's no command called {}".format(word)])
            return None
        lines = ['{}{} -- {}'.format(handler.label(prefix), self.access_note(handler, who, channel),
                                     handler.help_text)]
        if handler.native:
            lines.append('usage: ' + commands.usage(handler.name, handler.params))
            described = [(None, [line]) for line in commands.describe(handler.params)]
            lines += commands.pack(described, self.transport.text_room('privmsg', target))
        self.send_help(target, lines)
        return None

    def call_internal_commands(self, channel, nick, cmd, arg, op=None, source=None):
        """Run a built-in command, and return its reply as a message() for the channel, or
        None. cmd is its name without the prefix. source is who sent it, if known."""
        if op is None:
            op = self.nick_in(nick, self.ops)
        if cmd == 'help':
            if not self.disable_help:
                self.call_help(nick, op, arg, source, channel)
            return None
        if cmd not in self.internal_commands or not op:
            return None
        if cmd in ('allow', 'deny', 'revoke', 'access'):
            reply = self.access_command(cmd, nick, arg)
        elif cmd in ('op', 'deop', 'ban', 'unban') and not arg.split():
            reply = '{}: usage: {}{} <nick>'.format(nick, self.cmd_prefix, cmd)
        else:
            reply = getattr(self, cmd + '_command')(nick, arg, channel)
        output = plugin.message(reply) if reply else None
        if cmd in self.audited and output is not None:
            self.audit(nick, source, cmd, arg, output)
        return output

    # the built-in commands for ops, run by name as <name>_command, each taking who ran it,
    # what they said after it and where, and returning the reply

    def join_command(self, nick, arg, channel):
        if not arg.split():
            return '{}: usage: {}join #channel [key]'.format(nick, self.cmd_prefix)
        self.transport.join(*arg.split())
        self.logger.info('joining {} per request of {}'.format(arg, nick))
        return '{}: joined {}'.format(nick, arg.split()[0])

    def quit_command(self, nick, arg, channel):
        self.logger.info('quitting per request of {}'.format(nick))
        self.quit(arg or "See y'all later!")

    def reload_command(self, nick, arg, channel):
        self.logger.info('reloading plugins per request of {}'.format(nick))
        return 'Plugins reloaded' + self.reload()

    def enable_command(self, nick, arg, channel):
        return self.switch(True, channel, nick, arg)

    def disable_command(self, nick, arg, channel):
        return self.switch(False, channel, nick, arg)

    def op_command(self, nick, arg, channel):
        for who in arg.split():
            if not self.nick_in(who, self.ops):
                self.ops.append(who)
        return '{}: {} added as op'.format(nick, arg)

    def deop_command(self, nick, arg, channel):
        for who in arg.split():
            self.ops = [entry for entry in self.ops if not self.nick_in(entry, [who])]
        return '{}: {} removed as op'.format(nick, arg)

    def ops_command(self, nick, arg, channel):
        return 'current ops: {}'.format(', '.join(self.ops))

    def ban_command(self, nick, arg, channel):
        banned, problems = [], []
        for target in arg.split():
            problem = access.entry_problem(self.transport, target)
            if problem:
                problems.append(problem)
                continue
            entry, description = self.ban_entry(target)
            if not self.nick_in(entry, self.banned_users):
                self.banned_users.append(entry)
            banned.append(description)
        if banned:
            self.save_bans()
        said = (['banned ' + ', '.join(banned)] if banned else []) + problems
        return '{}: {}'.format(nick, '. '.join(said))

    def unban_command(self, nick, arg, channel):
        removed = []
        for target in arg.split():
            removed += self.remove_bans(target)
        self.save_bans()
        if not removed:
            return '{}: no ban found for {}'.format(nick, arg)
        reply = '{}: removed ban on {}'.format(nick, ', '.join(removed))
        from_config = [b for b in removed if self.nick_in(b, self.config_bans)]
        if from_config:
            reply += (" ({} is in the config file, so it'll be back after a restart)"
                      .format(', '.join(from_config)))
        return reply

    def banlist_command(self, nick, arg, channel):
        return 'currently banned: {}'.format(', '.join(self.banned_users) or 'nobody')

    # the commands that change who can do what, logged as audit lines
    audited = {'op', 'deop', 'ban', 'unban', 'allow', 'deny', 'revoke', 'enable', 'disable',
               'recipe'}

    def audit(self, nick, source, cmd, arg, output):
        """Log who ran a command that changes who can do what, and what it did. In JSON logs
        the line carries "audit": true, so it can be kept longer than the rest."""
        who = nick
        if source is not None and source.account:
            who = '{} (account {})'.format(nick, source.account)
        reply = ' '.join(output.msg)
        if reply.startswith(nick + ': '):
            reply = reply[len(nick) + 2:]
        ran = '{}{} {}'.format(self.cmd_prefix, cmd, arg.strip()).strip()
        self.logger.info('{} ran {}: {}'.format(who, ran, reply), extra={'audit': True})

    # !allow, !deny, !revoke and !access

    def access_target(self, name):
        # a plugin file, or a command written with or without its prefix.
        # (plugin, None) for a plugin, (plugin, command) for a command
        if name in self.registry.plugins:
            return name, None
        handler = self.registry.find(name) or self.registry.commands.get(name)
        if handler is None:
            return None
        return handler.plugin, handler.name

    def target_label(self, plugin, command):
        if command is None:
            return 'plugin ' + plugin
        return self.target_handlers(plugin, command)[0].label(self.cmd_prefix)

    def target_handlers(self, plugin, command):
        # from the plugin's own list, which has 1.x commands with their own trigger word too
        return [h for h in self.registry.plugins[plugin] if h.kind in ('command', 'listener')
                and (command is None or (h.kind == 'command' and h.name == command))]

    def access_command(self, cmd, nick, arg):
        try:
            args = shlex.split(arg)
        except ValueError:
            args = arg.split()
        usage = '{}: usage: {}{} <plugin or command>{}'.format(
            nick, self.cmd_prefix, cmd, '' if cmd == 'access' else ' <who> [<who> ...]')
        if not args or (cmd == 'access') != (len(args) == 1):
            return usage
        target = self.access_target(args[0])
        if target is None:
            return "{}: there's no plugin or command called {}".format(nick, args[0])
        plugin_name, command = target
        label = self.target_label(plugin_name, command)
        if cmd == 'access':
            return self.describe_access(plugin_name, command)
        if cmd == 'revoke':
            return self.revoke(nick, plugin_name, command, label, args[1:])
        levels = {self.access.level(h) for h in self.target_handlers(plugin_name, command)}
        if levels == {'ops'}:
            # only the config file changes a level
            return ("{}: {} is ops only, so it can't be given out or denied from chat. Its level "
                    "is set in the config file".format(nick, label))
        if cmd == 'allow' and 'restricted' not in levels:
            return ("{}: {} is open to everyone, so access to it can't be given out. To make it "
                    "restricted, set that in the config file".format(nick, label))
        done, problems = [], []
        for target in args[1:]:
            problem = None if self.access.is_group(target) else access.entry_problem(
                self.transport, target)
            if problem:
                problems.append(problem)
                continue
            if self.access.is_group(target):
                entry, description = access.GROUP + target, target
            else:
                entry, description = self.ban_entry(target)
            added = self.access.add(cmd, plugin_name, command, entry)
            done.append(description + ('' if added else ' (already)'))
        verb = 'gave access to {} to' if cmd == 'allow' else 'kept off {}:'
        said = (['{} {}'.format(verb.format(label), ', '.join(done))] if done else []) + problems
        return '{}: {}'.format(nick, '. '.join(said))

    def revoke(self, nick, plugin_name, command, label, targets):
        fold = self.transport.casefold
        removed, in_config = [], []
        for target in targets:
            seen = self.last_seen(target)

            def wanted(entry):
                # the entry itself, or one that matches the person last seen as target
                return (fold(entry.removeprefix(access.GROUP)) == fold(target) or
                        bool(seen) and not self.access.is_group(entry) and
                        self.transport.matches(entry, seen))
            removed += self.access.remove(plugin_name, command, wanted)
            in_config += self.access.in_config(plugin_name, command, wanted)
        reply = '{}: '.format(nick)
        if removed:
            reply += 'took back {} on {}'.format(
                ', '.join(entry.removeprefix(access.GROUP) for entry in removed), label)
        else:
            reply += 'nothing to take back for {} on {}'.format(' '.join(targets), label)
        if in_config:
            reply += (' ({} is in the config file, so it stays until it\'s taken out there)'
                      .format(', '.join(in_config)))
        return reply

    def describe_access(self, plugin_name, command):
        # one line for the plugin or command, and one for each of a plugin's commands
        # whose access differs from the plugin's
        lines = []
        handlers = self.target_handlers(plugin_name, command)
        if command is None:
            plugin_handler = Handler('listener', plugin_name, plugin_name, None)
            lines.append(self.access_line('plugin ' + plugin_name, plugin_handler))
            for handler in handlers:
                if handler.kind == 'command':
                    line = self.access_line(handler.label(self.cmd_prefix), handler)
                    if line.partition(': ')[2] != lines[0].partition(': ')[2]:
                        lines.append(line)
        else:
            lines.append(self.access_line(handlers[0].label(self.cmd_prefix), handlers[0]))
        return lines

    def access_line(self, label, handler):
        level = self.access.level(handler)
        if level == 'ops':
            return '{}: ops only'.format(label)
        parts = [level]
        allowed = self.access.entries(handler, 'allow')
        denied = self.access.entries(handler, 'deny')
        allowed = [entry.removeprefix(access.GROUP) for entry in allowed]
        denied = [entry.removeprefix(access.GROUP) for entry in denied]
        if level == 'restricted':
            parts.append('allowed: ' + (', '.join(['ops'] + allowed)))
        if denied:
            parts.append('denied: ' + ', '.join(denied))
        return '{}: {}'.format(label, ', '.join(parts))

    def accepts(self, source):
        """True if the bot should act on something this person did."""
        self.remember(source.nick, source.user, source.host, source.account)
        return not self.ignores(source, log=True)

    def ignores(self, source, log=False):
        """True if the bot ignores this person: they're banned, they're the bot, or
        require_account is on and they aren't logged in."""
        nick, fold = source.nick, self.transport.casefold
        if access.matches_any(self.transport, self.banned_users, source):
            if log:
                self.logger.debug('ignoring banned user {}'.format(nick))
            return True
        if fold(nick) == fold(self.transport.nick):
            return True
        if self.require_account and not source.account:
            if log:
                self.logger.debug('ignoring {}, not logged in to an account'.format(nick))
            return True
        return False

    async def process_other(self, event):
        # joins, parts, nick changes and the rest, for @on handlers
        if event.source and not self.accepts(event.source):
            return
        await self.run_event_handlers(event)

    async def run_event_handlers(self, event):
        await asyncio.gather(*(self.run_handler(h, event, None, '')
                               for h in self.registry.events.get(event.type, [])))

    async def send_out(self, message):
        # the output queue sends through here. Where the server doesn't echo the bot's
        # messages back, history records them as they're sent
        await self.transport.send(message)
        if is_channel(message.target) and not self.transport.supports('echo-message'):
            self.history.add(message.target, Entry(
                self.transport.nick, message.prefix + message.text, message.kind,
                datetime.now(timezone.utc), own=True))

    def remember_message(self, event, own=False):
        if is_channel(event.target):
            self.history.add(event.target, Entry(
                event.source.nick, event.text, event.kind,
                server_time(event.tags.get('time')) or datetime.now(timezone.utc),
                event.tags.get('msgid'), own))

    async def process_event(self, event):
        if self.transport.casefold(event.source.nick) == self.transport.casefold(
                self.transport.nick):
            # the bot's own message, echoed back by the server
            self.remember_message(event, own=True)
            return
        if not self.accepts(event.source):
            return
        self.remember_message(event)
        nick = event.source.nick
        if event.kind == 'notice':
            # notices never run commands or 1.x listeners, a bot shouldn't answer one by itself
            await asyncio.gather(*(self.run_handler(h, event, None, '')
                                   for h in self.registry.events.get('notice', [])))
            return
        op = self.is_op(event.source)
        text = event.text
        chan = event.target if is_channel(event.target) else nick
        addressed, body = self.strip_address(text)
        # actions only reach listeners, a /me is never a command
        word, _, rest = body.partition(' ') if event.kind != 'action' else ('', '', '')
        arg = rest.strip()
        self.logger.debug(
            'Message info: channel: {}, nick: {}, cmd: {}, text: {}'.format(chan, nick, word, text)
        )
        name = None
        if word:
            # "pinhook: reload" runs a built-in command without its prefix too
            name = self.registry.strip_prefix(word) or (word if addressed else None)
        if name in self.builtins:
            output = self.call_internal_commands(chan, nick, name, arg, op=op,
                                                 source=event.source)
            if output and not self.stopping:
                self.process_output(chan, output)
                return
        if self.stopping:
            return
        handler = self.registry.find(word, addressed) if word else None
        if handler:
            await self.run_handler(handler, event, word, arg, addressed)
            return
        # each listener answers on its own, so a slow or broken one doesn't hold up the rest
        listeners = list(self.registry.listeners.values()) + self.registry.events.get('message', [])
        await asyncio.gather(*(self.run_handler(h, event, None, '', addressed)
                               for h in listeners))

    def strip_address(self, text):
        """(True, the rest) when text starts with the bot's nick, like "pinhook: hi",
        "pinhook, hi" or "@pinhook hi". (False, text) otherwise."""
        if not self.address_by_nick:
            return False, text
        nick, fold = self.transport.nick, self.transport.casefold
        at = text.startswith('@')
        body = text[1:] if at else text
        if fold(body[:len(nick)]) != fold(nick):
            return False, text
        rest = body[len(nick):]
        if rest[:1] in (':', ','):
            return True, rest[1:].lstrip()
        if at and rest[:1] in ('', ' '):
            return True, rest.lstrip()
        return False, text

    def canonical_name(self, name):
        # what !enable and !disable take: a plugin file, a command or a listener.
        # a command written with its prefix, like !roll, means the command roll
        if name in self.registry.plugins:
            return name
        for handler in self.registry.handlers():
            if name in (handler.name, handler.label(self.cmd_prefix)):
                return handler.name
            if handler.kind == 'command' and self.registry.strip_prefix(name) == handler.name:
                return handler.name
        return None

    def switch(self, on, channel, nick, arg):
        # !enable and !disable <name> [all | #channel]: the current channel by default,
        # and everywhere from a private message
        try:
            args = shlex.split(arg)
        except ValueError:
            args = arg.split()
        verb = 'enable' if on else 'disable'
        scope_ok = len(args) < 2 or args[1] == 'all' or is_channel(args[1])
        if not args or len(args) > 2 or not scope_ok:
            return '{}: usage: {}{} <plugin> [all | #channel]'.format(
                nick, self.cmd_prefix, verb)
        name = self.canonical_name(args[0])
        if name is None:
            return "{}: '{}' not found".format(nick, args[0])
        where = args[1] if len(args) == 2 else channel
        target = where if is_channel(where) else None
        place = 'in ' + target if target else 'everywhere'
        if target is None:
            entry = self.switches.saved.get(name, {})
            already = entry.get('all') == on and not entry.get('channels')
        else:
            already = self.switches.name_on(name, target) == on
        if already:
            return "{}: '{}' is already {}d {}".format(nick, args[0], verb, place)
        self.switches.set(name, on, target)
        return "{}: '{}' {}d {}".format(nick, args[0], verb, place)

    def enabled_for(self, handler, target):
        channel = target if is_channel(target) else None
        return self.switches.is_on((handler.name, handler.plugin), channel)

    async def run_as(self, who, command, arg='', channel=None, capture=True):
        """Run a command as someone, with their access, the way a recipe step or a tool
        call does, and say how it went.

        Args:
            who: a Source, the person it runs as. Their bans, grants and denies apply.
            command: the command's name, or how it's typed, like 'roll' or '!roll'.
            arg: the text after the command.
            channel: the channel it runs in, or None for a private message.
            capture: True to return what the command says where it runs, instead of
                sending it. Captured lines never go to the output queue. A private reply or
                a notice still goes to whoever it's for.

        Returns a RunResult.
        """
        handler = self.registry.find(command) or self.registry.commands.get(command)
        if handler is None or handler.kind != 'command':
            return RunResult('unknown', (), "there's no command called {}".format(command))
        if self.ignores(who):
            return RunResult('refused', (), '{} is banned from the bot, or not logged in where '
                                            'require_account is on'.format(who.nick))
        label = handler.label(self.cmd_prefix)
        target = channel if channel and is_channel(channel) else self.transport.nick
        event = Event('message', who, target, '{} {}'.format(label, arg).strip(), 'privmsg')
        lines = [] if capture else None
        status, error = await self.run_handler(handler, event, label, arg, capture=lines)
        return RunResult(status, tuple(lines or ()), error)

    async def run_handler(self, handler, event, trigger, arg, addressed=False, capture=None):
        """Run one command or handler for a message or event, and send what it answers.

        Returns how it went, as ('ran' | 'refused' | 'busy' | 'failed', error or None).
        capture is a list to put what it says in, instead of sending it.
        """
        command = handler.kind == 'command'
        label = handler.label(self.cmd_prefix)
        if not self.enabled_for(handler, event.target):
            return 'refused', '{} is switched off here'.format(label)
        ctx = Context(self, event, plugin=handler.plugin, addressed=addressed,
                      command=handler.name if command else None, arg=arg, capture=capture)
        # commands and what listens to people's messages go by access, timers and server events
        # don't, since nobody in particular starts them
        checked = command or handler.kind == 'listener' or handler.event in ('message', 'notice')
        if checked and event.source:
            channel = event.target if is_channel(event.target) else None
            if not self.access.allows(event.source, handler, channel):
                self.logger.debug('{} has no access to {}'.format(ctx.nick, label))
                if command and handler.denied_msg:
                    ctx.out('privmsg', ctx.channel, handler.denied_msg)
                return 'refused', "{} doesn't have access to {}".format(ctx.nick, label)
        kwargs = {}
        if command and handler.native:
            try:
                kwargs = commands.parse(handler.params, arg)
            except commands.UsageError as e:
                problem = 'usage: {} ({})'.format(commands.usage(handler.name, handler.params), e)
                if capture is None:
                    ctx.out('privmsg', ctx.channel, problem)
                return 'failed', problem
        key = None
        if command:
            # one run at a time per person, so spamming a slow command can't pile them up
            key = (self.transport.casefold(ctx.nick), handler.name)
            if key in self.running:
                self.logger.debug('{} is still running for {}, ignoring'.format(label, ctx.nick))
                return 'busy', '{} is still running for {}'.format(label, ctx.nick)
            self.running.add(key)
        self.logger.debug('running {} {}'.format(handler.kind, label))
        timeout = handler.timeout or self.handler_timeout
        try:
            async with asyncio.timeout(timeout):
                if handler.native:
                    output = await handler.func(ctx, **kwargs)
                    ctx.store.save_if_changed()
                else:
                    # 1.x plugins are plain functions, so each runs on a thread of its own
                    worker = self.workers.get(handler.plugin)
                    if worker is None:
                        worker = self.workers[handler.plugin] = compat.Worker(handler.plugin)
                    output = await asyncio.wrap_future(worker.submit(
                        compat.run, handler, ctx, trigger, self.nick_list(event), self.ops))
        except TimeoutError:
            self.logger.error('{} took longer than {} seconds, giving up waiting for it'.format(
                label if command else handler.kind + ' ' + label, timeout))
            self.say_error(handler, ctx)
            return 'failed', '{} took longer than {} seconds'.format(label, timeout)
        except Exception as e:
            self.logger.exception('issue with {} {}'.format(handler.kind, label))
            self.say_error(handler, ctx)
            return 'failed', '{}: {}'.format(type(e).__name__, e)
        finally:
            self.running.discard(key)
        if handler.native:
            if output is not None:
                self.logger.warning('{} returned something, 2.0 handlers answer with ctx.reply() '
                                    'and the rest, so it was ignored'.format(label))
        elif output:
            self.logger.debug(f'sending output: {output.msg}')
            self.process_output(ctx.channel, output, ctx)
        return 'ran', None

    def nick_list(self, event):
        # msg.nick_list for 1.x plugins: the channel's nicks, or the sender's own
        if is_channel(event.target or ''):
            return [m.nick for m in self.transport.members(event.target)]
        return [event.source.nick] if event.source else []

    def say_error(self, handler, ctx):
        # failures stay out of chat unless the plugin's author chose words for it
        if handler.error_msg and ctx.channel:
            ctx.out('privmsg', ctx.channel, handler.error_msg)

    def process_output(self, chan, output, ctx=None):
        # what a 1.x command returned. Through its ctx, so run_as can capture it
        if not output.msg:
            return
        kinds = {plugin.OutputType.Message: 'privmsg', plugin.OutputType.Action: 'action'}
        if output.msg_type not in kinds:
            self.logger.warning("Unsupported output type '{}'".format(output.msg_type))
            return
        for msg in output.msg:
            self.logger.debug('output {}: {}'.format(output.msg_type.value, msg))
            if ctx is None:
                self.send_message(kinds[output.msg_type], chan, msg)
            else:
                ctx.out(kinds[output.msg_type], chan, msg)


class TwitchBot(Bot):
    """A bot for Twitch chat, connecting to irc.chat.twitch.tv over ssl.

    Args:
        nickname: the bot account's name.
        channel: the channel to join, like '#channel'.
        token: the bot account's oauth token, without 'oauth:'.
        **kwargs: any of the options TwitchBot takes, see
            https://archangelic.github.io/pinhook/latest/twitch/
    """
    server = 'irc.chat.twitch.tv'
    # Bot's options, less the ones for an IRC server's TLS and logging in
    options = Bot.options - {
        'ssl_required', 'ssl_verify', 'ssl_certfile', 'ssl_keyfile', 'server_pass',
        'ns_pass', 'nickserv', 'sasl_account', 'sasl_password', 'sasl_mechanism',
        'require_account',
    }

    def __init__(self, nickname, channel, token, **kwargs):
        self.token = token
        self.channel = channel
        kwargs.setdefault('port', 6697)
        super().__init__([channel], nickname, self.server, **kwargs)
        # everyone on Twitch is logged in
        self.require_account = False

    def make_transport(self, server, nickname):
        # always over TLS, checking the certificate, since the token is a password
        return TwitchTransport(
            self.logger, server, self.port, nickname, password='oauth:' + self.token,
            ssl_context=ssl.create_default_context(), bot_mode=self.bot_mode)
