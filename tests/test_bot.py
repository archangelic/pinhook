import ssl
from types import SimpleNamespace
from unittest import mock

from conftest import event


PING_PLUGIN = (
    "import pinhook.plugin as p\n"
    "@p.command('!ping')\n"
    "def ping(msg): return p.message('pong')\n"
)


def test_private_message_gets_reply(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('ping', PING_PLUGIN))
    b.process_event(conn, event('mal', 'pinbot', '!ping', type='privmsg'))
    conn.privmsg.assert_called_once_with('mal', 'pong')


def test_private_message_after_nick_change(make_bot, plugin_dir, conn):
    # e.g. services forced a nick change while connected
    b = make_bot(plugin_dir('ping', PING_PLUGIN))
    conn.get_nickname.return_value = 'pinbot_'
    b.process_event(conn, event('mal', 'pinbot_', '!ping', type='privmsg'))
    conn.privmsg.assert_called_once_with('mal', 'pong')


ECHO_PLUGIN = (
    "import pinhook.plugin as p\n"
    "@p.listener('echo')\n"
    "def echo(msg): return p.message(msg.text)\n"
)


def test_ignores_own_nick(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('echo', ECHO_PLUGIN))
    b.process_event(conn, event('pinbot', '#test', 'hello'))
    conn.privmsg.assert_not_called()


def test_ignores_own_nick_any_case(make_bot, plugin_dir, conn):
    # twitch sends nicks lowercase even if the bot was set up as PinBot
    b = make_bot(plugin_dir('echo', ECHO_PLUGIN))
    conn.get_nickname.return_value = 'PinBot'
    b.process_event(conn, event('pinbot', '#test', 'hello'))
    conn.privmsg.assert_not_called()


def test_ignores_own_nick_after_nick_change(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('echo', ECHO_PLUGIN))
    conn.get_nickname.return_value = 'pinbot_'
    b.process_event(conn, event('pinbot_', '#test', 'hello'))
    conn.privmsg.assert_not_called()


def test_plugins_get_current_botnick(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('whoami', (
        "import pinhook.plugin as p\n"
        "@p.command('!whoami')\n"
        "def whoami(msg): return p.message(msg.botnick)\n"
    )))
    conn.get_nickname.return_value = 'pinbot_'
    b.process_event(conn, event('mal', '#test', '!whoami'))
    conn.privmsg.assert_called_once_with('#test', 'pinbot_')


def test_banned_user_cannot_use_plugins(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('ping', PING_PLUGIN), banned_users=['troll'])
    b.process_event(conn, event('troll', '#test', '!ping'))
    conn.privmsg.assert_not_called()


def test_banned_user_cannot_use_internal_commands(make_bot, conn):
    b = make_bot(banned_users=['troll'])
    b.process_event(conn, event('troll', '#test', '!banlist'))
    conn.privmsg.assert_not_called()


def test_ban_command_blocks_user(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('ping', PING_PLUGIN), ops=['mal'])
    b.process_event(conn, event('mal', '#test', '!ban troll'))
    conn.reset_mock()
    b.process_event(conn, event('troll', '#test', '!ping'))
    conn.privmsg.assert_not_called()


def test_unbanned_user_can_use_plugins(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('ping', PING_PLUGIN), ops=['mal'], banned_users=['troll'])
    b.process_event(conn, event('mal', '#test', '!unban troll'))
    conn.reset_mock()
    b.process_event(conn, event('troll', '#test', '!ping'))
    conn.privmsg.assert_called_once_with('#test', 'pong')


def featurelist(*features):
    return SimpleNamespace(arguments=list(features) + ['are supported by this server'])


def test_sets_bot_mode_from_server(make_bot, conn):
    b = make_bot()
    b.on_featurelist(conn, featurelist('CHANTYPES=#', 'BOT=B'))
    conn.mode.assert_called_once_with('pinbot', '+B')


def test_uses_server_bot_mode_letter(make_bot, conn):
    b = make_bot()
    b.on_featurelist(conn, featurelist('BOT=b'))
    conn.mode.assert_called_once_with('pinbot', '+b')


def test_no_bot_mode_when_server_does_not_support_it(make_bot, conn):
    b = make_bot()
    b.on_featurelist(conn, featurelist('CHANTYPES=#', 'NETWORK=Libera.Chat'))
    conn.mode.assert_not_called()


def test_bot_mode_can_be_turned_off(make_bot, conn):
    b = make_bot(bot_mode=False)
    b.on_featurelist(conn, featurelist('BOT=B'))
    conn.mode.assert_not_called()


def test_command_returning_string_does_not_crash(make_bot, plugin_dir, conn, caplog):
    b = make_bot(plugin_dir('bad', (
        "import pinhook.plugin as p\n"
        "@p.command('!bad')\n"
        "def bad(msg): return 'plain string'\n"
    )))
    b.process_event(conn, event('mal', '#test', '!bad'))
    conn.privmsg.assert_not_called()
    assert 'issue with command !bad' in caplog.text
    assert 'got str' in caplog.text


def test_listener_returning_string_does_not_stop_others(make_bot, plugin_dir, conn, caplog):
    plugin_dir('bad_listener', (
        "import pinhook.plugin as p\n"
        "@p.listener('bad')\n"
        "def bad(msg): return 'plain string'\n"
    ))
    b = make_bot(plugin_dir('echo', ECHO_PLUGIN))
    b.process_event(conn, event('mal', '#test', 'hello'))
    conn.privmsg.assert_called_once_with('#test', 'hello')
    assert 'issue with listener bad' in caplog.text


def test_list_output_with_newline_sends_each_line(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('multi', (
        "import pinhook.plugin as p\n"
        "@p.command('!multi')\n"
        "def multi(msg): return p.message(['one\\ntwo', 'three'])\n"
    )))
    b.process_event(conn, event('mal', '#test', '!multi'))
    assert [c.args for c in conn.privmsg.call_args_list] == [
        ('#test', 'one'), ('#test', 'two'), ('#test', 'three')]


def ssl_wrapper(make_bot, **kwargs):
    with mock.patch('irc.connection.Factory') as factory:
        make_bot(**kwargs)
    return factory.call_args.kwargs['wrapper']


def test_ssl_verifies_certificate_by_default(make_bot):
    wrapper = ssl_wrapper(make_bot, ssl_required=True)
    context = wrapper.func.__self__
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert wrapper.keywords['server_hostname'] == 'localhost'


def test_ssl_verify_can_be_turned_off(make_bot):
    wrapper = ssl_wrapper(make_bot, ssl_required=True, ssl_verify=False)
    context = wrapper.func.__self__
    assert context.verify_mode == ssl.CERT_NONE
    assert not context.check_hostname
