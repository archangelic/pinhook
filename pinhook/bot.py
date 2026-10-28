from collections import OrderedDict
from datetime import datetime, timezone
import difflib
import functools
import logging
import socket
import ssl
import sys
import time
import warnings

from . import bans
from . import log
from . import plugin

import irc.bot


irc.client.ServerConnection.buffer_class.errors = 'replace'


class Bot(irc.bot.SingleServerIRCBot):
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
        'ban_file', 'require_account',
    }
    log_levels = {
        'critical': logging.CRITICAL,
        'error': logging.ERROR,
        'warning': logging.WARNING,
        'warn': logging.WARNING,
        'info': logging.INFO,
        'debug': logging.DEBUG,
    }
    # set once the server agrees to tag messages with the sender's account
    account_tag = False
    _negotiating_caps = False

    def __init__(self, channels, nickname, server, **kwargs):
        self.port = kwargs.get('port', 6667)
        self.ops = kwargs.get('ops', [])
        self.plugin_dir = kwargs.get('plugin_dir', 'plugins')
        self.ssl_required = kwargs.get('ssl_required', False)
        self.ssl_verify = kwargs.get('ssl_verify', True)
        self.ns_pass = kwargs.get('ns_pass', None)
        self.nickserv = kwargs.get('nickserv', 'NickServ')
        self.log_level = kwargs.get('log_level', 'info')
        self.log_file = kwargs.get('log_file', None)
        self.server_pass = kwargs.get('server_pass', None)
        self.cmd_prefix = kwargs.get('cmd_prefix', '!')
        self.use_prefix_for_plugins = kwargs.get('use_prefix_for_plugins', False)
        self.disable_help = kwargs.get('disable_help', False)
        self.bot_mode = kwargs.get('bot_mode', True)
        self.require_account = kwargs.get('require_account', False)
        factory = self.ssl_factory(server) if self.ssl_required else irc.connection.Factory()
        irc.bot.SingleServerIRCBot.__init__(self, [(server, self.port, self.server_pass)], nickname, nickname, connect_factory=self.cap_factory(factory))
        self.chanlist = channels
        self.bot_nick = nickname
        self.start_logging()
        self.warn_unknown_options(kwargs)
        self.setup_bans(nickname, kwargs)
        self.internal_commands = {self.cmd_prefix + k: v for k,v in self.internal_commands.items()}
        plugin.load_plugins(self.plugin_dir, use_prefix=self.use_prefix_for_plugins, cmd_prefix=self.cmd_prefix, logger=self.logger)

    class Message:
        def __init__(self, bot, channel, nick, user, botnick, ops, logger, action, privmsg, notice, msg_type, cmd=None, arg=None, text=None, nick_list=None, is_op=False, account=None):
            self._bot = bot
            self.datetime = datetime.now(timezone.utc)
            self.timestamp = self.datetime.timestamp()
            self.channel = channel
            self.nick = nick
            self.user = user
            self.nick_list = nick_list
            self.botnick = botnick
            self.ops = ops
            self.is_op = is_op
            self.account = account
            self.is_private = not irc.client.is_channel(channel)
            self.logger = logger
            self._action = action
            self.privmsg = privmsg
            self._notice = notice
            self.msg_type = msg_type
            if cmd:
                self.cmd = cmd
                self.arg = arg
            if text != None:
                self.text = text
            if cmd is None and text is None:
                raise TypeError('missing cmd or text parameter')

        @property
        def bot(self):
            self._bot.warn_deprecated('msg.bot', 'msg.bot is deprecated and will be read only in 2.0, use msg.reply(), msg.send() and msg.botnick instead')
            return self._bot

        def reply(self, text):
            """Send text where the message came from: the channel, or the sender if it was private."""
            self._bot.process_output(self._bot.connection, self.channel, plugin.message(text))

        def send(self, target, text):
            """Send text to another channel or nick."""
            self._bot.process_output(self._bot.connection, target, plugin.message(text))

        def action(self, *args):
            """action(text) replies with a /me, action(target, text) sends one somewhere else."""
            target, text = self._target_and_text(args, self.channel)
            self._bot.process_output(self._bot.connection, target, plugin.action(text))

        def notice(self, *args):
            """notice(text) sends the sender a notice, notice(target, text) sends one to anyone."""
            target, text = self._target_and_text(args, self.nick)
            for line in plugin.message(text).msg:
                self._notice(target, line)

        @staticmethod
        def _target_and_text(args, default_target):
            if len(args) == 1:
                return default_target, args[0]
            if len(args) == 2:
                return args
            raise TypeError('expected (text) or (target, text), got {} arguments'.format(len(args)))

    def connect(self, *args, **kwargs):
        # the irc library quietly retries failed connections, so say why it failed
        try:
            super().connect(*args, **kwargs)
        except irc.client.ServerConnectionError as e:
            self.logger.error(self.connection_error_message(args[0], args[1], e))
            raise

    def connection_error_message(self, host, port, error):
        cause = error.__cause__
        start = "couldn't connect to {}:{}: ".format(host, port)
        end = ' (will keep retrying every 1-5 minutes)'
        if isinstance(cause, ssl.SSLCertVerificationError):
            start += "the server's ssl certificate failed verification ({}). ".format(cause.verify_message.rstrip('.'))
            # openssl codes for hostname and ip address mismatch, and expired
            if cause.verify_code in (62, 64):
                return start + 'Set server to the name the certificate was issued for, not an IP address or alias' + end
            if cause.verify_code == 10:
                return start + 'This needs fixing on the server' + end
            return start + 'If this server uses a self-signed certificate, set ssl_verify to false' + end
        if isinstance(cause, ssl.SSLError):
            return (start + 'ssl handshake failed ({}). '
                    "Check {} is the server's ssl port, usually 6697".format(getattr(cause, 'reason', None) or cause, port) + end)
        if isinstance(cause, socket.gaierror):
            return start + 'server name not found, check the server setting' + end
        if isinstance(cause, ConnectionRefusedError):
            return start + 'connection refused, check the server and port settings' + end
        return start + str(cause or error) + end

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

    def setup_bans(self, nickname, kwargs):
        self.ban_file = kwargs.get('ban_file', '{}.bans.json'.format(nickname)) or None
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
        bans.save(self.ban_file, [b for b in self.banned_users if not self.nick_in(b, self.config_bans)])

    def remember(self, nick, user, host, account):
        key = irc.strings.lower(nick)
        self.seen[key] = (nick, user, host, account)
        self.seen.move_to_end(key)
        while len(self.seen) > 1000:
            self.seen.popitem(last=False)

    def ban_entry(self, target):
        # a nick on its own is easy to change, so ban their account if they're
        # logged in, or their user and host if not
        if bans.is_account(target) or bans.is_mask(target):
            return target, target
        seen = self.seen.get(irc.strings.lower(target))
        if not seen:
            return target, "{} (nick only, they haven't spoken since the bot started)".format(target)
        nick, user, host, account = seen
        if account:
            return '$a:' + account, '{} (account {})'.format(target, account)
        entry = '*!*{}@{}'.format((user or '').lstrip('~'), host)
        return entry, '{} ({})'.format(target, entry)

    def remove_bans(self, target):
        # the entry itself, plus anything banning the person last seen as target
        seen = self.seen.get(irc.strings.lower(target))
        removed = [b for b in self.banned_users if self.nick_in(b, [target]) or (seen and bans.matches(b, *seen))]
        self.banned_users = [b for b in self.banned_users if b not in removed]
        return removed

    @staticmethod
    def account_from_tags(tags):
        for tag in tags or []:
            if tag['key'] == 'account' and tag['value'] not in (None, '*'):
                return tag['value']
        return None

    def cap_factory(self, factory):
        # ask what the server supports before the irc library sends NICK and USER,
        # some servers (like libera) only allow it before registration
        def connect(address):
            sock = factory(address)
            sock.send(b'CAP LS 302\r\n')
            self._negotiating_caps = True
            self._server_caps = set()
            self.account_tag = False
            return sock
        return connect

    def on_cap(self, c, e):
        if not self._negotiating_caps:
            return
        subcommand = e.arguments[0]
        if subcommand == 'LS':
            self._server_caps.update(cap.split('=')[0] for cap in e.arguments[-1].split())
            # a * means the list carries on in another line
            if len(e.arguments) > 2 and e.arguments[1] == '*':
                return
            if 'account-tag' in self._server_caps:
                c.cap('REQ', 'account-tag')
                return
        elif subcommand in ('ACK', 'NAK'):
            self.account_tag = subcommand == 'ACK' and 'account-tag' in e.arguments[-1].split()
        else:
            return
        # registration waits until we say we're done
        self._negotiating_caps = False
        c.cap('END')

    def ssl_factory(self, server):
        context = ssl.create_default_context()
        if not self.ssl_verify:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        wrapper = functools.partial(context.wrap_socket, server_hostname=server)
        return irc.connection.Factory(wrapper=wrapper)

    @staticmethod
    def nick_in(nick, nicks):
        # irc nicks are case insensitive, so Troll and troll are the same person
        nick = irc.strings.lower(nick)
        return any(irc.strings.lower(n) == nick for n in nicks)

    def start_logging(self):
        self.logger = log.get_bot_logger(self.bot_nick)
        log_level = str(self.log_level).lower()
        if log_level == 'off':
            self.logger.disabled = True
            return
        if log_level not in self.log_levels:
            raise ValueError("log_level must be one of: off, {}".format(', '.join(self.log_levels)))
        self.logger.disabled = False
        if self.log_file:
            log.set_log_file(self.log_file, self.logger)
        else:
            log.set_log_file('{}.log'.format(self.bot_nick), self.logger)
        self.logger.setLevel(self.log_levels[log_level])
        self.logger.info('Logging started!')

    def on_welcome(self, c, e):
        if self.require_account and not self.account_tag:
            self.logger.error("require_account is on but this server doesn't tell the bot who is logged in (account-tag), so the bot will ignore everyone")
        if self.ns_pass:
            self.logger.info('identifying with nickserv')
            c.privmsg(self.nickserv, 'identify {}'.format(self.ns_pass))
        for channel in self.chanlist:
            self.logger.info('joining channel {}'.format(channel.split()[0]))
            c.join(*channel.split())

    def on_nicknameinuse(self, c, e):
        # servers call us * until we're registered, after that a failed
        # nick change should just keep the nick we already have
        if e.target != '*':
            return
        new_nick = e.arguments[0] + '_'
        self.logger.warning('nickname {} in use, trying {}'.format(e.arguments[0], new_nick))
        c.nick(new_nick)

    def on_featurelist(self, c, e):
        # servers that support bot mode advertise its letter as BOT=<mode>
        # https://ircv3.net/specs/extensions/bot-mode
        if not self.bot_mode:
            return
        for feature in e.arguments:
            if feature.startswith('BOT='):
                mode = feature[len('BOT='):]
                self.logger.info('setting bot mode +{}'.format(mode))
                c.mode(c.get_nickname(), '+' + mode)

    def on_pubmsg(self, c, e):
        self.process_event(c, e)

    def on_privmsg(self, c, e):
        self.process_event(c, e)

    def on_action(self, c, e):
        self.process_event(c, e)

    def pause(self, seconds):
        # flood protection between lines of output
        time.sleep(seconds)

    def call_help(self, nick, op):
        cmds = {k:v.help_text for k,v in plugin.cmds.items() if not (plugin.cmds[k].ops or plugin.cmds[k].hide) }
        cmds.update({self.cmd_prefix + 'help': 'returns this output to private message'})
        if op:
            cmds.update({k:v.help_text for k,v in plugin.cmds.items() if plugin.cmds[k].ops})
            cmds.update({k:v for k,v in self.internal_commands.items()})
        helpout = OrderedDict(sorted(cmds.items()))
        for h in helpout:
            self.connection.privmsg(nick, '{} -- {}'.format(h, helpout[h]))
            self.pause(.1)
        self.connection.privmsg(nick, 'List of listeners: {}'.format(', '.join([l for l in plugin.lstnrs])))
        return None

    def call_internal_commands(self, channel, nick, cmd, text, arg, c, op=None):
        if not cmd.startswith(self.cmd_prefix):
            return None
        else:
            cmd = cmd[len(self.cmd_prefix):]
        output = None
        if op is None:
            op = self.nick_in(nick, self.ops)
        if cmd == 'join' and op:
            try:
                c.join(*arg.split())
                self.logger.info('joining {} per request of {}'.format(arg, nick))
                output = plugin.message('{}: joined {}'.format(nick, arg.split()[0]))
            except:
                self.logger.exception('issue with join command: {}join #channel <channel key>'.format(self.cmd_prefix))
        elif cmd == 'quit' and op:
            self.logger.info('quitting per request of {}'.format(nick))
            if not arg:
                arg = "See y'all later!"
            c.quit(arg)
            sys.exit()
        elif cmd == 'help' and not self.disable_help:
            self.call_help(nick, op)
        elif cmd == 'reload' and op:
            self.logger.info('reloading plugins per request of {}'.format(nick))
            plugin.load_plugins(self.plugin_dir, use_prefix=self.use_prefix_for_plugins, cmd_prefix=self.cmd_prefix, logger=self.logger)
            output = plugin.message('Plugins reloaded')
        elif cmd == 'enable' and op:
            if arg in plugin.plugins:
                if plugin.plugins[arg].enabled:
                    output = plugin.message("{}: '{}' already enabled".format(nick, arg))
                else:
                    plugin.plugins[arg].enable()
                    output = plugin.message("{}: '{}' enabled!".format(nick, arg))
            else:
                output = plugin.message("{}: '{}' not found".format(nick, arg))
        elif cmd == 'disable' and op:
            if arg in plugin.plugins:
                if not plugin.plugins[arg].enabled:
                    output = plugin.message("{}: '{}' already disabled".format(nick, arg))
                else:
                    plugin.plugins[arg].disable()
                    output = plugin.message("{}: '{}' disabled!".format(nick, arg))
            else:
                output = plugin.message("{}: '{}' not found".format(nick, arg))
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
                    reply += " ({} is in the config file, so it'll be back after a restart)".format(', '.join(from_config))
                output = plugin.message(reply)
        elif cmd == 'banlist' and op:
            output = plugin.message('currently banned: {}'.format(', '.join(self.banned_users) or 'nobody'))
        return output

    def check_output(self, output):
        if output and not isinstance(output, plugin.Output):
            raise TypeError('plugins must return message() or action(), got {}'.format(type(output).__name__))
        return output

    def call_plugins(self, privmsg, action, notice, chan, cmd, text, nick_list, nick, user, arg, msg_type, botnick, op=None, account=None):
        output = None
        if op is None:
            op = self.nick_in(nick, self.ops)
        if cmd in plugin.cmds:
            try:
                if plugin.cmds[cmd].ops and not op:
                    if plugin.cmds[cmd].ops_msg:
                        output =  plugin.message(plugin.cmds[cmd].ops_msg)
                elif plugin.cmds[cmd].enabled:
                    self.logger.debug('executing {}'.format(cmd))
                    output = self.check_output(plugin.cmds[cmd].run(self.Message(
                        bot=self,
                        channel=chan,
                        cmd=cmd,
                        nick_list=nick_list,
                        nick=nick,
                        user=user,
                        arg=arg,
                        privmsg=privmsg,
                        action=action,
                        notice=notice,
                        botnick=botnick,
                        ops=self.ops,
                        logger=self.logger,
                        msg_type=msg_type,
                        is_op=op,
                        account=account
                    )))
            except Exception:
                self.logger.exception('issue with command {}'.format(cmd))
        else:
            for lstnr in plugin.lstnrs:
                if plugin.lstnrs[lstnr].enabled:
                    try:
                        self.logger.debug('whispering to listener: {}'.format(lstnr))
                        listen_output = self.check_output(plugin.lstnrs[lstnr].run(self.Message(
                            bot=self,
                            channel=chan,
                            text=text,
                            nick_list=nick_list,
                            nick=nick,
                            user=user,
                            privmsg=privmsg,
                            action=action,
                            notice=notice,
                            botnick=botnick,
                            ops=self.ops,
                            logger=self.logger,
                            msg_type=msg_type,
                            is_op=op,
                            account=account
                        )))
                        if listen_output:
                            output = listen_output
                    except Exception:
                        self.logger.exception('issue with listener {}'.format(lstnr))
        if output:
            self.logger.debug(f'returning output: {output.msg}')
        return output

    def process_event(self, c, e):
        nick = e.source.nick
        user = e.source.user
        host = e.source.host
        account = self.account_from_tags(e.tags)
        self.remember(nick, user, host, account)
        if bans.matches_any(self.banned_users, nick, user, host, account):
            self.logger.debug('ignoring banned user {}'.format(nick))
            return
        botnick = c.get_nickname()
        if irc.strings.lower(nick) == irc.strings.lower(botnick):
            return
        if self.require_account and not account:
            self.logger.debug('ignoring {}, not logged in to an account'.format(nick))
            return
        op = bans.matches_any(self.ops, nick, user, host, account)
        if e.arguments:
            text = e.arguments[0]
        else:
            text = ''
        if e.type == 'privmsg' or e.type == 'pubmsg':
            msg_type = 'message'
        else:
            msg_type = e.type
        if not irc.client.is_channel(e.target):
            chan = nick
            nick_list = [nick]
        else:
            chan = e.target
            nick_list = list(self.channels[chan].users())
        if e.type == 'action':
            cmd = ''
        else:
            cmd = text.split(' ')[0]
        self.logger.debug(
            'Message info: channel: {}, nick: {}, cmd: {}, text: {}'.format(chan, nick, cmd, text)
        )
        if len(text.split(' ')) > 1:
            arg = ''.join([i + ' ' for i in text.split(' ')[1:]]).strip()
        else:
            arg = ''
        output = self.call_internal_commands(chan, nick, cmd, text, arg, c, op=op)
        if not output:
            plugin_info = {
                'chan': chan,
                'cmd': cmd,
                'text': text,
                'nick_list': nick_list,
                'nick': nick,
                'user': user,
                'arg': arg,
                'privmsg': c.privmsg,
                'action': c.action,
                'notice': c.notice,
                'msg_type': msg_type,
                'botnick': botnick,
                'op': op,
                'account': account
            }
            output = self.call_plugins(**plugin_info)
        if output:
            self.logger.debug(f'sending output: {output.msg}')
            self.process_output(c, chan, output)

    def process_output(self, c, chan, output):
        if not output.msg:
            return
        for msg in output.msg:
            if output.msg_type == plugin.OutputType.Message:
                self.logger.debug('output message: {}'.format(msg))
                try:
                    c.privmsg(chan, msg)
                except irc.client.MessageTooLong:
                    self.logger.error('output message too long: {}'.format(msg))
                    break
            elif output.msg_type == plugin.OutputType.Action:
                self.logger.debug('output action: {}'.format(msg))
                try:
                    c.action(chan, msg)
                except irc.client.MessageTooLong:
                    self.logger.error('output message too long: {}'.format(msg))
                    break
            else:
                self.logger.warning("Unsupported output type '{}'".format(output.msg_type))
            self.pause(.5)


class TwitchBot(Bot):
    server = 'irc.chat.twitch.tv'
    options = {
        'port', 'ops', 'plugin_dir', 'log_level', 'log_file', 'cmd_prefix',
        'use_prefix_for_plugins', 'disable_help', 'banned_users', 'bot_mode',
        'ban_file',
    }

    def __init__(self, nickname, channel, token, **kwargs):
        self.port = kwargs.get('port', 6697)
        self.ssl_verify = True
        self.ops = kwargs.get('ops', [])
        self.plugin_dir = kwargs.get('plugin_dir', 'plugins')
        self.log_level = kwargs.get('log_level', 'info')
        self.log_file = kwargs.get('log_file', None)
        self.server_pass = kwargs.get('server_pass', None)
        self.cmd_prefix = kwargs.get('cmd_prefix', '!')
        self.use_prefix_for_plugins = kwargs.get('use_prefix_for_plugins', False)
        self.disable_help = kwargs.get('disable_help', False)
        self.bot_mode = kwargs.get('bot_mode', True)
        self.require_account = False
        self.bot_nick = nickname
        self.start_logging()
        self.warn_unknown_options(kwargs)
        self.setup_bans(nickname, kwargs)
        self.channel = channel
        self.logger.info('Joining Twitch Server')
        # always use tls, the oauth token is a password
        irc.bot.SingleServerIRCBot.__init__(self, [(self.server, self.port, 'oauth:'+token)], nickname, nickname, connect_factory=self.ssl_factory(self.server))
        self.internal_commands = {self.cmd_prefix + k: v for k,v in self.internal_commands.items()}
        plugin.load_plugins(self.plugin_dir, use_prefix=self.use_prefix_for_plugins, cmd_prefix=self.cmd_prefix, logger=self.logger)

    def on_welcome(self, c, e):
        self.logger.info('requesting permissions')
        c.cap('REQ', ':twitch.tv/membership')
        c.cap('REQ', ':twitch.tv/tags')
        c.cap('REQ', ':twitch.tv/commands')
        self.logger.info('Joining channel ' + self.channel)
        c.join(self.channel)
