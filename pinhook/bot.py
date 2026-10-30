"""The bots: Bot for IRC servers and TwitchBot for Twitch chat."""
import asyncio
from collections import OrderedDict
import difflib
import logging
import os
import shlex
import signal
import ssl
import time
import warnings

from . import bans
from . import compat
from . import log
from . import plugin
from .context import Context
from .output import OutputQueue
from .registry import Registry, Switches
from .store import PluginConfig, Store
from .transport.base import Outgoing, Transport, is_channel
from .transport.irc import IrcTransport, TwitchTransport


class Bot:
    """An IRC bot that loads plugins from a folder and runs them.

    Args:
        channels: channels to join once connected.
        nickname: the bot's nick.
        server: the server to connect to.
        **kwargs: any of the bot's options, like port, ssl_required or ops. See
            https://archangelic.github.io/pinhook/latest/options/

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
        'banlist': 'list current bans'
    }
    # keyword options Bot understands, subclasses can add their own
    options = {
        'port', 'ops', 'plugin_dir', 'ssl_required', 'ssl_verify', 'ns_pass',
        'nickserv', 'log_level', 'log_file', 'server_pass', 'cmd_prefix',
        'use_prefix_for_plugins', 'disable_help', 'banned_users', 'bot_mode',
        'ban_file', 'require_account', 'bot_dir', 'data_dir', 'plugin_config',
        'sasl_account', 'sasl_password', 'address_by_nick', 'plugin_channels',
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
        self.server = server
        self.chanlist = channels
        self.bot_nick = nickname
        self.start_logging()
        self.transport = self.make_transport(server, nickname)
        self.setup_core()
        self.warn_unknown_options(kwargs)
        self.setup_bans(nickname, kwargs)
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
            close = difflib.get_close_matches(key, self.options, n=1)
            hint = ", did you mean '{}'?".format(close[0]) if close else ''
            self.logger.warning("unknown option '{}' ignored{}".format(key, hint))

    def setup_paths(self, nickname, kwargs):
        # with bot_dir set, everything lives in one folder: plugins/, data/ and logs/.
        # without it, files go where they did in 1.11
        self.bot_dir = os.path.expanduser(kwargs['bot_dir']) if kwargs.get('bot_dir') else None
        if self.bot_dir:
            log_file = os.path.join('logs', '{}.log'.format(nickname))
            ban_file = os.path.join('data', '{}.bans.json'.format(nickname))
        else:
            log_file = '{}.log'.format(nickname)
            ban_file = '{}.bans.json'.format(nickname)
        self.plugin_dir = self.path(kwargs.get('plugin_dir', 'plugins'))
        self.data_dir = self.path(kwargs.get('data_dir', 'data'))
        self.log_file = self.path(kwargs.get('log_file') or log_file)
        ban_file = kwargs.get('ban_file', ban_file)
        self.ban_file = self.path(ban_file) if ban_file else None
        self.stores = {}
        self.plugin_config = dict(kwargs.get('plugin_config') or {})
        self.plugin_channels = dict(kwargs.get('plugin_channels') or {})

    def path(self, path):
        """Where a path from the options really is: relative ones are inside bot_dir, if set."""
        path = os.path.expanduser(path)
        if self.bot_dir and not os.path.isabs(path):
            return os.path.join(self.bot_dir, path)
        return path

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
        except Exception as e:
            self.logger.error(
                "couldn't read plugin_config from {} again, keeping the old settings: {}".format(
                    self.config_file, e))
            return (", but {} has a problem so plugin_config wasn't changed, "
                    "see the log".format(name))
        self.plugin_config = dict(config.get('plugin_config') or {})
        return ' (and plugin_config from {})'.format(name)

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
        self.registry.load(self.plugin_dir)
        self.check_plugin_config()

    def switches_path(self):
        # where !enable and !disable are saved
        return os.path.join(self.data_dir, '{}.plugins.json'.format(self.bot_nick))

    def check_plugin_config(self):
        # a section for a plugin that isn't loaded is probably a typo
        loaded = set(self.registry.plugins)
        for name in sorted(set(self.plugin_config) - loaded - {'shared'}):
            close = difflib.get_close_matches(name, loaded, n=1)
            hint = ", did you mean '{}'?".format(close[0]) if close else ''
            self.logger.warning("plugin_config has settings for '{}', but there's no plugin "
                                "called that{}".format(name, hint))

    def open_store(self, name):
        return Store(name, os.path.join(self.data_dir, name + '.json'))

    def setup_bans(self, nickname, kwargs):
        self.config_bans = list(kwargs.get('banned_users', []))
        self.banned_users = list(self.config_bans)
        saved = bans.load(self.ban_file)
        for entry in saved:
            if not self.nick_in(entry, self.banned_users):
                self.banned_users.append(entry)
        if saved:
            self.logger.info('loaded {} bans from {}'.format(len(saved), self.ban_file))
        # recent nicks and who they are, so !ban troll can ban their account or host
        self.seen = OrderedDict()

    def save_bans(self):
        # bans from the config stay in the config, the file keeps the ones made with !ban
        saved = [b for b in self.banned_users if not self.nick_in(b, self.config_bans)]
        bans.save(self.ban_file, saved)

    def remember(self, nick, user, host, account):
        key = self.transport.casefold(nick)
        self.seen[key] = (nick, user, host, account)
        self.seen.move_to_end(key)
        while len(self.seen) > 1000:
            self.seen.popitem(last=False)

    def ban_entry(self, target):
        # a nick on its own is easy to change, so ban their account if they're
        # logged in, or their user and host if not
        if bans.is_account(target) or bans.is_mask(target):
            return target, target
        seen = self.seen.get(self.transport.casefold(target))
        if not seen:
            description = "{} (nick only, they haven't spoken since the bot started)"
            return target, description.format(target)
        nick, user, host, account = seen
        if account:
            return '$a:' + account, '{} (account {})'.format(target, account)
        entry = '*!*{}@{}'.format((user or '').lstrip('~'), host)
        return entry, '{} ({})'.format(target, entry)

    def remove_bans(self, target):
        # the entry itself, plus anything banning the person last seen as target
        fold = self.transport.casefold
        seen = self.seen.get(fold(target))
        removed = [b for b in self.banned_users
                   if self.nick_in(b, [target]) or (seen and bans.matches(b, *seen, fold=fold))]
        self.banned_users = [b for b in self.banned_users if b not in removed]
        return removed

    def ssl_context(self):
        """The ssl settings the bot connects with: checks certificates unless ssl_verify is off."""
        context = ssl.create_default_context()
        if not self.ssl_verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        return context

    def is_op(self, source):
        """True if the sender of a message is one of the bot's ops."""
        return bans.matches_any(self.ops, source.nick, source.user, source.host, source.account,
                                fold=self.transport.casefold)

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
        self.logger.disabled = False
        log.set_log_file(self.log_file, self.logger)
        self.logger.setLevel(self.log_levels[log_level])
        self.logger.info('Logging started!')

    # the network, through the transport

    def make_transport(self, server, nickname):
        return IrcTransport(
            self.logger, server, self.port, nickname, password=self.server_pass,
            ssl_context=self.ssl_context() if self.ssl_required else None,
            sasl_account=self.sasl_account, sasl_password=self.sasl_password,
            nickserv=self.nickserv, ns_pass=self.ns_pass, bot_mode=self.bot_mode)

    def setup_core(self):
        # set once the bot is running, plugins in worker threads send through it
        self.loop = None
        # messages being handled, and the (nick, command) pairs still running
        self.handlers = set()
        self.running = set()
        self.stopping = False
        self.quit_reason = ''
        self.quitting = asyncio.Event()
        self.output = OutputQueue(self.transport.send, self.transport.limits, self.logger,
                                  clock=lambda: self.clock(), sleep=lambda s: self.pause(s))

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
            self.connected()
        elif event.type == 'disconnected':
            # answers to what was asked before the drop would be out of date
            dropped = self.output.clear()
            if dropped:
                self.logger.warning('disconnected, dropping {} messages that were waiting to be '
                                    'sent'.format(dropped))
        elif event.type == 'message' and not self.stopping:
            task = asyncio.get_running_loop().create_task(self.process_event(event))
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

    def send_message(self, kind, target, text):
        """Queue a message to send. Safe to call from a plugin's thread."""
        self.in_loop(self.output.put, Outgoing(kind, target, text))

    def send_text(self, kind, target, text):
        """Queue text to send, a message per line. text can be a list of lines too."""
        if isinstance(text, (list, tuple)):
            lines = [line for item in text for line in str(item).splitlines()]
        else:
            lines = str(text).splitlines()
        for line in lines:
            self.send_message(kind, target, line)

    def call_help(self, nick, op):
        prefix = self.cmd_prefix
        commands = [h for h in self.registry.handlers() if h.kind == 'command']
        cmds = {h.label(prefix): h.help_text for h in commands if not (h.ops or h.hide)}
        cmds.update({prefix + 'help': 'returns this output to private message'})
        if op:
            cmds.update({h.label(prefix): h.help_text for h in commands if h.ops})
            cmds.update({prefix + k: v for k, v in self.internal_commands.items()})
        helpout = OrderedDict(sorted(cmds.items()))
        for h in helpout:
            self.send_message('privmsg', nick, '{} -- {}'.format(h, helpout[h]))
        listeners = ', '.join(self.registry.listeners)
        self.send_message('privmsg', nick, 'List of listeners: {}'.format(listeners))
        return None

    def call_internal_commands(self, channel, nick, cmd, arg, op=None):
        # cmd is the command's name, without the prefix
        output = None
        if op is None:
            op = self.nick_in(nick, self.ops)
        if cmd == 'join' and op:
            try:
                self.transport.join(*arg.split())
                self.logger.info('joining {} per request of {}'.format(arg, nick))
                output = plugin.message('{}: joined {}'.format(nick, arg.split()[0]))
            except Exception:
                self.logger.exception('issue with join command: {}join #channel <channel key>'
                                      .format(self.cmd_prefix))
        elif cmd == 'quit' and op:
            self.logger.info('quitting per request of {}'.format(nick))
            if not arg:
                arg = "See y'all later!"
            self.quit(arg)
        elif cmd == 'help' and not self.disable_help:
            self.call_help(nick, op)
        elif cmd == 'reload' and op:
            self.logger.info('reloading plugins per request of {}'.format(nick))
            config_note = self.reload_plugin_config()
            self.registry.load(self.plugin_dir)
            self.check_plugin_config()
            output = plugin.message('Plugins reloaded' + config_note)
        elif cmd in ('enable', 'disable') and op:
            output = self.switch(cmd == 'enable', channel, nick, arg)
        elif cmd in ('op', 'deop', 'ban', 'unban') and op and not arg.split():
            output = plugin.message('{}: usage: {}{} <nick>'.format(nick, self.cmd_prefix, cmd))
        elif cmd == 'op' and op:
            for o in arg.split():
                if not self.nick_in(o, self.ops):
                    self.ops.append(o)
            output = plugin.message('{}: {} added as op'.format(nick, arg))
        elif cmd == 'deop' and op:
            for o in arg.split():
                self.ops = [i for i in self.ops if not self.nick_in(i, [o])]
            output = plugin.message('{}: {} removed as op'.format(nick, arg))
        elif cmd == 'ops' and op:
            output = plugin.message('current ops: {}'.format(', '.join(self.ops)))
        elif cmd == 'ban' and op:
            banned = []
            for target in arg.split():
                entry, description = self.ban_entry(target)
                if not self.nick_in(entry, self.banned_users):
                    self.banned_users.append(entry)
                banned.append(description)
            self.save_bans()
            output = plugin.message('{}: banned {}'.format(nick, ', '.join(banned)))
        elif cmd == 'unban' and op:
            removed = []
            for target in arg.split():
                removed += self.remove_bans(target)
            self.save_bans()
            if not removed:
                output = plugin.message('{}: no ban found for {}'.format(nick, arg))
            else:
                reply = '{}: removed ban on {}'.format(nick, ', '.join(removed))
                from_config = [b for b in removed if self.nick_in(b, self.config_bans)]
                if from_config:
                    reply += (" ({} is in the config file, so it'll be back after a restart)"
                              .format(', '.join(from_config)))
                output = plugin.message(reply)
        elif cmd == 'banlist' and op:
            banned = ', '.join(self.banned_users) or 'nobody'
            output = plugin.message('currently banned: {}'.format(banned))
        return output

    async def process_event(self, event):
        nick = event.source.nick
        user = event.source.user
        host = event.source.host
        account = event.source.account
        self.remember(nick, user, host, account)
        fold = self.transport.casefold
        if bans.matches_any(self.banned_users, nick, user, host, account, fold=fold):
            self.logger.debug('ignoring banned user {}'.format(nick))
            return
        botnick = self.transport.nick
        if self.transport.casefold(nick) == self.transport.casefold(botnick):
            return
        if self.require_account and not account:
            self.logger.debug('ignoring {}, not logged in to an account'.format(nick))
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
            output = self.call_internal_commands(chan, nick, name, arg, op=op)
            if output and not self.stopping:
                self.process_output(chan, output)
                return
        if self.stopping:
            return
        nick_list = self.transport.members(chan) if is_channel(event.target) else [nick]
        handler = self.registry.find(word, addressed) if word else None
        if handler:
            await self.run_handler(handler, event, word, arg, nick_list, addressed)
            return
        # each listener answers on its own, so a slow or broken one doesn't hold up the rest
        await asyncio.gather(*(self.run_handler(h, event, None, '', nick_list, addressed)
                               for h in self.registry.listeners.values()))

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
            return plugin.message('{}: usage: {}{} <plugin> [all | #channel]'.format(
                nick, self.cmd_prefix, verb))
        name = self.canonical_name(args[0])
        if name is None:
            return plugin.message("{}: '{}' not found".format(nick, args[0]))
        where = args[1] if len(args) == 2 else channel
        target = where if is_channel(where) else None
        place = 'in ' + target if target else 'everywhere'
        if target is None:
            entry = self.switches.saved.get(name, {})
            already = entry.get('all') == on and not entry.get('channels')
        else:
            already = self.switches.name_on(name, target) == on
        if already:
            return plugin.message("{}: '{}' is already {}d {}".format(nick, args[0], verb, place))
        self.switches.set(name, on, target)
        return plugin.message("{}: '{}' {}d {}".format(nick, args[0], verb, place))

    def enabled_for(self, handler, target):
        channel = target if is_channel(target) else None
        return self.switches.is_on((handler.name, handler.plugin), channel)

    async def run_handler(self, handler, event, trigger, arg, nick_list, addressed=False):
        """Run one command or listener for a message, and send what it returns."""
        command = handler.kind == 'command'
        if not self.enabled_for(handler, event.target):
            return
        ctx = Context(self, event, plugin=handler.plugin, addressed=addressed,
                      command=handler.name if command else None, arg=arg)
        label = handler.label(self.cmd_prefix)
        if command and handler.ops and not ctx.is_op:
            if handler.ops_msg:
                self.send_text('privmsg', ctx.channel, handler.ops_msg)
            return
        key = None
        if command:
            # one run at a time per person, so spamming a slow command can't pile them up
            key = (self.transport.casefold(ctx.nick), handler.name)
            if key in self.running:
                self.logger.debug('{} is still running for {}, ignoring'.format(label, ctx.nick))
                return
            self.running.add(key)
        self.logger.debug('running {} {}'.format(handler.kind, label))
        try:
            # 1.x plugins are plain functions, so they run in a worker thread
            async with asyncio.timeout(self.handler_timeout):
                output = await asyncio.to_thread(compat.run, handler, ctx, trigger, nick_list,
                                                 self.ops)
        except TimeoutError:
            self.logger.error('{} took longer than {} seconds, giving up waiting for it'.format(
                label if command else 'listener ' + label, self.handler_timeout))
            return
        except Exception:
            self.logger.exception('issue with {} {}'.format(handler.kind, label))
            return
        finally:
            self.running.discard(key)
        if output:
            self.logger.debug(f'sending output: {output.msg}')
            self.process_output(ctx.channel, output)

    def process_output(self, chan, output):
        if not output.msg:
            return
        kinds = {plugin.OutputType.Message: 'privmsg', plugin.OutputType.Action: 'action'}
        if output.msg_type not in kinds:
            self.logger.warning("Unsupported output type '{}'".format(output.msg_type))
            return
        for msg in output.msg:
            self.logger.debug('output {}: {}'.format(output.msg_type.value, msg))
            self.send_message(kinds[output.msg_type], chan, msg)


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
    options = {
        'port', 'ops', 'plugin_dir', 'log_level', 'log_file', 'cmd_prefix',
        'use_prefix_for_plugins', 'disable_help', 'banned_users', 'bot_mode',
        'ban_file', 'bot_dir', 'data_dir', 'plugin_config', 'address_by_nick',
        'plugin_channels',
    }

    def __init__(self, nickname, channel, token, **kwargs):
        self.port = kwargs.get('port', 6697)
        self.ssl_verify = True
        self.ops = kwargs.get('ops', [])
        self.setup_paths(nickname, kwargs)
        self.log_level = kwargs.get('log_level', 'info')
        self.server_pass = kwargs.get('server_pass', None)
        self.cmd_prefix = kwargs.get('cmd_prefix', '!')
        self.use_prefix_for_plugins = kwargs.get('use_prefix_for_plugins')
        self.address_by_nick = kwargs.get('address_by_nick', True)
        self.disable_help = kwargs.get('disable_help', False)
        self.bot_mode = kwargs.get('bot_mode', True)
        self.require_account = False
        self.bot_nick = nickname
        self.start_logging()
        self.channel = channel
        self.chanlist = [channel]
        self.logger.info('Joining Twitch Server')
        # always use tls, the oauth token is a password
        self.transport = TwitchTransport(
            self.logger, self.server, self.port, nickname, password='oauth:' + token,
            ssl_context=self.ssl_context(), bot_mode=self.bot_mode)
        self.setup_core()
        self.warn_unknown_options(kwargs)
        self.setup_bans(nickname, kwargs)
        self.setup_plugins()
