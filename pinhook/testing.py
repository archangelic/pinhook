"""Test pinhook plugins without connecting to a server.

    from pinhook.testing import TestBot

    def test_roll():
        bot = TestBot(plugin_dir='plugins')
        assert bot.say('!roll 1d1') == ['1']
"""
from collections import namedtuple
import logging
import os

import irc.bot
import irc.client

from .bot import Bot

# one thing the bot sent, kind is 'message', 'action' or 'notice'
Sent = namedtuple('Sent', ['kind', 'target', 'text'])


class PluginError(Exception):
    """A plugin raised an exception, or returned something it shouldn't."""


class FakeConnection:
    # stands in for the irc library's connection and records what the bot sends

    def __init__(self, bot, nickname):
        self.bot = bot
        self.nickname = nickname

    def get_nickname(self):
        return self.nickname

    def privmsg(self, target, text):
        self.bot.sent.append(Sent('message', target, text))

    def action(self, target, text):
        self.bot.sent.append(Sent('action', target, text))

    def notice(self, target, text):
        self.bot.sent.append(Sent('notice', target, text))

    def join(self, channel, key=''):
        self.bot.add_channel(channel)

    def part(self, channel, message=''):
        self.bot.channels.pop(channel, None)

    def nick(self, new_nick):
        self.nickname = new_nick

    def quit(self, message=''):
        self.bot.quit_message = message

    def mode(self, target, command):
        pass

    def cap(self, subcommand, *args):
        pass


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
        self.pauses = []
        self.quit_message = None
        self._errors = _ErrorCatcher()
        super().__init__(list(channels), nickname, 'localhost', plugin_dir=plugin_dir, **options)
        self.connection = FakeConnection(self, nickname)
        for channel in channels:
            self.add_channel(channel)
        # a plugin that couldn't load fails here, not later
        self._raise_plugin_errors()

    def start_logging(self):
        super().start_logging()
        self.logger.addHandler(self._errors)

    def pause(self, seconds):
        # record flood protection pauses instead of waiting for them
        self.pauses.append(seconds)

    def add_channel(self, channel):
        if channel not in self.channels:
            self.channels[channel] = irc.bot.Channel()
            self.channels[channel].add_user(self.connection.get_nickname())

    def say(self, text, nick='tester', channel=None, **who):
        """Send a message to a channel as nick, and return the bot's replies there.

        who can be user, host and account, to test ops and bans by hostmask
        or account.
        """
        channel = channel or self.chanlist[0]
        self.add_channel(channel)
        self.channels[channel].add_user(nick)
        return self._receive('pubmsg', nick, channel, text, channel, **who)

    def action(self, text, nick='tester', channel=None, **who):
        """Send a /me action to a channel as nick, and return the bot's replies there."""
        channel = channel or self.chanlist[0]
        self.add_channel(channel)
        self.channels[channel].add_user(nick)
        return self._receive('action', nick, channel, text, channel, **who)

    def private(self, text, nick='tester', **who):
        """Send a private message to the bot as nick, and return the bot's replies to them."""
        return self._receive('privmsg', nick, self.connection.get_nickname(), text, nick, **who)

    def sent_to(self, target):
        """Every message and action the bot has sent to target, like a nick for !help."""
        return [s.text for s in self.sent if s.target == target and s.kind in ('message', 'action')]

    def _receive(self, kind, nick, target, text, reply_to, user=None, host='example.com', account=None):
        start = len(self.sent)
        source = irc.client.NickMask.from_params(nick, user or nick, host)
        tags = [{'key': 'account', 'value': account}] if account else None
        self.process_event(self.connection, irc.client.Event(kind, source, target, [text], tags))
        self._raise_plugin_errors()
        return [s.text for s in self.sent[start:] if s.target == reply_to and s.kind in ('message', 'action')]

    def _raise_plugin_errors(self):
        if self._errors.records:
            record = self._errors.records.pop(0)
            self._errors.records.clear()
            raise PluginError(record.getMessage()) from record.exc_info[1]
