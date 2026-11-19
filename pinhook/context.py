"""The context: everything a plugin gets for one message, and nothing else."""
import asyncio
import contextlib
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, overload

from .history import Entry
from .store import PluginConfig, Store
from .transport.base import Event, Member, Source, Whois

if TYPE_CHECKING:
    from .bot import Bot, RunResult
    from .commands import CommandInfo
    from .recipes import Recipe

Text = str | Sequence[str]


class BotInfo:
    """What a plugin can see of the bot: ctx.bot in a handler, and self.bot in a Plugin
    class, from setup on. Read only."""

    def __init__(self, bot: 'Bot') -> None:
        self._bot = bot

    @property
    def nick(self) -> str:
        """The bot's nick right now."""
        return self._bot.transport.nick

    @property
    def channels(self) -> tuple[str, ...]:
        """The channels the bot is in."""
        return tuple(self._bot.transport.joined())

    @property
    def prefix(self) -> str:
        """The command prefix, like '!'. The first one, when there are several."""
        return str(self._bot.cmd_prefix)

    @property
    def data_dir(self) -> str:
        """The bot's data folder, where a plugin can keep files of its own."""
        return str(self._bot.data_dir)

    def is_op(self, who: Any) -> bool:
        """True if who, a Source or a Member, is one of the bot's ops."""
        return bool(self._bot.is_op(who))

    def matches(self, entry: str, who: Any) -> bool:
        """True if an entry like '$a:mal', a hostmask or a nick names who, a Source or a
        Member, the way ops, bans and grants are matched."""
        return bool(self._bot.transport.matches(entry, who))

    def keeps_history(self, channel: str) -> bool:
        """True if the history option lists channel, so ctx.history() is kept for it."""
        return bool(self._bot.history.records(channel))


class OwnCommands:
    """What a Plugin class can change of the bot: its own commands, and nothing of another
    plugin's. Plugin.set_recipes and Plugin.allow go through it."""

    def __init__(self, bot: 'Bot', plugin: str) -> None:
        self._bot = bot
        self._plugin = plugin

    def set_recipes(self, recipes: Sequence['Recipe']) -> list[str]:
        return list(self._bot.set_recipes(self._plugin, list(recipes)))

    def allow(self, command: str, who: Any) -> bool:
        return bool(self._bot.allow(self._plugin, command, who))


class Context:
    """One message or event, as a plugin sees it, and how to answer it.

    Attributes:
        event: what happened: 'message', 'notice', 'join', 'part', 'kick', 'quit',
            'nick', 'topic', 'invite', 'mode', 'netsplit', 'netjoin', 'connected' or
            'disconnected'.
        nick, user, host, account: who sent it, or who did it. account is their
            services account, or None when the server doesn't say.
        source: the same four as a Source, or None when nobody did it, like a timer.
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
        invited: who was invited, for an invite: the bot, or with invite-notify, anyone
            invited to a channel the bot is in.
        new_nick: the new nick, for a nick change. nick is the old one.
        modes: for a mode change, like ['+o', 'mal'].
        nicks: everyone who left in a netsplit, or came back in a netjoin. text holds
            the two servers.
        command: the command's name, without a prefix, for a command. None otherwise.
        arg: everything after the command word, for a command. For an @on('addressed')
            handler, the message after the bot's nick.
        time: when the message was sent, timezone-aware. The server's time when it says.
        tags: the message's IRCv3 tags.
        msgid: the message's ID, when the server gives one.
        store: the plugin's saved data, a dict kept between restarts.
        config: the plugin's settings from plugin_config, read only.
        bot: the bot's nick and channels, read only.
        logger: the bot's logger.
    """

    def __init__(self, bot: 'Bot', event: Event, plugin: str | None = None,
                 addressed: bool = False, command: str | None = None, arg: str = '',
                 capture: list[str] | None = None) -> None:
        self._bot = bot
        self._capture = capture
        source = event.source
        self.event = 'notice' if event.kind == 'notice' else event.type
        self.nick = source.nick if source else None
        self.user = source.user if source else None
        self.host = source.host if source else None
        self.account = source.account if source else None
        self.source: Source | None = source
        in_channel = bot.transport.is_channel(event.target or '')
        self.is_private = bool(event.target) and not in_channel and source is not None
        self.channel: str | None
        if in_channel:
            self.channel = event.target
        else:
            self.channel = self.nick if self.is_private else None
        self.is_op = bot.is_op(source) if source else False
        me = self.member(self.nick) if self.nick else None
        self.is_chanop = bool(me and me.is_chanop)
        self.tags = dict(event.tags)
        self.is_bot = 'bot' in self.tags or bool(me and me.is_bot)
        self.addressed = addressed
        self.text = event.text
        self.kind = event.kind
        self.kicked = event.data.get('kicked')
        self.invited = event.data.get('invited')
        self.new_nick = event.data.get('new_nick')
        self.modes = list(event.data.get('modes', []))
        self.nicks = tuple(event.data.get('nicks', ()))
        self.command = command
        self.arg = arg
        self.msgid = self.tags.get('msgid')
        self.time = server_time(self.tags.get('time')) or datetime.now(timezone.utc)
        self.plugin = plugin
        self._store: dict[str, Any] | None = None
        self.config = bot.config_for(plugin) if plugin else PluginConfig('plugin')
        self.bot: BotInfo = bot.info
        self.logger = bot.logger

    @property
    def store(self) -> dict[str, Any]:
        """The plugin's saved data, a dict kept between restarts."""
        if self._store is None:
            self._store = self._bot.store(self.plugin) if self.plugin else {}
        return self._store

    def save_store(self) -> None:
        """Save the plugin's store, if the handler used it and changed something."""
        if isinstance(self._store, Store):
            self._store.save_if_changed()

    def members(self, channel: str | None = None) -> tuple[Member, ...]:
        """Who is in channel, this one by default, as Members: each one's nick, account,
        modes and whether they're a bot. From member tracking, so it never waits on the
        server. Empty for a private message."""
        channel = channel or self.channel
        if channel is None or not self._bot.transport.is_channel(channel):
            return ()
        return tuple(self._bot.transport.members(channel))

    def member(self, nick: str, channel: str | None = None) -> Member | None:
        """nick's Member in channel, this one by default, or None if they aren't in it."""
        channel = channel or self.channel
        if channel is None or not self._bot.transport.is_channel(channel):
            return None
        return self._bot.transport.member(channel, nick)

    async def whois(self, nick: str) -> Whois | None:
        """Ask the server about nick, and return a Whois, or None if there's no one by
        that name. This waits for the server, unlike members()."""
        return await self._bot.transport.whois(nick)

    def history(self, limit: int | None = None) -> tuple[Entry, ...]:
        """This channel's recent messages, oldest first, as history Entries: nick, text,
        kind, time, msgid and own, True for the bot's. Empty unless the history option
        lists the channel. limit keeps only that many of the newest."""
        if not self._bot.transport.is_channel(self.channel or ''):
            return ()
        return self._bot.history.recent(self.channel, limit)

    def commands(self) -> list['CommandInfo']:
        """The commands the sender can trigger here, from the command listing: each one's
        name, help, typed arguments and access level. Empty when nobody sent this."""
        if self.source is None:
            return []
        return self._bot.commands(self.source, self.in_channel())

    async def run(self, command: str, arg: str = '') -> 'RunResult':
        """Run a command as the sender, here, with their access, and return how it went,
        with what it said where it ran instead of saying it. command is its name, like
        'roll', and arg the text after it."""
        if self.source is None:
            raise RuntimeError('there is nobody to run a command as here')
        return await self._bot.run_as(self.source, command, arg, self.in_channel())

    def in_channel(self) -> str | None:
        return self.channel if self._bot.transport.is_channel(self.channel or '') else None

    def supports(self, feature: str) -> bool:
        """True if the network supports feature, like 'account-tag'."""
        return self._bot.transport.supports(feature)

    async def reply(self, text: Text, thread: bool = False, private: bool = False,
                    prefix: str = '') -> None:
        """Answer where the message came from: the channel, or the sender if private.

        Args:
            text: what to say. Each line is sent as its own message.
            thread: answer this message in particular. Clients that show threads show it
                under the message, and elsewhere it starts with the sender's nick.
            private: answer the sender in a private message instead, which their client
                can show with the channel it's about.
            prefix: text to start every line with, like '[bot] '. A line too long for
                the network is split, and each part starts with it too.
        """
        target = self.where(self.channel)
        tags: dict[str, str] = {}
        if not self.supports('private'):
            thread = thread or private
            private = False
        if private and self.nick and not self.is_private:
            tags['+channel-context'] = target
            target = self.nick
        elif thread and self.nick and not self.is_private:
            if self.msgid and self.supports('reply'):
                tags['+reply'] = self.msgid
            else:
                prefix += '{}: '.format(self.nick)
        self.out('privmsg', target, text, tags, prefix)

    def out(self, kind: str, target: str, text: Text, tags: dict[str, str] | None = None,
            prefix: str = '') -> None:
        fold = self._bot.transport.casefold
        if self._capture is not None and kind != 'notice' and self.channel and \
                fold(target) == fold(self.channel):
            self._capture.extend(prefix + line for line in text_lines(text))
        else:
            self._bot.send_text(kind, target, text, tags, prefix)

    @contextlib.asynccontextmanager
    async def typing(self) -> AsyncIterator[None]:
        """Show the bot as typing while a slow command works:

            async with ctx.typing():
                forecast = await fetch_forecast(city)
            await ctx.reply(forecast)

        Does nothing where the network can't show it."""
        target = self.channel
        if not target or not self.supports('typing') or self._capture is not None:
            yield
            return
        transport = self._bot.transport
        transport.typing(target, 'active')
        keep_going = asyncio.get_running_loop().create_task(self.keep_typing(target))
        try:
            yield
        finally:
            keep_going.cancel()
            transport.typing(target, 'done')

    async def keep_typing(self, target: str) -> None:
        while True:
            await asyncio.sleep(3)
            self._bot.transport.typing(target, 'active')

    async def send(self, target: str, text: Text, prefix: str = '') -> None:
        """Send text to another channel or nick, with prefix at the start of every line."""
        self.out('privmsg', target, text, prefix=prefix)

    @overload
    async def action(self, text: Text, /) -> None: ...

    @overload
    async def action(self, target: str, text: Text, /) -> None: ...

    async def action(self, *args: Any) -> None:
        """action(text) answers with a /me, action(target, text) sends one somewhere else."""
        target, text = target_and_text(args, self.channel)
        self.out('action', self.where(target), text)

    @overload
    async def notice(self, text: Text, /) -> None: ...

    @overload
    async def notice(self, target: str, text: Text, /) -> None: ...

    async def notice(self, *args: Any) -> None:
        """notice(text) sends the sender a notice, notice(target, text) sends one to anyone.

        Where the network has no notices from bots, like Twitch, a notice to a channel
        is sent as a message, and one to a person isn't sent: the bot logs a warning,
        once per plugin. ctx.supports('notice') says which."""
        target, text = target_and_text(args, self.nick)
        target = self.where(target)
        if self.supports('notice'):
            self.out('notice', target, text)
        elif self._bot.transport.is_channel(target):
            self.out('privmsg', target, text)
        elif self.plugin not in self._bot.notice_warned:
            self._bot.notice_warned.add(self.plugin)
            self.logger.warning('plugin {} sent a notice to {}, but this network has no '
                                'notices from bots, so it was dropped. Check '
                                "ctx.supports('notice') first".format(self.plugin, target))

    def where(self, target: str | None) -> str:
        if not target:
            raise RuntimeError('there is no channel or sender to answer here, '
                               'use ctx.send(target, text)')
        return target


def text_lines(text: Text) -> list[str]:
    """The lines text is sent as: each line of a string, or of each item in a list."""
    if isinstance(text, (list, tuple)):
        return [line for item in text for line in str(item).splitlines()]
    return str(text).splitlines()


def target_and_text(args: tuple[Any, ...], default_target: str | None) -> tuple[Any, Any]:
    if len(args) == 1:
        return default_target, args[0]
    if len(args) == 2:
        return args
    raise TypeError('expected (text) or (target, text), got {} arguments'.format(len(args)))


def server_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
