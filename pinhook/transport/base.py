"""What the core and the transports under it share.

The core never touches the network. A transport connects, turns what the
network sends into Events for the core, and sends the core's Outgoing
messages. The interface is internal and can change before 2.0.
"""
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Source:
    """Who an event came from."""
    nick: str
    user: str | None = None
    host: str | None = None
    account: str | None = None


@dataclass(frozen=True)
class Event:
    """Something that happened on the network.

    type is 'connected' once the bot is registered, 'disconnected' when the
    connection drops, or 'message'. A message's kind is 'privmsg' or 'action',
    and its target is a channel or the bot's own nick.
    """
    type: str
    source: Source | None = None
    target: str = ''
    text: str = ''
    kind: str = ''
    tags: dict[str, str | None] = field(default_factory=dict)


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

    async def connect(self) -> None:
        """Start connecting. Keeps reconnecting until closed."""
        ...

    def events(self) -> AsyncIterator[Event]:
        """Every event from the network, until the transport is closed."""
        ...

    async def send(self, message: Outgoing) -> None: ...

    def join(self, channel: str, key: str = '') -> None: ...

    def members(self, channel: str) -> list[str]: ...

    def supports(self, feature: str) -> bool: ...

    async def close(self, reason: str = '') -> None: ...


def is_channel(name: str) -> bool:
    # the channel types every irc server has, until CHANTYPES is read from the server
    return name[:1] in '#&+!'
