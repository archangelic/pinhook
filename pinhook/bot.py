import imp
import os
import ssl
import time
import pinhook.plugin

import irc.bot


irc.client.ServerConnection.buffer_class.errors = 'replace'


class Message:
    def __init__(self, channel, nick, botnick, ops, cmd=None, arg=None, text=None, nick_list=None):
        self.channel = channel
        self.nick = nick
        self.nick_list = nick_list
        self.botnick = botnick
        self.ops = ops
        if cmd:
            self.cmd = cmd
        if arg:
            self.arg = arg
        if text:
            self.text = text
        if not (cmd or text):
            print('Please pass Message a command or text!')


class Bot(irc.bot.SingleServerIRCBot):
    def __init__(self, channels, nickname, server, **kwargs):
        self.set_kwargs(**kwargs)
        if self.ssl_required:
            factory = irc.connection.Factory(wrapper=ssl.wrap_socket)
            irc.bot.SingleServerIRCBot.__init__(self, [(server, self.port)], nickname, nickname, connect_factory=factory)
        else:
            irc.bot.SingleServerIRCBot.__init__(self, [(server, self.port)], nickname, nickname)
        self.chanlist = channels
        self.bot_nick = nickname
        self.load_plugins()

    def set_kwargs(self, **kwargs):
        kwarguments = {
            'port': 6667,
            'ops': [],
            'plugin_dir': 'plugins',
            'ssl_required': False,
            'ns_pass': None,
            'nickserv': 'NickServ',
        }
        for k, v in kwargs.items():
            setattr(self, k, v)
        for a in kwarguments:
            if a not in kwargs:
                setattr(self, a, kwarguments[a])

    def load_plugins(self):
        # clear plugin list to ensure no old plugins remain
        pinhook.plugin.clear_plugins()
        # ensure plugin folder exists
        if not os.path.exists(self.plugin_dir):
            os.makedirs(self.plugin_dir)
        # load all plugins
        plugins = []
        for m in os.listdir(self.plugin_dir):
            if m.endswith('.py'):
                try:
                    name = m[:-3]
                    fp, pathname, description = imp.find_module(name, [self.plugin_dir])
                    p = imp.load_module(name, fp, pathname, description)
                    p.pinhook
                    plugins.append(p)
                except Exception as e:
                    print(e)
        # gather all commands and listeners
        self.cmds = {}
        self.lstnrs = {}
        for plugin in plugins:
            for cmd in plugin.pinhook.plugin.cmds:
                self.cmds[cmd['cmd']] = cmd['func']
            for lstnr in plugin.pinhook.plugin.lstnrs:
                self.lstnrs[lstnr['lstn']] = lstnr['func']

    def on_welcome(self, c, e):
        if self.ns_pass:
            c.privmsg(self.nickserv, 'identify {}'.format(self.ns_pass))
        for channel in self.chanlist:
            c.join(channel)

    def on_pubmsg(self, c, e):
        self.process_command(c, e)

    def on_privmsg(self, c, e):
        self.process_command(c, e)

    def process_command(self, c, e):
        nick = e.source.nick
        text = e.arguments[0]
        if e.target == self.bot_nick:
            chan = nick
        else:
            chan = e.target
        cmd = text.split(' ')[0]
        if len(text.split(' ')) > 1:
            arg = ''.join([i + ' ' for i in text.split(' ')[1:]]).strip()
        else:
            arg = ''
        output = None
        if cmd == '!join' and nick in self.ops:
            c.join(arg)
            c.privmsg(chan, '{}: joined {}'.format(nick, arg))
        elif cmd == '!quit' and nick in self.ops:
            c.quit("See y'all later!")
            quit()
        elif cmd == '!help':
            helplist = sorted([i for i in self.cmds])
            msg = ', '.join(helplist)
            c.privmsg(chan, 'Available commands: {}'.format(msg))
        elif cmd == '!reload' and nick in self.ops:
            self.load_plugins()
            c.privmsg(chan, 'Plugins reloaded')
        elif cmd in self.cmds:
            try:
                output = self.cmds[cmd](Message(
                    channel=chan,
                    cmd=cmd,
                    nick_list=list(self.channels[chan].users()),
                    nick=nick,
                    arg=arg,
                    botnick=self.bot_nick,
                    ops=self.ops
                ))
                if output:
                    self.process_output(c, chan, output)
            except Exception as e:
                print(e)
        else:
            for lstnr in self.lstnrs:
                try:
                    output = self.lstnrs[lstnr](Message(
                        channel=chan,
                        text=text,
                        nick_list=list(self.channels[chan].users()),
                        nick=nick,
                        botnick=self.bot_nick,
                        ops=self.ops
                    ))
                    if output:
                        self.process_output(c, chan, output)
                except Exception as e:
                    print(e)

    def process_output(self, c, chan, output):
        for msg in output.msg:
            if output.msg_type == 'message':
                c.privmsg(chan, msg)
            elif output.msg_type == 'action':
                c.action(chan, msg)
            time.sleep(.5)
