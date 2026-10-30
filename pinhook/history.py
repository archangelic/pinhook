"""Recent history: the last few messages in each channel that has it turned on.

Plugins read it through ctx.history(), for context like who said what just now.
It's kept in memory only, so a restart empties it, and a channel is only recorded
when the config lists it.
"""
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class Entry:
    """One message in a channel's history.

    kind is 'privmsg', 'action' or 'notice'. own is True for the bot's own lines.
    time is when it was sent, the server's time when it says.
    """
    nick: str
    text: str
    kind: str
    time: datetime
    msgid: str | None = None
    own: bool = False


def parse_config(config):
    """The history option, checked: (casefolded channel names, size, seconds)."""
    config = config or {}
    if not isinstance(config, dict):
        raise ValueError('history should be settings like {channels: ["#games"]}')
    unknown = sorted(set(config) - {'channels', 'size', 'minutes'})
    if unknown:
        raise ValueError("history has settings pinhook doesn't know: {}. It takes channels, "
                         "size and minutes".format(', '.join(unknown)))
    channels = config.get('channels', [])
    if not isinstance(channels, list) or not all(isinstance(c, str) for c in channels):
        raise ValueError('history.channels should be a list of channels, like ["#games"]')
    size, minutes = config.get('size', 20), config.get('minutes', 10)
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        raise ValueError('history.size should be a whole number of messages, 1 or more')
    if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or minutes <= 0:
        raise ValueError('history.minutes should be a number of minutes, more than 0')
    return channels, size, minutes * 60


class History:
    """The recent messages of the channels that have history turned on.

    Args:
        config: the history option.
        fold: the server's case folding, so #Games and #games are one channel.
        now: what time it is, so tests can fake it.
    """

    def __init__(self, config, fold, now=lambda: datetime.now(timezone.utc)):
        channels, self.size, self.seconds = parse_config(config)
        self.fold = fold
        self.now = now
        self.wanted = list(channels)
        self.channels = {}

    def records(self, channel):
        """True if channel has history turned on."""
        return any(self.fold(c) == self.fold(channel) for c in self.wanted)

    def add(self, channel, entry):
        if not self.records(channel):
            return
        self.channels.setdefault(self.fold(channel), deque(maxlen=self.size)).append(entry)

    def recent(self, channel, limit=None):
        """The channel's messages, oldest first: at most size of them, from the last few
        minutes. limit keeps only that many of the newest."""
        entries = self.channels.get(self.fold(channel), ())
        cutoff = self.now() - timedelta(seconds=self.seconds)
        found = [e for e in entries if e.time >= cutoff]
        return tuple(found[-limit:] if limit else found)
