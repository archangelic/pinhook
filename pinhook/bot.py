from datetime import datetime, timezone
import imp
import logging
import os
import ssl
import time
import pinhook.plugin

import irc.bot


irc.client.ServerConnection.buffer_class.errors = 'replace'


class Bot(irc.bot.SingleServerIRCBot):
    def __init__(self, channels, nickname, server, **kwargs):
        self.set_kwargs(**kwargs)
        if self.ssl_required:
            factory = irc.connection.Factory(wrapper=ssl.wrap_socket)
            irc.bot.SingleServerIRCBot.__init__(self, [(server, self.port, self.server_pass)], nickname, nickname, connect_factory=factory)
        else:
            irc.bot.SingleServerIRCBot.__init__(self, [(server, self.port, self.server_pass)], nickname, nickname)
        self.chanlist = channels
        self.bot_nick = nickname
        self.start_logging(self.log_level)
        self.output_message = pinhook.plugin.message
        self.output_action = pinhook.plugin.action
        self.load_plugins()

    class Message:
        def __init__(self, channel, nick, botnick, ops, logger, action, privmsg, notice, cmd=None, arg=None, text=None, nick_list=None):
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

    def set_kwargs(self, **kwargs):
        kwarguments = {
            'port': 6667,
            'ops': [],
            'plugin_dir': 'plugins',
            'ssl_required': False,
            'ns_pass': None,
            'nickserv': 'NickServ',
            'log_level': 'info',
            'server_pass': None,
        }
        for k, v in kwargs.items():
            setattr(self, k, v)
        for a in kwarguments:
            if a not in kwargs:
                setattr(self, a, kwarguments[a])

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
        pinhook.plugin.clear_plugins()
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
                except Exception as e:
                    self.logger.exception('could not load plugin')
        # gather all commands and listeners
        for cmd in pinhook.plugin.cmds:
            self.logger.debug('adding command {}'.format(cmd))
        for lstnr in pinhook.plugin.lstnrs:
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

    def call_help(self):
        helplist = sorted([i for i in pinhook.plugin.cmds])
        msg = ', '.join(helplist)
        return self.output_message('Available commands: {}'.format(msg))

    def call_internal_commands(self, channel, nick, cmd, text, arg, c):
        output = None
        if nick in self.ops:
            op = True
        else:
            op = False
        if cmd == '!join' and op:
            c.join(*arg.split())
            self.logger.info('joining {} per request of {}'.format(arg, nick))
            output = self.output_message('{}: joined {}'.format(nick, arg.split()[0]))
        elif cmd == '!quit' and op:
            self.logger.info('quitting per request of {}'.format(nick))
            c.quit("See y'all later!")
            quit()
        elif cmd == '!help':
            output = self.call_help()
        elif cmd == '!reload' and op:
            self.logger.info('reloading plugins per request of {}'.format(nick))
            self.load_plugins()
            output = self.output_message('Plugins reloaded')
        return output

    def call_plugins(self, privmsg, action, notice, chan, cmd, text, nick_list, nick, arg):
        output = None
        if cmd in pinhook.plugin.cmds:
            try:
                output = pinhook.plugin.cmds[cmd]['run'](self.Message(
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
            except Exception as e:
                self.logger.exception('issue with command {}'.format(cmd))
        else:
            for lstnr in pinhook.plugin.lstnrs:
                try:
                    output = pinhook.plugin.lstnrs[lstnr](self.Message(
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
                except Exception as e:
                    self.logger.exception('issue with listener {}'.format(lstnr))
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
            self.process_output(c, chan, output)

    def process_output(self, c, chan, output):
        for msg in output.msg:
            if len(msg.encode('UTF-8')) > 512:
                self.logger.error('output message too long: {}'.format(msg))
            elif output.msg_type == pinhook.plugin.OutputType.Message:
                self.logger.debug('output message: {}'.format(msg))
                c.privmsg(chan, msg)
            elif output.msg_type == pinhook.plugin.OutputType.Action:
                self.logger.debug('output action: {}'.format(msg))
                c.action(chan, msg)
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

