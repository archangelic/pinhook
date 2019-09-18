from collections import OrderedDict
from datetime import datetime, timezone
import imp
import logging
import os
import ssl
import time
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
        self.server_pass = kwargs.get('server_pass', None)
        self.cmd_prefix = kwargs.get('cmd_prefix', '!')
        self.use_prefix_for_plugins = kwargs.get('use_prefix_for_plugins', False)
        if self.ssl_required:
            factory = irc.connection.Factory(wrapper=ssl.wrap_socket)
            irc.bot.SingleServerIRCBot.__init__(self, [(server, self.port, self.server_pass)], nickname, nickname, connect_factory=factory)
        else:
            irc.bot.SingleServerIRCBot.__init__(self, [(server, self.port, self.server_pass)], nickname, nickname)
        self.chanlist = channels
        self.bot_nick = nickname
        self.start_logging(self.log_level)
        self.output_message = plugin.message
        self.output_action = plugin.action
        self.internal_commands = {
            'join': 'join a channel',
            'quit': 'force the bot to quit',
            'reload': 'force bot to reload all plugins',
            'enable': 'enable a plugin',
            'disable': 'disable a plugin'
        }
        self.internal_commands = {self.cmd_prefix + k: v for k,v in self.internal_commands.items()}
        self.load_plugins()

    class Message:
        def __init__(self, bot, channel, nick, botnick, ops, logger, action, privmsg, notice, cmd=None, arg=None, text=None, nick_list=None):
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
            if cmd:
                self.cmd = cmd
                self.arg = arg
            if text:
                self.text = text
            if not (cmd or text):
                raise TypeError('missing cmd or text parameter')

    def start_logging(self, level):
        if level == 'error':
            level = logging.ERROR
        elif level == 'warning':
            level = logging.WARNING
        elif level == 'info':
            level = logging.INFO
        elif level == 'debug':
            level = logging.DEBUG
        self.logger = logging.getLogger(self.bot_nick)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(module)s - %(message)s')
        # Set console logger
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        # Set file logger
        fh = logging.FileHandler('{}.log'.format(self.bot_nick))
        fh.setFormatter(formatter)
        # Set levels
        if level != "off":
            self.logger.setLevel(level)
            ch.setLevel(level)
            fh.setLevel(level)
        # Add handlers
        self.logger.addHandler(ch)
        self.logger.addHandler(fh)
        self.logger.info('Logging started!')

    def load_plugins(self):
        # clear plugin list to ensure no old plugins remain
        self.logger.info('clearing plugin cache')
        plugin.clear_plugins()
        # ensure plugin folder exists
        self.logger.info('checking plugin directory')
        if not os.path.exists(self.plugin_dir):
            self.logger.info('plugin directory {} not found, creating'.format(self.plugin_dir))
            os.makedirs(self.plugin_dir)
        # load all plugins
        for m in os.listdir(self.plugin_dir):
            if m.endswith('.py'):
                try:
                    name = m[:-3]
                    self.logger.info('loading plugin {}'.format(name))
                    fp, pathname, description = imp.find_module(name, [self.plugin_dir])
                    imp.load_module(name, fp, pathname, description)
                except Exception:
                    self.logger.exception('could not load plugin')
        # gather all commands and listeners
        if self.use_prefix_for_plugins: # use prefixes if needed
            plugin.cmds = {self.cmd_prefix + k: v for k,v in plugin.cmds.items()}
        for cmd in plugin.cmds:
            self.logger.debug('adding command {}'.format(cmd))
        for lstnr in plugin.lstnrs:
            self.logger.debug('adding listener {}'.format(lstnr))

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
            time.sleep(.5)
        self.connection.privmsg(nick, 'List of listeners: {}'.format(', '.join([l for l in plugin.lstnrs])))
        return None

    def call_internal_commands(self, channel, nick, cmd, text, arg, c):
        output = None
        if nick in self.ops:
            op = True
        else:
            op = False
        if cmd == self.cmd_prefix + 'join' and op:
            c.join(*arg.split())
            self.logger.info('joining {} per request of {}'.format(arg, nick))
            output = self.output_message('{}: joined {}'.format(nick, arg.split()[0]))
        elif cmd == self.cmd_prefix + 'quit' and op:
            self.logger.info('quitting per request of {}'.format(nick))
            c.quit("See y'all later!")
            quit()
        elif cmd == self.cmd_prefix + 'help':
            self.call_help(nick, op)
        elif cmd == self.cmd_prefix + 'reload' and op:
            self.logger.info('reloading plugins per request of {}'.format(nick))
            self.load_plugins()
            output = self.output_message('Plugins reloaded')
        elif cmd == self.cmd_prefix + 'enable' and op:
            if arg in plugin.plugins:
                if plugin.plugins[arg].enabled:
                    output = self.output_message("{}: '{}' already enabled".format(nick, arg))
                else:
                    plugin.plugins[arg].enable()
                    output = self.output_message("{}: '{}' enabled!".format(nick, arg))
            else:
                output = self.output_message("{}: '{}' not found".format(nick, arg))
        elif cmd == self.cmd_prefix + 'disable' and op:
            if arg in plugin.plugins:
                if not plugin.plugins[arg].enabled:
                    output = self.output_message("{}: '{}' already disabled".format(nick, arg))
                else:
                    plugin.plugins[arg].disable()
                    output = self.output_message("{}: '{}' disabled!".format(nick, arg))
        return output

    def call_plugins(self, privmsg, action, notice, chan, cmd, text, nick_list, nick, arg):
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
                        logger=self.logger
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
                            logger=self.logger
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
        self.start_logging(log_level)
        self.channel = channel
        self.plugin_dir = plugin_dir
        self.ops = ops
        server = 'irc.twitch.tv'
        port = 6667
        self.logger.info('Joining Twitch Server')
        irc.bot.SingleServerIRCBot.__init__(self, [(server, port, 'oauth:'+token)], nickname, nickname)
        self.load_plugins()

    def on_welcome(self, c, e):
        self.logger.info('requesting permissions')
        c.cap('REQ', ':twitch.tv/membership')
        c.cap('REQ', ':twitch.tv/tags')
        c.cap('REQ', ':twitch.tv/commands')
        self.logger.info('Joining channel ' + self.channel)
        c.join(self.channel)

