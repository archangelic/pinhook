import pytest

from pinhook import access
from pinhook.transport.base import Source, casefold
from pinhook.transport.identity import IrcIdentity


class Irc(IrcIdentity):
    def casefold(self, name):
        return casefold(name)


def matches(entry, nick, user=None, host=None, account=None):
    return Irc().matches(entry, Source(nick, user, host, account))


PING_PLUGIN = (
    "import pinhook.plugin as p\n"
    "@p.command('!ping')\n"
    "def ping(msg): return p.message('pong')\n"
)


# matching

def test_nick_entry_ignores_case():
    assert matches('troll', 'TroLL')
    assert not matches('troll', 'troll2')


def test_mask_entry_matches_any_nick_from_that_host():
    assert matches('*!*@203.0.113.7', 'anything', 'user', '203.0.113.7')
    assert not matches('*!*@203.0.113.7', 'anything', 'user', '203.0.113.8')


def test_mask_entry_works_with_brackets_in_nicks():
    assert matches('nick[m]!*@*', 'Nick[M]', 'user', 'host')
    assert not matches('nick[m]!*@*', 'nickm', 'user', 'host')


def test_account_entry_matches_account_not_nick():
    assert matches('$a:Troll', 'newnick', account='troll')
    assert not matches('$a:troll', 'troll')


# ban file

def test_ban_file_round_trip(tmp_path):
    path = str(tmp_path / 'bans.json')
    access.save_bans(path, ['troll', '$a:troll'])
    assert access.load_bans(path) == ['troll', '$a:troll']
    assert not (tmp_path / 'bans.json.tmp').exists()


def test_missing_ban_file_means_no_bans(tmp_path):
    assert access.load_bans(str(tmp_path / 'nope.json')) == []


def test_broken_ban_file_gives_clear_error(tmp_path):
    path = tmp_path / 'bans.json'
    path.write_text('["troll",')
    with pytest.raises(ValueError, match="couldn't read ban file"):
        access.load_bans(str(path))
    path.write_text('{"troll": true}')
    with pytest.raises(ValueError, match='should be a list'):
        access.load_bans(str(path))


# !ban picks the strongest ban it can


# saved bans


def test_broken_ban_file_stops_bot_starting(make_bot, tmp_path):
    (tmp_path / 'bans.json').write_text('not json')
    with pytest.raises(ValueError, match="couldn't read ban file"):
        make_bot()


# ops by account


# require_account


# capability negotiation


def test_seen_list_is_capped(make_bot):
    b = make_bot()
    for i in range(1100):
        b.remember('nick{}'.format(i), 'user', 'host', None)
    assert len(b.seen) == 1000
    assert 'nick0' not in b.seen and 'nick1099' in b.seen
