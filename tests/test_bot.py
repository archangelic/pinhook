import logging
import ssl
from types import SimpleNamespace
from unittest import mock

import pytest

from pinhook import bot as pinhook_bot

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


def nick_in_use(nick, target='*'):
    return SimpleNamespace(target=target, arguments=[nick, 'Nickname is already in use'])


def test_retries_with_new_nick_when_taken(make_bot, conn):
    b = make_bot()
    b.on_nicknameinuse(conn, nick_in_use('pinbot'))
    conn.nick.assert_called_once_with('pinbot_')


def test_keeps_retrying_when_new_nick_also_taken(make_bot, conn):
    # get_nickname still says pinbot until the server accepts a nick
    b = make_bot()
    b.on_nicknameinuse(conn, nick_in_use('pinbot_'))
    conn.nick.assert_called_once_with('pinbot__')


def test_failed_nick_change_after_connecting_keeps_nick(make_bot, conn):
    b = make_bot()
    b.on_nicknameinuse(conn, nick_in_use('othernick', target='pinbot'))
    conn.nick.assert_not_called()


def test_log_level_is_case_insensitive(make_bot):
    b = make_bot(log_level='INFO')
    assert b.logger.level == logging.INFO


def test_log_level_accepts_warn_and_warning(make_bot):
    assert make_bot(log_level='warn').logger.level == logging.WARNING
    assert make_bot(log_level='warning').logger.level == logging.WARNING


def test_bad_log_level_gives_clear_error(make_bot):
    with pytest.raises(ValueError, match='log_level must be one of'):
        make_bot(log_level='verbose')


def test_log_level_off_disables_logging(make_bot, tmp_path, caplog):
    b = make_bot(log_level='off')
    b.logger.error('should not appear')
    assert 'should not appear' not in caplog.text
    assert not (tmp_path / 'bot.log').exists()


def test_logging_works_again_after_off(make_bot, caplog):
    make_bot(log_level='off')
    b = make_bot(log_level='info')
    b.logger.error('should appear')
    assert 'should appear' in caplog.text


def test_enable_after_plugin_deleted_says_not_found(make_bot, plugin_dir, tmp_path, conn):
    b = make_bot(plugin_dir('ping', PING_PLUGIN), ops=['mal'])
    (tmp_path / 'ping.py').unlink()
    b.process_event(conn, event('mal', '#test', '!reload'))
    conn.reset_mock()
    b.process_event(conn, event('mal', '#test', '!enable !ping'))
    conn.privmsg.assert_called_once_with('#test', "mal: '!ping' not found")


def test_disable_unknown_plugin_says_not_found(make_bot, conn):
    b = make_bot(ops=['mal'])
    b.process_event(conn, event('mal', '#test', '!disable nope'))
    conn.privmsg.assert_called_once_with('#test', "mal: 'nope' not found")


def test_op_with_no_nick_shows_usage(make_bot, conn):
    b = make_bot(ops=['mal'])
    b.process_event(conn, event('mal', '#test', '!op'))
    assert b.ops == ['mal']
    conn.privmsg.assert_called_once_with('#test', 'mal: usage: !op <nick>')


def test_ban_with_no_nick_shows_usage(make_bot, conn):
    b = make_bot(ops=['mal'])
    b.process_event(conn, event('mal', '#test', '!ban'))
    assert b.banned_users == []
    conn.privmsg.assert_called_once_with('#test', 'mal: usage: !ban <nick>')


def test_op_ignores_extra_spaces_and_duplicates(make_bot, conn):
    b = make_bot(ops=['mal'])
    b.process_event(conn, event('mal', '#test', '!op  alice   mal'))
    assert b.ops == ['mal', 'alice']


MESSAGE_ARGS = dict(bot=None, channel='#test', nick='mal', user='user', botnick='pinbot', ops=[],
                    logger=None, action=None, privmsg=None, notice=None, msg_type='message')


def test_message_needs_cmd_or_text():
    with pytest.raises(TypeError, match='missing cmd or text'):
        pinhook_bot.Bot.Message(**MESSAGE_ARGS)


def test_message_with_cmd_and_text_is_fine():
    msg = pinhook_bot.Bot.Message(cmd='!ping', arg='', text='!ping', **MESSAGE_ARGS)
    assert msg.cmd == '!ping' and msg.text == '!ping'


def test_quit_command_disconnects_and_exits(make_bot, conn):
    b = make_bot(ops=['mal'])
    with pytest.raises(SystemExit):
        b.process_event(conn, event('mal', '#test', '!quit bye'))
    conn.quit.assert_called_once_with('bye')
