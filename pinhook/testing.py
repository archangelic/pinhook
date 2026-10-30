"""Test pinhook plugins without connecting to a server.

    from pinhook.testing import TestBot

    def test_roll():
        bot = TestBot(plugin_dir='plugins')
        assert bot.say('!roll 1d1') == ['1']
"""
import asyncio
from collections import namedtuple
import logging
import os
import weakref

from .bot import Bot
from .store import Store
from .transport.base import Event, Limits, Member, Source, Whois, casefold
from .transport.irc import text_room

# one thing the bot sent, kind is 'message', 'action' or 'notice'
Sent = namedtuple('Sent', ['kind', 'target', 'text'])


class PluginError(Exception):
    """A plugin raised an exception, or returned something it shouldn't."""


class FakeChannel:
    # the nicks in a channel, in the order they joined, their accounts, and their modes there

    def __init__(self):
        self.nicks = {}
        self.modes = {}

    def add_user(self, nick, account=None):
        if account or nick not in self.nicks:
            self.nicks[nick] = account

    def remove_user(self, nick):
        self.nicks.pop(nick, None)
        self.modes.pop(nick, None)

    def set_modes(self, changes):
        # what a mode change like ['+ov', 'mal', 'ana'] does to the members' +o and +v
        adding, args = True, list(changes[1:])
        for letter in changes[0] if changes else '':
            if letter in '+-':
                adding = letter == '+'
            elif letter in 'qaohv' and args:
                modes = self.modes.setdefault(args.pop(0), set())
                if adding:
                    modes.add(letter)
                else:
                    modes.discard(letter)

    def users(self):
        return list(self.nicks)

    def members(self):
        return [Member(nick, account=account, modes=frozenset(self.modes.get(nick, ())))
                for nick, account in self.nicks.items()]


class Driver:
    """Runs a bot's core a step at a time, so a test can wait for each answer.

    Time only moves when the output queue waits for its rate limit, and those
    waits are kept in pauses instead of taken.
    """

    def __init__(self, bot):
        self.bot = bot
        self.loop = asyncio.new_event_loop()
        weakref.finalize(self, self.loop.close)
        self.now = 0.0
        self.pauses = []
        bot.loop = self.loop
        bot.clock = lambda: self.now
        bot.pause = self.pause
        # timers were scheduled on the real clock, start them again on this one
        bot.reset_timers()

    async def pause(self, seconds):
        self.pauses.append(seconds)
        self.now += seconds

    def tick(self, seconds):
        """Move the clock on by seconds, run the timers that are due, and wait for them."""
        self.now += seconds
        self.loop.run_until_complete(self.fire_timers())

    async def fire_timers(self):
        self.bot.fire_due_timers()
        await self.settle(())

    def run(self, *events):
        """Handle events, and any the transport has waiting, until the bot has sent every
        answer. Raises SystemExit if the bot quit."""
        self.loop.run_until_complete(self.settle(events))
        if self.bot.stopping:
            self.loop.run_until_complete(self.bot.transport.close(self.bot.quit_reason))
            raise SystemExit

    async def settle(self, events):
        bot = self.bot
        for event in events:
            bot.dispatch(event)
        while True:
            while not bot.transport.queue.empty():
                event = bot.transport.queue.get_nowait()
                if event is not None:
                    bot.dispatch(event)
            running = {task for task in bot.handlers if not task.done()}
            if running:
                done, _ = await asyncio.wait(running, timeout=0.01)
                # a plugin waiting for the server to answer, which the test sends next
                if (not done and getattr(bot.transport, 'whois_waiting', None)
                        and bot.transport.queue.empty()):
                    return
            elif bot.output.targets:
                await bot.output.flush()
            else:
                # one more turn, for anything a plugin's thread handed over
                await asyncio.sleep(0)
                if bot.transport.queue.empty() and not bot.handlers and not bot.output.targets:
                    return


class FakeTransport:
    # stands in for the network and records what the bot sends
    name = 'fake'
    limits = Limits()

    def __init__(self, bot, nickname):
        self.bot = bot
        self.nick = nickname
        self.channels = {}
        self.queue = asyncio.Queue()
        self.closed = asyncio.Event()

    async def run(self):
        await self.closed.wait()

    async def events(self):
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event

    async def send(self, message):
        kind = 'message' if message.kind == 'privmsg' else message.kind
        self.bot.sent.append(Sent(kind, message.target, message.prefix + message.text))

    def join(self, channel, key=''):
        self.bot.add_channel(channel)

    def text_room(self, kind, target, prefix=''):
        # as much as a real server would take
        return text_room(self.nick, kind, target, prefix)

    def members(self, channel):
        return self.channels[channel].members() if channel in self.channels else []

    def joined(self):
        return list(self.channels)

    async def whois(self, nick, timeout=10):
        # what the fake network knows: the channels they're in and their account
        fold = self.casefold
        channels = [name for name, channel in self.channels.items()
                    if any(fold(n) == fold(nick) for n in channel.nicks)]
        if not channels:
            return None
        account = next((channel.nicks[n] for channel in self.channels.values()
                        for n in channel.nicks if fold(n) == fold(nick) and channel.nicks[n]),
                       None)
        return Whois(nick, user=nick, host='example.com', account=account,
                     channels=tuple(channels))

    def member_modes(self, channel, nick):
        if channel not in self.channels:
            return frozenset()
        return frozenset(self.channels[channel].modes.get(nick, ()))

    def supports(self, feature):
        return feature == 'account-tag'

    def casefold(self, name):
        return casefold(name)

    async def close(self, reason=''):
        self.bot.quit_message = reason
        self.closed.set()
        self.queue.put_nowait(None)


class _ErrorCatcher(logging.Handler):
    # plugin errors are logged by the bot, this keeps them so the test can raise them

    def __init__(self):
        super().__init__(logging.ERROR)
        self.records = []

    def emit(self, record):
        if record.exc_info:
            self.records.append(record)


class TestBot(Bot):
    """A Bot that never connects, for testing plugins.

    Plugins, ops, bans and the built-in commands all work as they do on a
    real server. What the bot sends is recorded in `sent` instead, and a
    plugin that raises an exception fails the test with a PluginError.
    """
    # tell pytest this isn't a test class, despite the name
    __test__ = False

    def __init__(self, plugin_dir='plugins', nickname='testbot', channels=('#test',), **options):
        options.setdefault('log_file', os.devnull)
        options.setdefault('ban_file', '')
        self.sent = []
        self.quit_message = None
        self._errors = _ErrorCatcher()
        super().__init__(list(channels), nickname, 'localhost', plugin_dir=plugin_dir, **options)
        self.driver = Driver(self)
        # a TestBot is always connected, so its timers run
        self.online = True
        for channel in channels:
            self.add_channel(channel)
        # a plugin that couldn't load fails here, not later
        self._raise_plugin_errors()

    def start_logging(self):
        super().start_logging()
        self.logger.addHandler(self._errors)

    def make_transport(self, server, nickname):
        return FakeTransport(self, nickname)

    def switches_path(self):
        # !enable and !disable stay in memory too
        return None

    def access_path(self):
        # and so do !allow and !deny
        return None

    def open_store(self, name):
        # stores stay in memory, look at one with bot.store('karma')
        return Store(name)

    @property
    def channels(self):
        """The channels the bot is in, each with the nicks seen there."""
        return self.transport.channels

    @property
    def pauses(self):
        """The waits for the rate limit the bot would have taken, in seconds."""
        return self.driver.pauses

    def add_channel(self, channel):
        if channel not in self.channels:
            self.channels[channel] = FakeChannel()
            self.channels[channel].add_user(self.transport.nick)

    def say(self, text, nick='tester', channel=None, **who):
        """Send a message to a channel as nick, and return the bot's replies there.

        who can be user, host and account, to test ops and bans by hostmask
        or account.
        """
        channel = channel or self.chanlist[0]
        self.add_channel(channel)
        self.channels[channel].add_user(nick, who.get('account'))
        return self._receive('privmsg', nick, channel, text, channel, **who)

    def action(self, text, nick='tester', channel=None, **who):
        """Send a /me action to a channel as nick, and return the bot's replies there."""
        channel = channel or self.chanlist[0]
        self.add_channel(channel)
        self.channels[channel].add_user(nick, who.get('account'))
        return self._receive('action', nick, channel, text, channel, **who)

    def private(self, text, nick='tester', **who):
        """Send a private message to the bot as nick, and return the bot's replies to them."""
        return self._receive('privmsg', nick, self.transport.nick, text, nick, **who)

    def event(self, kind, nick='tester', channel=None, text='', user=None, host='example.com',
              account=None, **data):
        """Something other than a message happens, and returns what the bot sent, as Sent.

        kind is join, part, kick, quit, nick, topic, invite, mode, netsplit, netjoin
        or notice. channel is the bot's first channel unless given, or none for nick,
        quit, netsplit and netjoin. data is
        the rest: kicked='troll' for a kick, new_nick='mal_' for a nick change,
        modes=['+o', 'mal'] for a mode change, which gives mal +o in the channel the
        way a real one would, invited='ana' for an invite of someone other than
        the bot, and nicks=['ana', 'bob'] for a netsplit or netjoin, with the two
        servers as text. A notice's channel can be the bot's nick.
        """
        if kind in ('nick', 'quit', 'netsplit', 'netjoin'):
            target = ''
        else:
            target = channel or self.chanlist[0]
        if kind == 'join':
            self.add_channel(target)
            self.channels[target].add_user(nick, account)
        elif kind == 'part' and target in self.channels:
            self.channels[target].remove_user(nick)
        elif kind == 'mode' and target in self.channels:
            self.channels[target].set_modes(data.get('modes', []))
        elif kind == 'invite':
            data.setdefault('invited', self.transport.nick)
        tags = {'account': account} if account else {}
        # a netsplit or netjoin comes from the network, not anyone in particular
        source = None if kind in ('netsplit', 'netjoin') else Source(nick, user or nick, host,
                                                                     account)
        if kind == 'notice':
            event = Event('message', source, target, text, 'notice', tags)
        else:
            event = Event(kind, source, target, text, tags=tags, data=data)
        start = len(self.sent)
        self.driver.run(event)
        self._raise_plugin_errors()
        return self.sent[start:]

    def tick(self, seconds):
        """Let seconds pass, run any @every timers that come due, and return what the bot sent.

        Time only moves when you call this, so a timer every 30 minutes runs on
        bot.tick(1800).
        """
        start = len(self.sent)
        self.driver.tick(seconds)
        self._raise_plugin_errors()
        return self.sent[start:]

    def sent_to(self, target):
        """Every message and action the bot has sent to target, like a nick for !help."""
        return [s.text for s in self.sent if s.target == target and s.kind in ('message', 'action')]

    def _receive(self, kind, nick, target, text, reply_to,
                 user=None, host='example.com', account=None):
        start = len(self.sent)
        tags = {'account': account} if account else {}
        source = Source(nick, user or nick, host, account)
        self.driver.run(Event('message', source, target, text, kind, tags))
        self._raise_plugin_errors()
        return [s.text for s in self.sent[start:]
                if s.target == reply_to and s.kind in ('message', 'action')]

    def _raise_plugin_errors(self):
        if self._errors.records:
            record = self._errors.records.pop(0)
            self._errors.records.clear()
            error = record.exc_info[1]
            raise PluginError('{}: {}'.format(record.getMessage(), error)) from error
