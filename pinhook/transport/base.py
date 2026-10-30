"""What the core and the transports under it share.

The core never touches the network. A transport connects, turns what the
network sends into Events for the core, and sends the core's Outgoing
messages. The interface is internal and can change before 2.0.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
import string
from typing import Protocol


@dataclass(frozen=True)
class Source:
    """Who an event came from."""
    nick: str
    user: str | None = None
    host: str | None = None
    account: str | None = None


@dataclass(frozen=True)
class Member:
    """Someone in a channel, as member tracking knows them.

    modes are the channel modes they have there, like {'o'} for a channel operator.
    account is None when they're not logged in or the server doesn't say. is_bot is
    True when the server marks them as a bot.
    """
    nick: str
    user: str | None = None
    host: str | None = None
    account: str | None = None
    modes: frozenset[str] = frozenset()
    away: bool = False
    realname: str | None = None
    is_bot: bool = False

    @property
    def is_chanop(self) -> bool:
        """True for a channel operator: +o, or the +a and +q some servers have above it."""
        return bool(self.modes & CHANOP_MODES)

    @property
    def is_voiced(self) -> bool:
        """True for +v, or any mode above it, like halfop or op."""
        return bool(self.modes & VOICED_MODES)


@dataclass(frozen=True)
class Whois:
    """What the server says about someone, from await ctx.whois(nick).

    channels are the ones the server shows, which leaves out secret channels the
    bot isn't in. away is their away message, or None. idle is seconds since they
    last spoke, when the server says.
    """
    nick: str
    user: str | None = None
    host: str | None = None
    realname: str | None = None
    account: str | None = None
    channels: tuple[str, ...] = ()
    away: str | None = None
    server: str | None = None
    idle: int | None = None
    operator: bool = False
    is_bot: bool = False
    secure: bool = False


# the member modes that make someone a channel operator, or voiced or better
CHANOP_MODES = frozenset('qao')
VOICED_MODES = frozenset('qaohv')


@dataclass(frozen=True)
class Event:
    """Something that happened on the network.

    type is 'connected' once the bot is registered, 'disconnected' when the
    connection drops, 'message', or one of join, part, kick, quit, nick, topic,
    invite and mode. A message's kind is 'privmsg', 'action' or 'notice', and
    its target is a channel or the bot's own nick.

    text is a message's text, a part, kick or quit's reason, or a new topic.
    data holds the rest: kicked for a kick, new_nick for a nick change, and
    modes for a mode change, like ['+o', 'mal'].
    """
    type: str
    source: Source | None = None
    target: str = ''
    text: str = ''
    kind: str = ''
    tags: dict[str, str | None] = field(default_factory=dict)
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Outgoing:
    """A message for the transport to send. kind is 'privmsg', 'action' or 'notice'.

    The prefix goes in front of every line the text is sent as.
    """
    kind: str
    target: str
    text: str
    prefix: str = ''


@dataclass(frozen=True)
class Limits:
    """How fast the output queue sends: burst lines at once, then one every interval
    seconds. Each target holds at most backlog lines waiting to be sent."""
    burst: int = 4
    interval: float = 2.0
    backlog: int = 50


class MessageTooLong(ValueError):
    """The text doesn't fit in one line, and this transport doesn't split it."""


class Transport(Protocol):
    """A connection to one network."""
    name: str
    limits: Limits

    @property
    def nick(self) -> str:
        """The bot's nick right now."""
        ...

    async def run(self) -> None:
        """Connect, and keep reconnecting, until closed."""
        ...

    def events(self) -> AsyncIterator[Event]:
        """Every event from the network, until the transport is closed."""
        ...

    async def send(self, message: Outgoing) -> None: ...

    def join(self, channel: str, key: str = '') -> None: ...

    def text_room(self, kind: str, target: str, prefix: str = '') -> int:
        """How many bytes of text fit in one message of this kind to target."""
        ...

    def members(self, channel: str) -> list[Member]:
        """Who is in channel, from member tracking, with no call to the server."""
        ...

    def joined(self) -> list[str]:
        """The channels the bot is in."""
        ...

    async def whois(self, nick: str, timeout: float = 10) -> Whois | None:
        """Ask the server about nick. None if there's no one by that name, or no answer."""
        ...

    def member_modes(self, channel: str, nick: str) -> frozenset[str]:
        """The channel modes nick has in channel, like {'o'} for a channel operator."""
        ...

    def supports(self, feature: str) -> bool: ...

    def casefold(self, name: str) -> str: ...

    async def close(self, reason: str = '') -> None: ...


# how servers lowercase nicks and channel names, named by ISUPPORT CASEMAPPING.
# rfc1459 also counts [ ] \ ^ as the uppercase { } | ~
UPPER, LOWER = string.ascii_uppercase, string.ascii_lowercase
CASEMAPPINGS = {
    'ascii': str.maketrans(UPPER, LOWER),
    'rfc1459': str.maketrans(UPPER + '[]\\^', LOWER + '{}|~'),
    'rfc1459-strict': str.maketrans(UPPER + '[]\\', LOWER + '{}|'),
}


def casefold(name: str, casemapping: str = 'rfc1459') -> str:
    """name in lowercase, the way a server with this CASEMAPPING compares names."""
    return name.translate(CASEMAPPINGS.get(casemapping, CASEMAPPINGS['rfc1459']))


def is_channel(name: str) -> bool:
    # the channel types every irc server has, until CHANTYPES is read from the server
    return bool(name) and name[0] in '#&+!'
