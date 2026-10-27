import json
from types import SimpleNamespace
from unittest import mock

import pytest

from pinhook import bans
from pinhook import bot as pinhook_bot

from conftest import event


PING_PLUGIN = (
    "import pinhook.plugin as p\n"
    "@p.command('!ping')\n"
    "def ping(msg): return p.message('pong')\n"
)


def replies(conn):
    return [c.args[1] for c in conn.privmsg.call_args_list]


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

def test_ban_logged_in_user_bans_their_account(make_bot, conn):
    b = make_bot(ops=['mal'])
    b.process_event(conn, event('troll', '#test', 'hi', account='trollacct'))
    b.process_event(conn, event('mal', '#test', '!ban troll'))
    assert b.banned_users == ['$a:trollacct']
    assert replies(conn) == ['mal: banned troll (account trollacct)']
    conn.reset_mock()
    b.process_event(conn, event('newnick', '#test', '!banlist', host='elsewhere', account='trollacct'))
    conn.privmsg.assert_not_called()


def test_ban_without_account_bans_user_and_host(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('ping', PING_PLUGIN), ops=['mal'])
    b.process_event(conn, event('troll', '#test', 'hi', user='~troll', host='203.0.113.7'))
    b.process_event(conn, event('mal', '#test', '!ban troll'))
    assert b.banned_users == ['*!*troll@203.0.113.7']
    conn.reset_mock()
    b.process_event(conn, event('newnick', '#test', '!ping', user='~troll', host='203.0.113.7'))
    conn.privmsg.assert_not_called()
    # someone else on the same shared host is not caught
    b.process_event(conn, event('friend', '#test', '!ping', user='friend', host='203.0.113.7'))
    assert replies(conn) == ['pong']


def test_ban_unseen_nick_falls_back_to_nick(make_bot, conn):
    b = make_bot(ops=['mal'])
    b.process_event(conn, event('mal', '#test', '!ban ghost'))
    assert b.banned_users == ['ghost']
    assert "nick only" in replies(conn)[0]


def test_ban_explicit_mask_or_account(make_bot, conn):
    b = make_bot(ops=['mal'])
    b.process_event(conn, event('mal', '#test', '!ban *!*@203.0.113.* $a:troll'))
    assert b.banned_users == ['*!*@203.0.113.*', '$a:troll']


def test_unban_nick_removes_their_account_ban(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('ping', PING_PLUGIN), ops=['mal'])
    b.process_event(conn, event('troll', '#test', 'hi', account='trollacct'))
    b.process_event(conn, event('mal', '#test', '!ban troll'))
    conn.reset_mock()
    b.process_event(conn, event('mal', '#test', '!unban troll'))
    assert b.banned_users == []
    assert replies(conn) == ['mal: removed ban on $a:trollacct']


def test_unban_unknown_says_so(make_bot, conn):
    b = make_bot(ops=['mal'])
    b.process_event(conn, event('mal', '#test', '!unban nobody'))
    assert replies(conn) == ['mal: no ban found for nobody']


def test_unban_config_ban_warns_it_comes_back(make_bot, conn):
    b = make_bot(ops=['mal'], banned_users=['troll'])
    b.process_event(conn, event('mal', '#test', '!unban troll'))
    assert "in the config file, so it'll be back after a restart" in replies(conn)[0]


def test_banlist_is_ops_only(make_bot, conn):
    b = make_bot(ops=['mal'], banned_users=['*!*@203.0.113.7'])
    b.process_event(conn, event('someone', '#test', '!banlist'))
    conn.privmsg.assert_not_called()
    b.process_event(conn, event('mal', '#test', '!banlist'))
    assert replies(conn) == ['currently banned: *!*@203.0.113.7']


# saved bans

def test_bans_are_saved_and_loaded(make_bot, tmp_path, conn):
    b = make_bot(ops=['mal'], banned_users=['fromconfig'])
    b.process_event(conn, event('troll', '#test', 'hi', account='trollacct'))
    b.process_event(conn, event('mal', '#test', '!ban troll'))
    # only bans made with !ban go in the file, config bans stay in the config
    assert json.loads((tmp_path / 'bans.json').read_text()) == ['$a:trollacct']
    again = make_bot(banned_users=['fromconfig'])
    assert again.banned_users == ['fromconfig', '$a:trollacct']


def test_broken_ban_file_stops_bot_starting(make_bot, tmp_path):
    (tmp_path / 'bans.json').write_text('not json')
    with pytest.raises(ValueError, match="couldn't read ban file"):
        make_bot()


def test_empty_ban_file_option_keeps_bans_in_memory(make_bot, tmp_path, monkeypatch, conn):
    monkeypatch.chdir(tmp_path)
    b = make_bot(ops=['mal'], ban_file='')
    b.process_event(conn, event('mal', '#test', '!ban troll'))
    assert b.banned_users == ['troll']
    assert list(tmp_path.glob('*.json')) == []


# ops by account

def test_op_by_account(make_bot, conn):
    b = make_bot(ops=['$a:mal'])
    b.process_event(conn, event('anynick', '#test', '!ops', account='mal'))
    assert replies(conn) == ['current ops: $a:mal']
    conn.reset_mock()
    # someone using the nick mal without the account is not an op
    b.process_event(conn, event('mal', '#test', '!ops'))
    conn.privmsg.assert_not_called()


def test_plugins_get_is_op(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('amiop', (
        "import pinhook.plugin as p\n"
        "@p.command('!amiop')\n"
        "def amiop(msg): return p.message(str(msg.is_op))\n"
    )), ops=['$a:mal'])
    b.process_event(conn, event('anynick', '#test', '!amiop', account='mal'))
    b.process_event(conn, event('mal', '#test', '!amiop'))
    assert replies(conn) == ['True', 'False']


# require_account

def test_require_account_ignores_logged_out_users(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('ping', PING_PLUGIN), require_account=True)
    b.process_event(conn, event('guest', '#test', '!ping'))
    b.process_event(conn, event('member', '#test', '!ping', account='member'))
    assert replies(conn) == ['pong']


def test_require_account_warns_when_server_has_no_account_tags(make_bot, conn, caplog):
    b = make_bot(require_account=True)
    b.on_welcome(conn, SimpleNamespace())
    assert 'require_account is on but this server' in caplog.text


# capability negotiation

def cap(*arguments):
    return SimpleNamespace(arguments=list(arguments))


def test_cap_ls_is_sent_before_nick_and_user(make_bot):
    b = make_bot()
    sock = mock.Mock()
    b.cap_factory(lambda address: sock)(('localhost', 6667))
    sock.send.assert_called_once_with(b'CAP LS 302\r\n')


def test_requests_account_tag_when_server_has_it(make_bot, conn):
    b = make_bot()
    b.cap_factory(lambda address: mock.Mock())(('localhost', 6667))
    b.on_cap(conn, cap('LS', '*', 'multi-prefix sasl=PLAIN'))
    conn.cap.assert_not_called()
    b.on_cap(conn, cap('LS', 'account-tag away-notify'))
    conn.cap.assert_called_once_with('REQ', 'account-tag')
    b.on_cap(conn, cap('ACK', 'account-tag'))
    conn.cap.assert_called_with('END')
    assert b.account_tag


def test_ends_negotiation_when_server_lacks_account_tag(make_bot, conn):
    b = make_bot()
    b.cap_factory(lambda address: mock.Mock())(('localhost', 6667))
    b.on_cap(conn, cap('LS', 'multi-prefix'))
    conn.cap.assert_called_once_with('END')
    assert not b.account_tag


def test_nak_ends_negotiation(make_bot, conn):
    b = make_bot()
    b.cap_factory(lambda address: mock.Mock())(('localhost', 6667))
    b.on_cap(conn, cap('LS', 'account-tag'))
    b.on_cap(conn, cap('NAK', 'account-tag'))
    conn.cap.assert_called_with('END')
    assert not b.account_tag


def test_cap_replies_after_negotiation_are_ignored(make_bot, conn):
    # e.g. TwitchBot asking for its own caps after connecting
    b = make_bot()
    b.on_cap(conn, cap('ACK', 'twitch.tv/tags'))
    conn.cap.assert_not_called()


def test_seen_list_is_capped(make_bot, conn):
    b = make_bot()
    for i in range(1100):
        b.remember('nick{}'.format(i), 'user', 'host', None)
    assert len(b.seen) == 1000
    assert 'nick0' not in b.seen and 'nick1099' in b.seen
