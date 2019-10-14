from collections import OrderedDict
from datetime import datetime, timezone
import logging
import ssl
import time

from . import log
from . import plugin

import irc.bot


irc.client.ServerConnection.buffer_class.errors = 'replace'


class Bot(irc.bot.SingleServerIRCBot):
    def __init__(self, channels, nickname, server, **kwargs):
        self.port = kwargs.get('port', 6667)
        self.ops = kwargs.get('ops', [])
        self.plugin_dir = kwargs.get('plugin_dir', 'plugins')
        self.ssl_required = kwargs.get('ssl_required', False)
        self.ns_pass = kwargs.get('ns_pass', None)
        self.nickserv = kwargs.get('nickserv', 'NickServ')
        self.log_level = kwargs.get('log_level', 'info')
        self.log_file = kwargs.get('log_file', None)
        self.server_pass = kwargs.get('server_pass', None)
        self.cmd_prefix = kwargs.get('cmd_prefix', '!')
        self.use_prefix_for_plugins = kwargs.get('use_prefix_for_plugins', False)
        self.disable_help = kwargs.get('disable_help', False)
        self.banned_users = kwargs.get('banned_users', [])
        if self.ssl_required:
            factory = irc.connection.Factory(wrapper=ssl.wrap_socket)
            irc.bot.SingleServerIRCBot.__init__(self, [(server, self.port, self.server_pass)], nickname, nickname, connect_factory=factory)
        else:
            irc.bot.SingleServerIRCBot.__init__(self, [(server, self.port, self.server_pass)], nickname, nickname)
        self.chanlist = channels
        self.bot_nick = nickname
        self.start_logging()
        self.output_message = plugin.message
        self.output_action = plugin.action
        self.internal_commands = {
            'join': 'join a channel',
            'quit': 'force the bot to quit',
            'reload': 'force bot to reload all plugins',
            'enable': 'enable a plugin',
            'disable': 'disable a plugin',
            'op': 'add a user as bot operator',
            'deop': 'remove a user as bot operator',
            'ops': 'list all ops',
            'ban': 'ban a user from using the bot',
            'unban': 'remove bot ban for user',
            'banlist': 'currently banned nicks'
        }
        self.internal_commands = {self.cmd_prefix + k: v for k,v in self.internal_commands.items()}
        plugin.load_plugins(self.plugin_dir, use_prefix=self.use_prefix_for_plugins, cmd_prefix=self.cmd_prefix)

    class Message:
        def __init__(self, bot, channel, nick, botnick, ops, logger, action, privmsg, notice, msg_type, cmd=None, arg=None, text=None, nick_list=None):
            self.bot = bot
            self.datetime = datetime.now(timezone.utc)
            self.timestamp = self.datetime.timestamp()
            self.channel = channel
            self.nick = nick
            self.nick_list = nick_list
            self.botnick = botnick
            self.ops = ops
            self.logger = logger
            self.action = action
            self.privmsg = privmsg
            self.notice = notice
            self.msg_type = msg_type
            if cmd:
                self.cmd = cmd
                self.arg = arg
            if text:
                self.text = text
            if not (cmd or text):
                raise TypeError('missing cmd or text parameter')

    def start_logging(self):
        self.logger = log.logger
        if self.log_file:
            log.set_log_file(self.log_file)
        else:
            log.set_log_file('{}.log'.format(self.bot_nick))
        if self.log_level == 'error':
            level = logging.ERROR
        elif self.log_level == 'warning':
            level = logging.WARNING
        elif self.log_level == 'info':
            level = logging.INFO
        elif self.log_level == 'debug':
            level = logging.DEBUG
        # Set levels
        if self.log_level != "off":
            self.logger.setLevel(level)
        self.logger.info('Logging started!')

    def on_welcome(self, c, e):
        if self.ns_pass:
            self.logger.info('identifying with nickserv')
            c.privmsg(self.nickserv, 'identify {}'.format(self.ns_pass))
        for channel in self.chanlist:
            self.logger.info('joining channel {}'.format(channel.split()[0]))
            c.join(*channel.split())

    def on_pubmsg(self, c, e):
        self.process_event(c, e)

    def on_privmsg(self, c, e):
        self.process_event(c, e)

    def on_action(self, c, e):
        self.process_event(c, e)

    def call_help(self, nick, op):
        cmds = {k:v.help_text for k,v in plugin.cmds.items() if not plugin.cmds[k].ops}
        cmds.update({self.cmd_prefix + 'help': 'returns this output to private message'})
        if op:
            cmds.update({k:v.help_text for k,v in plugin.cmds.items() if plugin.cmds[k].ops})
            cmds.update({k:v for k,v in self.internal_commands.items()})
        helpout = OrderedDict(sorted(cmds.items()))
        for h in helpout:
            self.connection.privmsg(nick, '{} -- {}'.format(h, helpout[h]))
            time.sleep(.1)
        self.connection.privmsg(nick, 'List of listeners: {}'.format(', '.join([l for l in plugin.lstnrs])))
        return None

    def call_internal_commands(self, channel, nick, cmd, text, arg, c):
        if not cmd.startswith(self.cmd_prefix):
            return None
        else:
            cmd = cmd[len(self.cmd_prefix):]
        output = None
        if nick in self.ops:
            op = True
        else:
            op = False
        if cmd == 'join' and op:
            try:
                c.join(*arg.split())
                self.logger.info('joining {} per request of {}'.format(arg, nick))
                output = self.output_message('{}: joined {}'.format(nick, arg.split()[0]))
            except:
                self.logger.exception('issue with join command: {}join #channel <channel key>'.format(self.cmd_prefix))
        elif cmd == 'quit' and op:
            self.logger.info('quitting per request of {}'.format(nick))
            if not arg:
                arg = "See y'all later!"
            c.quit(arg)
            quit()
        elif cmd == 'help' and not self.disable_help:
            self.call_help(nick, op)
        elif cmd == 'reload' and op:
            self.logger.info('reloading plugins per request of {}'.format(nick))
            plugin.load_plugins(self.plugin_dir, use_prefix=self.use_prefix_for_plugins, cmd_prefix=self.cmd_prefix)
            output = self.output_message('Plugins reloaded')
        elif cmd == 'enable' and op:
            if arg in plugin.plugins:
                if plugin.plugins[arg].enabled:
                    output = self.output_message("{}: '{}' already enabled".format(nick, arg))
                else:
                    plugin.plugins[arg].enable()
                    output = self.output_message("{}: '{}' enabled!".format(nick, arg))
            else:
                output = self.output_message("{}: '{}' not found".format(nick, arg))
        elif cmd == 'disable' and op:
            if arg in plugin.plugins:
                if not plugin.plugins[arg].enabled:
                    output = self.output_message("{}: '{}' already disabled".format(nick, arg))
                else:
                    plugin.plugins[arg].disable()
                    output = self.output_message("{}: '{}' disabled!".format(nick, arg))
        elif cmd == 'op' and op:
            for o in arg.split(' '):
                self.ops.append(o)
            output = self.output_message('{}: {} added as op'.format(nick, arg))
        elif cmd == 'deop' and op:
            for o in arg.split(' '):
                self.ops = [i for i in self.ops if i != o]
            output = self.output_message('{}: {} removed as op'.format(nick, arg))
        elif cmd == 'ops' and op:
            output = self.output_message('current ops: {}'.format(', '.join(self.ops)))
        elif cmd == 'ban' and op:
            for o in arg.split(' '):
                self.banned_users.append(o)
            output = self.output_message('{}: banned {}'.format(nick, arg))
        elif cmd == 'unban' and op:
            for o in arg.split(' '):
                self.banned_users = [i for i in self.banned_users if i != o]
            output = self.output_message('{}: removed ban for {}'.format(nick, arg))
        elif cmd == 'banlist':
            output = self.output_message('currently banned: {}'.format(', '.join(self.banned_users)))
        return output

    def call_plugins(self, privmsg, action, notice, chan, cmd, text, nick_list, nick, arg, msg_type):
        output = None
        if cmd in plugin.cmds:
            try:
                if plugin.cmds[cmd].ops and nick not in self.ops:
                    if plugin.cmds[cmd].ops_msg:
                        output =  self.output_message(plugin.cmds[cmd].ops_msg)
                elif plugin.cmds[cmd].enabled:
                    self.logger.debug('executing {}'.format(cmd))
                    output = plugin.cmds[cmd].run(self.Message(
                        bot=self,
                        channel=chan,
                        cmd=cmd,
                        nick_list=nick_list,
                        nick=nick,
                        arg=arg,
                        privmsg=privmsg,
                        action=action,
                        notice=notice,
                        botnick=self.bot_nick,
                        ops=self.ops,
                        logger=self.logger,
                        msg_type=msg_type
                    ))
            except Exception:
                self.logger.exception('issue with command {}'.format(cmd))
        else:
            for lstnr in plugin.lstnrs:
                if plugin.lstnrs[lstnr].enabled:
                    try:
                        self.logger.debug('whispering to listener: {}'.format(lstnr))
                        listen_output = plugin.lstnrs[lstnr].run(self.Message(
                            bot=self,
                            channel=chan,
                            text=text,
                            nick_list=nick_list,
                            nick=nick,
                            privmsg=privmsg,
                            action=action,
                            notice=notice,
                            botnick=self.bot_nick,
                            ops=self.ops,
                            logger=self.logger,
                            msg_type=msg_type
                        ))
                        if listen_output:
                            output = listen_output
                    except Exception:
                        self.logger.exception('issue with listener {}'.format(lstnr))
        if output:
            self.logger.debug(f'returning output: {output.msg}')
        return output

    def process_event(self, c, e):
        nick = e.source.nick
        text = e.arguments[0]
        if e.type == 'privmsg' or e.type == 'pubmsg':
            msg_type = 'message'
        else:
            msg_type = e.type
        if e.target == self.bot_nick:
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
        output = self.call_internal_commands(chan, nick, cmd, text, arg, c)
        if not output:
            plugin_info = {
                'chan': chan,
                'cmd': cmd,
                'text': text,
                'nick_list': nick_list,
                'nick': nick,
                'arg': arg,
                'privmsg': c.privmsg,
                'action': c.action,
                'notice': c.notice,
                'msg_type': msg_type
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
            time.sleep(.5)


class TwitchBot(Bot):
    def __init__(self, nickname, channel, token, plugin_dir='plugins', log_level='info', ops=[]):
        self.bot_nick = nickname
        self.log_level = log_level
        self.start_logging()
        self.channel = channel
        self.plugin_dir = plugin_dir
        self.ops = ops
        server = 'irc.twitch.tv'
        port = 6667
        self.logger.info('Joining Twitch Server')
        irc.bot.SingleServerIRCBot.__init__(self, [(server, port, 'oauth:'+token)], nickname, nickname)
        plugin.load_plugins(self.plugin_dir)

    def on_welcome(self, c, e):
        self.logger.info('requesting permissions')
        c.cap('REQ', ':twitch.tv/membership')
        c.cap('REQ', ':twitch.tv/tags')
        c.cap('REQ', ':twitch.tv/commands')
        self.logger.info('Joining channel ' + self.channel)
        c.join(self.channel)

