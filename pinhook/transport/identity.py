"""Who someone is, as each platform sees it: the entries ops, bans and access lists use,
the built-in groups, and what !ban and !allow save.

The rules of access stay in the core. A transport says whether an entry names
someone, whether they're in one of its groups, and which entry is hardest to dodge.

An entry is one of:
    a nick                  troll
    a hostmask              *!*@203.0.113.7  (* and ? are wildcards)
    a services account      $a:troll
"""
import fnmatch

from .base import CHANOP_MODES, VOICED_MODES


def entry_kind(entry):
    """'account' for $a:name, 'mask' for nick!user@host, or 'nick'."""
    if entry.startswith('$a:'):
        return 'account'
    if '!' in entry or '@' in entry:
        return 'mask'
    return 'nick'


class IrcIdentity:
    """IRC's identities: nicks, hostmasks and services accounts, and the chanops, voiced
    and logged-in groups. Mixed into a transport with casefold and member_modes."""
    entry_kinds = frozenset({'nick', 'mask', 'account'})
    groups = frozenset({'chanops', 'voiced', 'logged-in'})

    def matches(self, entry, who):
        """True if entry names who."""
        # casefold is the server's lowercasing. Its rfc1459 one turns [ ] into { }, so
        # nicks can't break the wildcard match
        fold = self.casefold
        entry = fold(entry)
        kind = entry_kind(entry)
        if kind == 'account':
            return bool(who.account) and fold(who.account) == entry[len('$a:'):]
        if kind == 'mask':
            mask = fold('{}!{}@{}'.format(who.nick, who.user or '', who.host or ''))
            return fnmatch.fnmatchcase(mask, entry)
        return fold(who.nick) == entry

    def in_group(self, group, who, channel):
        """True if who is in one of this platform's built-in groups, in channel."""
        if group == 'logged-in':
            return bool(who.account)
        if not channel or group not in self.groups:
            return False
        modes = self.member_modes(channel, who.nick)
        return bool(modes & (CHANOP_MODES if group == 'chanops' else VOICED_MODES))

    def strongest_entry(self, who):
        """What !ban and !allow save for who: their account if they're logged in, or else
        their user and host, since a nick on its own is easy to change."""
        if who.account:
            return '$a:' + who.account
        return '*!*{}@{}'.format((who.user or '').lstrip('~'), who.host)


class TwitchIdentity(IrcIdentity):
    """Twitch's identities: nicks, which are logins and unique, and accounts, with badges
    as groups. Everyone on Twitch is logged in. chanops are the broadcaster and
    moderators, and voiced adds VIPs, from the member modes their badges become."""
    entry_kinds = frozenset({'nick', 'account'})
    badge_groups = frozenset({'broadcaster', 'moderator', 'vip', 'subscriber'})
    groups = IrcIdentity.groups | badge_groups

    def in_group(self, group, who, channel):
        if group == 'logged-in':
            return True
        if group in self.badge_groups:
            return bool(channel) and group in self.member_badges(channel, who.nick)
        return super().in_group(group, who, channel)

    def member_badges(self, channel, nick):
        """The badges nick showed in channel with their last message."""
        return frozenset()

    def strongest_entry(self, who):
        return '$a:' + who.account if who.account else who.nick
