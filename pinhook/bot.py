import imp
import os

import irc.bot

irc.client.ServerConnection.buffer_class.errors = 'replace'


class Bot(irc.bot.SingleServerIRCBot):
    def __init__(self, channels, nickname, server, port=6667, ops=[], plugin_dir='plugins'):
        irc.bot.SingleServerIRCBot.__init__(self, [(server, port)], nickname, nickname)
        self.chanlist = channels
        self.bot_nick = nickname
        self.ops = ops

        # load all plugins
        plugins = []
        for m in os.listdir(plugin_dir):
            if m.endswith('.py'):
                name = m[:-3]
                fp, pathname, description = imp.find_module(name, [plugin_dir])
                plugins.append(imp.load_module(name, fp, pathname, description))

        # gather all commands
        self.cmds = {}
        for plugin in plugins:
            for cmd in plugin.pinhook.plugin.cmds:
                self.cmds[cmd['cmd']] = cmd['func']

    def on_welcome(self, c, e):
        for channel in self.chanlist:
            c.join(channel)

    def on_pubmsg(self, c, e):
        self.process_command(c, e, e.arguments[0])

    def on_privmsg(self, c, e):
        self.process_command(c, e, e.arguments[0])

    def process_command(self, c, e, text):
        nick = e.source.nick
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
        elif cmd in self.cmds:
            output = self.cmds[cmd](nick=nick, arg=arg)

        if output:
            if output.msg_type == 'message':
                c.privmsg(chan, output.msg)
            elif output.msg_type == 'action':
                c.action(chan, output.msg)

