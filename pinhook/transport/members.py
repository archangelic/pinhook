"""Who is in each channel the bot is in, kept up to date from what the server sends.

Each person is kept once, with their user, host, account, away status, real name
and whether they're a bot, and each channel keeps the modes they have there.
Someone the bot no longer shares a channel with is forgotten.
"""
from .base import Member

# the fields Tracker.update takes
FIELDS = ('user', 'host', 'account', 'away', 'realname', 'is_bot')


class Tracker:
    """Channel members for one connection.

    Args:
        fold: the server's case folding, called each time so a CASEMAPPING that
            arrives later is used.
    """

    def __init__(self, fold):
        self.fold = fold
        self.clear()

    def clear(self):
        # casefolded nick: the person's details, including their nick as written
        self.people = {}
        # casefolded channel: {casefolded nick: set of mode letters}
        self.channels = {}

    def add_channel(self, channel):
        self.channels[self.fold(channel)] = {}

    def remove_channel(self, channel):
        members = self.channels.pop(self.fold(channel), {})
        for key in members:
            self.forget_if_gone(key)

    def has_channel(self, channel):
        return self.fold(channel) in self.channels

    def join(self, channel, nick, **details):
        """nick is in channel, with whatever details are known."""
        members = self.channels.get(self.fold(channel))
        if members is None:
            return
        key = self.person(nick, **details)
        members.setdefault(key, set())

    def person(self, nick, **details):
        key = self.fold(nick)
        person = self.people.setdefault(key, {'nick': nick, 'user': None, 'host': None,
                                              'account': None, 'away': False, 'realname': None,
                                              'is_bot': False})
        person['nick'] = nick
        self.update(nick, **details)
        return key

    def update(self, nick, **details):
        """Change what's known about nick. A detail given as None is left as it was."""
        person = self.people.get(self.fold(nick))
        if person is None:
            return
        for name, value in details.items():
            if name not in FIELDS:
                raise TypeError('unknown member detail {}'.format(name))
            if value is not None:
                person[name] = value

    def log_out(self, nick):
        person = self.people.get(self.fold(nick))
        if person is not None:
            person['account'] = None

    def leave(self, channel, nick):
        members = self.channels.get(self.fold(channel))
        if members is not None:
            members.pop(self.fold(nick), None)
        self.forget_if_gone(self.fold(nick))

    def quit(self, nick):
        key = self.fold(nick)
        for members in self.channels.values():
            members.pop(key, None)
        self.people.pop(key, None)

    def rename(self, old, new):
        old_key, new_key = self.fold(old), self.fold(new)
        person = self.people.pop(old_key, None)
        if person is None:
            return
        person['nick'] = new
        self.people[new_key] = person
        for members in self.channels.values():
            if old_key in members:
                members[new_key] = members.pop(old_key)

    def set_mode(self, channel, nick, letter, on):
        members = self.channels.get(self.fold(channel))
        if members is None:
            return
        modes = members.setdefault(self.person(nick), set())
        if on:
            modes.add(letter)
        else:
            modes.discard(letter)

    def set_modes(self, channel, nick, letters):
        """Replace the modes nick has in channel, like from NAMES or WHO."""
        members = self.channels.get(self.fold(channel))
        if members is not None and self.fold(nick) in members:
            members[self.fold(nick)] = set(letters)

    def forget_if_gone(self, key):
        if not any(key in members for members in self.channels.values()):
            self.people.pop(key, None)

    def lookup(self, nick):
        """What's known about nick, as a dict, or None for someone in none of the channels."""
        person = self.people.get(self.fold(nick))
        return dict(person) if person else None

    def members(self, channel):
        """The members of channel, as Members, in the order they were first seen."""
        members = self.channels.get(self.fold(channel), {})
        return [self.member(key, modes) for key, modes in members.items() if key in self.people]

    def member(self, key, modes):
        person = self.people[key]
        return Member(person['nick'], person['user'], person['host'], person['account'],
                      frozenset(modes), person['away'], person['realname'], person['is_bot'])

    def modes(self, channel, nick):
        members = self.channels.get(self.fold(channel), {})
        return frozenset(members.get(self.fold(nick), ()))

    def channel_names(self):
        return list(self.channels)
