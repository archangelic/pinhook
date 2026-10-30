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
    """One message or event, as a plugin sees it, and how to answer it.

    Attributes:
        event: what happened: 'message', 'notice', 'join', 'part', 'kick', 'quit',
            'nick', 'topic', 'invite', 'mode', 'connected' or 'disconnected'.
        nick, user, host, account: who sent it, or who did it. account is their
            services account, or None when the server doesn't say.
        channel: where to answer: the channel, or the sender for a private message.
            None when there's nowhere, like a nick change or a quit.
        is_private: True for a private message to the bot.
        is_op: True if the sender is one of the bot's ops.
        is_chanop: True if the sender is a channel operator (+o, or more) in this channel.
        is_bot: True if the server marks the sender as a bot.
        addressed: True when the message started with the bot's nick, like "pinhook: hi".
        text: the whole message, a part, kick or quit's reason, or a new topic.
        kind: a message's 'privmsg', 'action' or 'notice'.
        kicked: who was kicked, for a kick.
        new_nick: the new nick, for a nick change. nick is the old one.
        modes: for a mode change, like ['+o', 'mal'].
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
        self.event = 'notice' if event.kind == 'notice' else event.type
        self.nick = source.nick if source else None
        self.user = source.user if source else None
        self.host = source.host if source else None
        self.account = source.account if source else None
        self.is_private = bool(event.target) and not is_channel(event.target) and source is not None
        if is_channel(event.target):
            self.channel = event.target
        else:
            self.channel = self.nick if self.is_private else None
        self.is_op = bot.is_op(source) if source else False
        me = self.member(self.nick) if self.nick else None
        self.is_chanop = bool(me and me.is_chanop)
        self.tags = dict(event.tags)
        # bot mode: the server tags a bot's messages, and marks bots in WHO
        self.is_bot = 'bot' in self.tags or bool(me and me.is_bot)
        self.addressed = addressed
        self.text = event.text
        self.kind = event.kind
        self.kicked = event.data.get('kicked')
        self.new_nick = event.data.get('new_nick')
        self.modes = list(event.data.get('modes', []))
        self.command = command
        self.arg = arg
        self.msgid = self.tags.get('msgid')
        self.time = server_time(self.tags.get('time')) or datetime.now(timezone.utc)
        self.plugin = plugin
        self.store = bot.store(plugin) if plugin else {}
        self.config = bot.config_for(plugin) if plugin else PluginConfig('plugin')
        self.bot = BotInfo(bot)
        self.logger = bot.logger

    def members(self, channel=None):
        """Who is in channel, this one by default, as Members: each one's nick, account,
        modes and whether they're a bot. From member tracking, so it never waits on the
        server. Empty for a private message."""
        channel = channel or self.channel
        if not is_channel(channel or ''):
            return ()
        return tuple(self._bot.transport.members(channel))

    def member(self, nick, channel=None):
        """nick's Member in channel, this one by default, or None if they aren't in it."""
        fold = self._bot.transport.casefold
        for member in self.members(channel):
            if fold(member.nick) == fold(nick):
                return member
        return None

    def supports(self, feature):
        """True if the network supports feature, like 'account-tag'."""
        return self._bot.transport.supports(feature)

    async def reply(self, text):
        """Answer where the message came from: the channel, or the sender if private."""
        self._bot.send_text('privmsg', self.where(self.channel), text)

    async def send(self, target, text):
        """Send text to another channel or nick."""
        self._bot.send_text('privmsg', target, text)

    async def action(self, *args):
        """action(text) answers with a /me, action(target, text) sends one somewhere else."""
        target, text = target_and_text(args, self.channel)
        self._bot.send_text('action', self.where(target), text)

    async def notice(self, *args):
        """notice(text) sends the sender a notice, notice(target, text) sends one to anyone."""
        target, text = target_and_text(args, self.nick)
        self._bot.send_text('notice', self.where(target), text)

    def where(self, target):
        if not target:
            raise RuntimeError('there is no channel or sender to answer here, '
                               'use ctx.send(target, text)')
        return target


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
