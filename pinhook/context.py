"""The context: everything a plugin gets for one message, and nothing else."""
from datetime import datetime, timezone

from .store import PluginConfig
from .transport.base import is_channel


class BotInfo:
    """What a plugin can see of the bot. Read only."""

    def __init__(self, bot):
        self._bot = bot

    @property
    def nick(self):
        """The bot's nick right now."""
        return self._bot.transport.nick

    @property
    def channels(self):
        """The channels the bot is in."""
        return tuple(self._bot.transport.joined())


class Context:
    """One message, as a plugin sees it, and how to answer it.

    Attributes:
        nick, user, host, account: who sent it. account is their services
            account, or None when the server doesn't say.
        channel: where to answer: the channel, or the sender for a private message.
        is_private: True for a private message to the bot.
        is_op: True if the sender is one of the bot's ops.
        addressed: True when the message started with the bot's nick, like "pinhook: hi".
        text: the whole message.
        kind: 'privmsg', or 'action' for a /me.
        command: the command's name, without a prefix, for a command. None otherwise.
        arg: everything after the command word, for a command.
        time: when the message was sent, timezone-aware. The server's time when it says.
        tags: the message's IRCv3 tags.
        msgid: the message's ID, when the server gives one.
        store: the plugin's saved data, a dict kept between restarts.
        config: the plugin's settings from plugin_config, read only.
        bot: the bot's nick and channels, read only.
        logger: the bot's logger.
    """

    def __init__(self, bot, event, plugin=None, addressed=False, command=None, arg=''):
        self._bot = bot
        source = event.source
        self.nick = source.nick
        self.user = source.user
        self.host = source.host
        self.account = source.account
        self.is_private = not is_channel(event.target)
        self.channel = source.nick if self.is_private else event.target
        self.is_op = bot.is_op(source)
        self.addressed = addressed
        self.text = event.text
        self.kind = event.kind
        self.command = command
        self.arg = arg
        self.tags = dict(event.tags)
        self.msgid = self.tags.get('msgid')
        self.time = server_time(self.tags.get('time')) or datetime.now(timezone.utc)
        self.plugin = plugin
        self.store = bot.store(plugin) if plugin else {}
        self.config = bot.config_for(plugin) if plugin else PluginConfig('plugin')
        self.bot = BotInfo(bot)
        self.logger = bot.logger

    def supports(self, feature):
        """True if the network supports feature, like 'account-tag'."""
        return self._bot.transport.supports(feature)

    async def reply(self, text):
        """Answer where the message came from: the channel, or the sender if private."""
        self._bot.send_text('privmsg', self.channel, text)

    async def send(self, target, text):
        """Send text to another channel or nick."""
        self._bot.send_text('privmsg', target, text)

    async def action(self, *args):
        """action(text) answers with a /me, action(target, text) sends one somewhere else."""
        target, text = target_and_text(args, self.channel)
        self._bot.send_text('action', target, text)

    async def notice(self, *args):
        """notice(text) sends the sender a notice, notice(target, text) sends one to anyone."""
        target, text = target_and_text(args, self.nick)
        self._bot.send_text('notice', target, text)


def target_and_text(args, default_target):
    if len(args) == 1:
        return default_target, args[0]
    if len(args) == 2:
        return args
    raise TypeError('expected (text) or (target, text), got {} arguments'.format(len(args)))


def server_time(value):
    # the server-time tag, like 2026-10-30T01:02:03.456Z
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
