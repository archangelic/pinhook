import pytest

from pinhook import plugin
from pinhook.testing import PluginError, TestBot


def bot_with(tmp_path, nickname='testbot', **files):
    for name, code in files.items():
        (tmp_path / (name + '.py')).write_text('import pinhook.plugin as p\n' + code)
    return TestBot(plugin_dir=str(tmp_path), nickname=nickname)


def test_command_hide_option(tmp_path):
    bot = bot_with(tmp_path, hidden="@p.command('!secret', hide=True)\ndef secret(msg): pass\n")
    assert bot.registry.commands['secret'].hide


def test_command_not_hidden_by_default(tmp_path):
    bot = bot_with(tmp_path, visible="@p.command('!visible')\ndef visible(msg): pass\n")
    assert not bot.registry.commands['visible'].hide


def test_message_splits_string_lines():
    assert plugin.message('one\ntwo').msg == ['one', 'two']


def test_message_splits_lines_inside_list():
    assert plugin.message(['one\ntwo', 'three']).msg == ['one', 'two', 'three']


def test_action_splits_lines_inside_list():
    assert plugin.action(('one\r\ntwo',)).msg == ['one', 'two']


def test_reload_picks_up_plugin_changes(tmp_path):
    bot = bot_with(tmp_path, changing="@p.command('!cmd', help_text='old')\ndef cmd(msg): pass\n")
    bot_with(tmp_path, changing="@p.command('!cmd', help_text='new')\ndef cmd(msg): pass\n")
    bot.registry.load(bot.plugin_dir)
    assert bot.registry.commands['cmd'].help_text == 'new'


def test_reload_never_uses_a_stale_bytecode_cache(tmp_path):
    # an edit that keeps the file's size, within the same second, is still picked up
    import os
    path = tmp_path / 'same.py'
    path.write_text("import pinhook.plugin as p\n"
                    "@p.command('!a', help_text='aaa')\ndef a(m): pass\n")
    stamp = os.stat(path).st_mtime
    bot = TestBot(plugin_dir=str(tmp_path))
    path.write_text("import pinhook.plugin as p\n"
                    "@p.command('!a', help_text='bbb')\ndef a(m): pass\n")
    os.utime(path, (stamp, stamp))
    bot.registry.load(bot.plugin_dir)
    assert bot.registry.commands['a'].help_text == 'bbb'
    assert not (tmp_path / '__pycache__').exists()


def test_plugin_named_like_stdlib_module_does_not_replace_it(tmp_path):
    import json
    json_file = json.__file__
    bot = bot_with(tmp_path, json="@p.command('!j')\ndef j(msg): pass\n")
    assert 'j' in bot.registry.commands
    assert json.__file__ == json_file
    assert not hasattr(json, 'j')


def test_reload_removes_deleted_plugins(tmp_path):
    bot = bot_with(tmp_path, gone="@p.command('!gone')\ndef gone(msg): pass\n")
    (tmp_path / 'gone.py').unlink()
    bot.registry.load(bot.plugin_dir)
    assert 'gone' not in bot.registry.commands
    assert 'gone' not in bot.registry.plugins


def test_reload_keeps_disabled_plugins_disabled(tmp_path):
    bot = TestBot(plugin_dir=str(tmp_path), ops=['mal'])
    bot_with(tmp_path, stays="@p.command('!stays')\ndef stays(msg): return p.message('here')\n")
    bot.say('!reload', nick='mal')
    assert bot.say('!disable !stays', nick='mal') == ["mal: '!stays' disabled in #test"]
    bot.say('!reload', nick='mal')
    assert bot.say('!stays') == []


# each bot's own plugins

def test_plugins_load_under_the_bots_own_module_name(tmp_path):
    import sys
    bot_with(tmp_path, nickname='Dice-Bot', dice="@p.command('!roll')\ndef roll(msg): pass\n")
    assert 'pinhook_plugins.dice_bot.dice' in sys.modules


def test_two_bots_loading_one_folder_keep_separate_plugins_and_globals(tmp_path):
    counter = ("count = 0\n"
               "@p.command('!count')\n"
               "def bump(msg):\n"
               "    global count\n"
               "    count += 1\n"
               "    return p.message(str(count))\n")
    one = bot_with(tmp_path, nickname='one', counter=counter)
    two = TestBot(plugin_dir=str(tmp_path), nickname='two')
    assert one.say('!count') == ['1']
    assert one.say('!count') == ['2']
    assert two.say('!count') == ['1']
    assert one.registry.commands['count'] is not two.registry.commands['count']


def test_a_plugin_can_import_another_by_its_bot_module_name(tmp_path):
    (tmp_path / 'aaa_words.py').write_text("WORD = 'pong'\n")
    bot = bot_with(tmp_path, nickname='pinger', ping=(
        "from pinhook_plugins.pinger import aaa_words\n"
        "@p.command('!ping')\n"
        "def ping(msg): return p.message(aaa_words.WORD)\n"))
    assert bot.say('!ping') == ['pong']


# names

def test_two_plugins_with_the_same_command_is_a_load_error_naming_both(tmp_path):
    (tmp_path / 'a.py').write_text(
        "import pinhook.plugin as p\n@p.command('!roll')\ndef roll(msg): pass\n")
    (tmp_path / 'b.py').write_text(
        "import pinhook.plugin as p\n@p.command('!roll')\ndef roll(msg): pass\n")
    with pytest.raises(PluginError, match='plugin b registers command !roll, which plugin a '
                                          'already has'):
        TestBot(plugin_dir=str(tmp_path))


def test_a_plugin_cant_take_a_built_in_commands_name(tmp_path):
    (tmp_path / 'help.py').write_text(
        "import pinhook.plugin as p\n@p.command('!help')\ndef h(msg): pass\n")
    with pytest.raises(PluginError, match='which the bot itself already has'):
        TestBot(plugin_dir=str(tmp_path))


def test_a_clash_leaves_none_of_the_second_plugin_loaded(tmp_path, caplog):
    (tmp_path / 'a.py').write_text(
        "import pinhook.plugin as p\n@p.command('!roll')\ndef roll(msg): pass\n")
    (tmp_path / 'b.py').write_text(
        "import pinhook.plugin as p\n"
        "@p.command('!flip')\ndef flip(msg): pass\n"
        "@p.command('!roll')\ndef roll(msg): pass\n")
    from pinhook import bot as pinhook_bot
    bot = pinhook_bot.Bot(['#test'], 'pinbot', 'localhost', plugin_dir=str(tmp_path),
                          log_file=str(tmp_path / 'bot.log'), ban_file='')
    assert 'flip' not in bot.registry.commands
    assert 'could not load plugin b' in caplog.text


def test_commands_with_another_prefix_still_answer_to_their_word(tmp_path):
    bot = bot_with(tmp_path, weather=(
        "@p.command('.weather')\ndef weather(msg): return p.message('sunny')\n"))
    assert bot.say('.weather') == ['sunny']
    assert bot.say('!weather') == []


def test_removed_decorators_fail_the_plugin_with_the_replacement(tmp_path):
    with pytest.raises(PluginError, match=r"use @command\('!old'\) instead"):
        bot_with(tmp_path, old="@p.register('!old')\ndef old(msg): pass\n")


# listeners

def test_every_listener_gets_to_answer(tmp_path):
    bot = bot_with(tmp_path, echo=(
        "@p.listener('one')\ndef one(msg): return p.message('one')\n"
        "@p.listener('two')\ndef two(msg): return p.message('two')\n"))
    assert sorted(bot.say('hello')) == ['one', 'two']


def test_msg_bot_only_has_the_nick_and_channels(tmp_path):
    bot = bot_with(tmp_path, legacy=(
        "@p.command('!who')\n"
        "def who(msg): return p.message(msg.bot.nick + ' ' + ','.join(msg.bot.channels))\n"
        "@p.command('!inside')\n"
        "def inside(msg): return p.message(str(msg.bot.ops))\n"))
    with pytest.warns(DeprecationWarning):
        assert bot.say('!who') == ['testbot #test']
    with pytest.warns(DeprecationWarning), pytest.raises(PluginError, match='msg.bot.ops is gone'):
        bot.say('!inside')
