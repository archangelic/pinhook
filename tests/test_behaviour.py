"""What the bot does with messages: commands, bans, ops, output and saved data.

Checked with raw IRC lines in and out, see wire.py.
"""
import json

import pytest

from pinhook import bot as pinhook_bot

from wire import Wire, lines

PING = ("import pinhook.plugin as p\n"
        "@p.command('!ping')\n"
        "def ping(msg): return p.message('pong')\n")
KARMA = ("import pinhook.plugin as p\n"
         "@p.command('!karma')\n"
         "def karma(msg):\n"
         "    scores = msg.store.setdefault('scores', {})\n"
         "    scores[msg.arg] = scores.get(msg.arg, 0) + 1\n"
         "    return p.message('{} has {} karma'.format(msg.arg, scores[msg.arg]))\n")


def wire(tmp_path, **kwargs):
    kwargs.setdefault('plugins', {'ping': PING})
    return Wire(tmp_path, **kwargs).ready()


# bans

def test_banned_user_is_ignored_completely(tmp_path):
    w = wire(tmp_path, banned_users=['troll'], ops=['troll'])
    assert w.say('!ping', nick='troll') == []
    assert w.say('!ops', nick='troll') == []


def test_ban_ignores_nick_case(tmp_path):
    w = wire(tmp_path, banned_users=['troll'])
    assert w.say('!ping', nick='TroLL') == []


def test_ban_command_blocks_a_user(tmp_path):
    w = wire(tmp_path, ops=['mal'])
    w.say('!ban troll', nick='mal')
    assert w.say('!ping', nick='troll') == []


def test_ban_logged_in_user_bans_their_account(tmp_path):
    w = wire(tmp_path, ops=['mal'])
    w.say('hi', nick='troll', account='trollacct')
    assert w.say('!ban troll', nick='mal') == ['mal: banned troll (account trollacct)']
    assert w.bot.banned_users == ['$a:trollacct']
    assert w.say('!ping', nick='newnick', host='elsewhere', account='trollacct') == []


def test_ban_without_account_bans_user_and_host(tmp_path):
    w = wire(tmp_path, ops=['mal'])
    w.say('hi', nick='troll', user='~troll', host='203.0.113.7')
    w.say('!ban troll', nick='mal')
    assert w.bot.banned_users == ['*!*troll@203.0.113.7']
    assert w.say('!ping', nick='newnick', user='~troll', host='203.0.113.7') == []
    # someone else on the same shared host isn't caught
    assert w.say('!ping', nick='friend', user='friend', host='203.0.113.7') == ['pong']


def test_ban_unseen_nick_falls_back_to_the_nick(tmp_path):
    w = wire(tmp_path, ops=['mal'])
    assert 'nick only' in w.say('!ban ghost', nick='mal')[0]
    assert w.bot.banned_users == ['ghost']


def test_ban_explicit_mask_or_account(tmp_path):
    w = wire(tmp_path, ops=['mal'])
    w.say('!ban *!*@203.0.113.* $a:troll', nick='mal')
    assert w.bot.banned_users == ['*!*@203.0.113.*', '$a:troll']


def test_unban_by_current_nick_removes_their_account_ban(tmp_path):
    w = wire(tmp_path, ops=['mal'])
    w.say('hi', nick='troll', account='trollacct')
    w.say('!ban troll', nick='mal')
    assert w.say('!unban troll', nick='mal') == ['mal: removed ban on $a:trollacct']
    assert w.say('!ping', nick='troll', account='trollacct') == ['pong']


def test_unban_ignores_nick_case(tmp_path):
    w = wire(tmp_path, ops=['mal'], banned_users=['troll'])
    w.say('!unban Troll', nick='mal')
    assert w.bot.banned_users == []


def test_unban_unknown_says_so(tmp_path):
    assert wire(tmp_path, ops=['mal']).say('!unban nobody', nick='mal') == [
        'mal: no ban found for nobody']


def test_unban_config_ban_warns_it_comes_back(tmp_path):
    w = wire(tmp_path, ops=['mal'], banned_users=['troll'])
    assert "in the config file, so it'll be back after a restart" in w.say(
        '!unban troll', nick='mal')[0]


def test_banlist_is_ops_only(tmp_path):
    w = wire(tmp_path, ops=['mal'], banned_users=['*!*@203.0.113.7'])
    assert w.say('!banlist', nick='someone') == []
    assert w.say('!banlist', nick='mal') == ['currently banned: *!*@203.0.113.7']


def test_op_and_ban_with_no_nick_show_usage(tmp_path):
    w = wire(tmp_path, ops=['mal'])
    assert w.say('!op', nick='mal') == ['mal: usage: !op <nick>']
    assert w.say('!ban', nick='mal') == ['mal: usage: !ban <nick>']
    assert w.bot.ops == ['mal'] and w.bot.banned_users == []


def test_bans_are_saved_and_loaded(tmp_path):
    w = wire(tmp_path, ops=['mal'], banned_users=['fromconfig'])
    w.say('hi', nick='troll', account='trollacct')
    w.say('!ban troll', nick='mal')
    # only bans made with !ban go in the file, config bans stay in the config
    assert json.loads((tmp_path / 'bans.json').read_text()) == ['$a:trollacct']
    again = Wire(tmp_path, banned_users=['fromconfig'])
    assert again.bot.banned_users == ['fromconfig', '$a:trollacct']


def test_empty_ban_file_option_keeps_bans_in_memory(tmp_path):
    w = wire(tmp_path, ops=['mal'], ban_file='')
    w.say('!ban troll', nick='mal')
    assert w.bot.banned_users == ['troll']
    assert not (tmp_path / 'bans.json').exists()


# ops

def test_op_by_account_not_nick(tmp_path):
    w = wire(tmp_path, ops=['$a:mal'])
    assert w.say('!ops', nick='anynick', account='mal') == ['current ops: $a:mal']
    # someone using the nick mal without the account isn't an op
    assert w.say('!ops', nick='mal') == []


def test_ops_ignore_nick_case(tmp_path):
    w = wire(tmp_path, ops=['Mal'], plugins={'secret': (
        "import pinhook.plugin as p\n"
        "@p.command('!secret', ops=True, ops_msg='ops only')\n"
        "def secret(msg): return p.message('welcome op')\n")})
    assert w.say('!secret', nick='mal') == ['welcome op']
    assert w.say('!secret', nick='rando') == ['ops only']


def test_op_ignores_extra_spaces_and_duplicates(tmp_path):
    w = wire(tmp_path, ops=['mal'])
    w.say('!op  alice   mal', nick='mal')
    assert w.bot.ops == ['mal', 'alice']


def test_plugins_get_is_op(tmp_path):
    w = wire(tmp_path, ops=['$a:mal'], plugins={'amiop': (
        "import pinhook.plugin as p\n"
        "@p.command('!amiop')\n"
        "def amiop(msg): return p.message(str(msg.is_op))\n")})
    assert w.say('!amiop', nick='anynick', account='mal') == ['True']
    assert w.say('!amiop', nick='mal') == ['False']


def test_require_account_ignores_logged_out_users(tmp_path):
    w = wire(tmp_path, require_account=True)
    assert w.say('!ping', nick='guest') == []
    assert w.say('!ping', nick='member', account='member') == ['pong']


# built-in commands

def test_disable_and_enable_unknown_plugins_say_not_found(tmp_path):
    w = wire(tmp_path, ops=['mal'])
    assert w.say('!disable nope', nick='mal') == ["mal: 'nope' not found"]
    assert w.say('!enable nope', nick='mal') == ["mal: 'nope' not found"]


def test_enable_after_plugin_deleted_says_not_found(tmp_path):
    w = wire(tmp_path, ops=['mal'])
    (tmp_path / 'plugins' / 'ping.py').unlink()
    w.say('!reload', nick='mal')
    assert w.say('!enable !ping', nick='mal') == ["mal: '!ping' not found"]


def test_join_command_joins_the_channel(tmp_path):
    w = wire(tmp_path, ops=['mal'])
    assert 'JOIN #new key' in lines(w.message('mal', '!join #new key'))


# output

def test_plugin_returning_a_string_does_not_crash(tmp_path, caplog):
    w = wire(tmp_path, plugins={'bad': (
        "import pinhook.plugin as p\n"
        "@p.command('!bad')\n"
        "def bad(msg): return 'plain string'\n")})
    assert w.say('!bad') == []
    assert 'issue with command !bad' in caplog.text and 'got str' in caplog.text


def test_listener_returning_a_string_does_not_stop_others(tmp_path, caplog):
    w = wire(tmp_path, plugins={
        'bad': ("import pinhook.plugin as p\n"
                "@p.listener('bad')\n"
                "def bad(msg): return 'plain string'\n"),
        'echo': ("import pinhook.plugin as p\n"
                 "@p.listener('echo')\n"
                 "def echo(msg): return p.message(msg.text)\n")})
    assert w.say('hello') == ['hello']
    assert 'issue with listener bad' in caplog.text


def test_newlines_inside_list_output_send_each_line(tmp_path):
    w = wire(tmp_path, plugins={'multi': (
        "import pinhook.plugin as p\n"
        "@p.command('!multi')\n"
        "def multi(msg): return p.message(['one\\ntwo', 'three'])\n")})
    assert w.say('!multi') == ['one', 'two', 'three']


# logging

def test_plugin_loading_and_plugin_logs_go_to_their_bot(tmp_path):
    w = wire(tmp_path, plugins={'chatty': (
        "import pinhook.plugin as p\n"
        "@p.command('!chatty')\n"
        "def chatty(msg): msg.logger.info('hello from plugin')\n")})
    w.say('!chatty')
    log_text = (tmp_path / 'bot.log').read_text()
    assert 'loading plugin chatty' in log_text and 'hello from plugin' in log_text
    assert ' - bot.pinbot - ' in log_text


# saved data and files

def test_store_is_saved_to_the_data_folder_and_survives_a_restart(tmp_path):
    w = Wire(tmp_path, bot_dir=str(tmp_path), isolated=False, plugins={'karma': KARMA}).ready()
    assert w.say('!karma pinhook') == ['pinhook has 1 karma']
    assert json.loads((tmp_path / 'data' / 'karma.json').read_text()) == {'scores': {'pinhook': 1}}
    again = Wire(tmp_path, bot_dir=str(tmp_path), isolated=False).ready()
    assert again.say('!karma pinhook') == ['pinhook has 2 karma']


def test_unchanged_store_writes_nothing(tmp_path):
    w = Wire(tmp_path, bot_dir=str(tmp_path), isolated=False, plugins={'ping': PING}).ready()
    w.say('!ping')
    assert not (tmp_path / 'data').exists()


def test_broken_store_file_is_left_alone(tmp_path, caplog):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'karma.json').write_text('{"scores": ')
    w = Wire(tmp_path, bot_dir=str(tmp_path), isolated=False, plugins={'karma': KARMA}).ready()
    assert w.say('!karma pinhook') == []
    assert "couldn't read the store for karma" in caplog.text
    assert (tmp_path / 'data' / 'karma.json').read_text() == '{"scores": '


def files(folder):
    return sorted(str(p.relative_to(folder)) for p in folder.rglob('*'))


def test_without_bot_dir_files_go_where_they_did_in_1_11(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    w = pinhook_bot.Bot(['#test'], 'pinbot', 'localhost', ops=['mal'])
    Wire(bot=w, nickname='pinbot').ready().say('!ban troll', nick='mal')
    assert files(tmp_path) == ['pinbot.bans.json', 'pinbot.log', 'plugins']


def test_bot_dir_keeps_everything_in_one_folder(tmp_path):
    w = Wire(tmp_path / 'ph-bot', bot_dir=str(tmp_path / 'ph-bot'), isolated=False, ops=['mal'])
    w.ready().say('!ban troll', nick='mal')
    assert files(tmp_path / 'ph-bot') == [
        'data', 'data/pinbot.bans.json', 'logs', 'logs/pinbot.log', 'plugins']


# !reload and the config file

def test_reload_without_a_config_file_just_reloads(tmp_path):
    assert wire(tmp_path, ops=['mal']).say('!reload', nick='mal') == ['Plugins reloaded']


@pytest.mark.parametrize('new_config, reply, units', [
    ('{"units": "imperial"}', 'Plugins reloaded (and plugin_config and access from config.json)',
     'imperial'),
    (None, "Plugins reloaded, but config.json has a problem so plugin_config and access weren't "
           "changed, see the log", 'metric'),
])
def test_reload_reads_plugin_config_from_the_config_file(tmp_path, new_config, reply, units):
    from unittest import mock
    from click.testing import CliRunner
    from pinhook.cli import cli
    (tmp_path / 'plugins').mkdir()
    (tmp_path / 'plugins' / 'weather.py').write_text(
        "import pinhook.plugin as p\n"
        "@p.command('!units')\n"
        "def units(msg): return p.message(msg.config.get('units', 'none'))\n")

    def config(weather):
        return json.dumps({'nickname': 'pinbot', 'server': 'localhost', 'channels': ['#test'],
                           'ops': ['mal'], 'log_level': 'off', 'ban_file': '',
                           'bot_dir': str(tmp_path), 'plugin_config': {'weather': weather}})
    path = tmp_path / 'config.json'
    path.write_text(config({'units': 'metric'}))
    # the real pinhook command, with start() stubbed so it doesn't connect anywhere
    with mock.patch.object(pinhook_bot.Bot, 'start', autospec=True) as start:
        assert CliRunner().invoke(cli, [str(path)]).exit_code == 0
    w = Wire(bot=start.call_args.args[0]).ready()
    assert w.say('!units') == ['metric']
    path.write_text(config(json.loads(new_config)) if new_config else '{"nickname": ')
    assert w.say('!reload', nick='mal') == [reply]
    assert w.say('!units') == [units]
