import pytest

from pinhook import bans


PING_PLUGIN = (
    "import pinhook.plugin as p\n"
    "@p.command('!ping')\n"
    "def ping(msg): return p.message('pong')\n"
)


# matching

def test_nick_entry_ignores_case():
    assert bans.matches('troll', 'TroLL')
    assert not bans.matches('troll', 'troll2')


def test_mask_entry_matches_any_nick_from_that_host():
    assert bans.matches('*!*@203.0.113.7', 'anything', 'user', '203.0.113.7')
    assert not bans.matches('*!*@203.0.113.7', 'anything', 'user', '203.0.113.8')


def test_mask_entry_works_with_brackets_in_nicks():
    assert bans.matches('nick[m]!*@*', 'Nick[M]', 'user', 'host')
    assert not bans.matches('nick[m]!*@*', 'nickm', 'user', 'host')


def test_account_entry_matches_account_not_nick():
    assert bans.matches('$a:Troll', 'newnick', account='troll')
    assert not bans.matches('$a:troll', 'troll')


# ban file

def test_ban_file_round_trip(tmp_path):
    path = str(tmp_path / 'bans.json')
    bans.save(path, ['troll', '$a:troll'])
    assert bans.load(path) == ['troll', '$a:troll']
    assert not (tmp_path / 'bans.json.tmp').exists()


def test_missing_ban_file_means_no_bans(tmp_path):
    assert bans.load(str(tmp_path / 'nope.json')) == []


def test_broken_ban_file_gives_clear_error(tmp_path):
    path = tmp_path / 'bans.json'
    path.write_text('["troll",')
    with pytest.raises(ValueError, match="couldn't read ban file"):
        bans.load(str(path))
    path.write_text('{"troll": true}')
    with pytest.raises(ValueError, match='should be a list'):
        bans.load(str(path))


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
