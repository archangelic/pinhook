"""Drive a real Bot with raw IRC lines, through its IRC transport.

Tests written with Wire only see the IRC lines going in and out, so they don't
depend on how the transport is written. Changing how it reads and writes the
network means changing this file, and the same tests then check the new version.
"""
import asyncio
import os
import re

import irctokens

from pinhook import bot as pinhook_bot
from pinhook.testing import Driver

SERVER = 'irc.example.net'


class FakeWriter:
    # stands in for the connection to the server, and keeps what the bot sends

    def __init__(self):
        self.outbox = b''

    def write(self, data):
        self.outbox += data

    async def drain(self):
        pass

    def close(self):
        pass


class Sent:
    """One line the bot sent, split into its parts."""

    def __init__(self, line):
        self.line = line
        params = line.split(' :', 1)
        words = params[0].split(' ')
        self.command = self.raw_command = words[0]
        self.params = self.raw_params = words[1:] + params[1:]
        self.target = self.params[0] if self.params else None
        self.text = self.params[-1] if len(self.params) > 1 else None
        if self.text and self.text.startswith('\x01ACTION ') and self.command == 'PRIVMSG':
            self.command, self.text = 'ACTION', self.text[len('\x01ACTION '):].rstrip('\x01')

    def __repr__(self):
        return 'Sent({!r})'.format(self.line)


class Wire:
    """A Bot connected to a fake server. Feed it server lines, see the lines it sends.

    Args:
        tmp_path: a folder for the bot's plugins, logs and data.
        plugins: plugin files to write, as {name: code}.
        isolated: put the log and ban files in tmp_path, unless given.
        bot: drive this already-made bot instead of making one.
        **options: options for the Bot.
    """

    def __init__(self, tmp_path=None, nickname='pinbot', channels=('#test',), plugins=None,
                 isolated=True, bot=None, cls=pinhook_bot.Bot, **options):
        if bot is None:
            plugin_dir = os.path.join(str(tmp_path), 'plugins')
            os.makedirs(plugin_dir, exist_ok=True)
            for name, code in (plugins or {}).items():
                with open(os.path.join(plugin_dir, name + '.py'), 'w') as f:
                    f.write(code)
            options.setdefault('plugin_dir', plugin_dir)
            if isolated:
                options.setdefault('log_file', os.path.join(str(tmp_path), 'bot.log'))
                options.setdefault('ban_file', os.path.join(str(tmp_path), 'bans.json'))
                options.setdefault('data_dir', os.path.join(str(tmp_path), 'data'))
            bot = cls(list(channels), nickname, SERVER, **options)
        self.bot = bot
        self.nickname = nickname
        self.driver = Driver(bot)
        self.writer = FakeWriter()
        self.joined = set()
        self._read = 0

    @property
    def pauses(self):
        """The waits for the rate limit the bot would have taken, in seconds."""
        return self.driver.pauses

    # connecting

    def connect(self):
        """Connect to the fake server. The bot sends its first lines, like CAP LS."""
        self.bot.transport.begin(self.writer)
        return self.sent()

    def connect_fails(self, error):
        """Try to connect, with the network failing with error. Returns what was raised."""
        async def open_connection(*args, **kwargs):
            raise error
        self.bot.transport.open_connection = open_connection
        try:
            asyncio.run(self.bot.transport.open())
        except Exception as e:
            return e

    def welcome(self, isupport='CHANTYPES=#'):
        """Finish registering: the server welcomes the bot and it joins its channels."""
        self.receive(':{} 001 {} :Welcome'.format(SERVER, self.nickname),
                     ':{} 005 {} {} :are supported by this server'.format(
                         SERVER, self.nickname, isupport))
        for channel in self.bot.chanlist:
            self.join(self.nickname, channel.split()[0])
        return self.sent()

    def ready(self, **kwargs):
        """Connect and register, ignoring what the bot sends while it does."""
        self.connect()
        self.welcome(**kwargs)
        return self

    # the server talking to the bot

    def receive(self, *lines):
        """Send the bot raw lines from the server."""
        for line in lines:
            self.bot.transport.handle(irctokens.tokenise(line))
        self.driver.run()

    def join(self, nick, channel='#test', user=None, host='example.com'):
        self.receive(':{}!{}@{} JOIN {}'.format(nick, user or nick, host, channel))
        self.joined.add((nick.lower(), channel.lower()))

    def message(self, nick, text, target='#test', user=None, host='example.com',
                account=None, action=False):
        """Someone sends a message. Returns every line the bot sent back."""
        if target.startswith('#') and (nick.lower(), target.lower()) not in self.joined:
            self.join(nick, target, user, host)
        self.sent()
        tags = '@account={} '.format(account) if account else ''
        if action:
            text = '\x01ACTION {}\x01'.format(text)
        self.receive('{}:{}!{}@{} PRIVMSG {} :{}'.format(
            tags, nick, user or nick, host, target, text))
        return self.sent()

    def say(self, text, nick='tester', channel='#test', **who):
        """Someone says text in a channel. Returns the text of the bot's replies there."""
        return [s.text for s in self.message(nick, text, channel, **who)
                if s.command in ('PRIVMSG', 'ACTION') and s.target == channel]

    # what the bot sent

    def sent(self):
        """Lines the bot has sent since the last call, as Sent objects."""
        lines = self.writer.outbox.decode('utf-8', 'replace').split('\r\n')
        new, self._read = lines[self._read:-1], len(lines) - 1
        return [Sent(line) for line in new]


def lines(sent):
    """Sent lines as 'COMMAND param param', for asserts.

    Where the : goes is up to the transport (CAP REQ account-tag and
    CAP REQ :account-tag mean the same), so it's left out.
    """
    return [' '.join([s.raw_command] + s.raw_params) for s in sent]


def texts(sent, command='PRIVMSG', target=None):
    """The text of sent messages, optionally only one command or target."""
    return [s.text for s in sent if s.command == command and (target is None or s.target == target)]


def b64_login(sent):
    """The SASL login the bot sent, put back together from its AUTHENTICATE lines."""
    import base64
    pieces = [s.params[0] for s in sent if s.command == 'AUTHENTICATE']
    payload = ''.join(p for p in pieces if p not in ('PLAIN', '+'))
    return base64.b64decode(payload).decode()


def matches(pattern, sent):
    return [s for s in sent if re.search(pattern, s.line)]
