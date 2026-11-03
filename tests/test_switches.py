"""Turning plugins on and off per channel, with plugin_channels and !enable and !disable."""
import json

from pinhook.testing import TestBot

from wire import Wire

PING = ("import pinhook.plugin as p\n"
        "@p.command('!ping')\n"
        "def ping(msg): return p.message('pong')\n")


def bot_with(tmp_path, **options):
    (tmp_path / 'dice.py').write_text(PING)
    return TestBot(plugin_dir=str(tmp_path), ops=['mal'], **options)


def test_disable_turns_a_plugin_off_in_this_channel_only(tmp_path):
    bot = bot_with(tmp_path)
    assert bot.say('!disable dice', nick='mal') == ["mal: 'dice' disabled in #test"]
    assert bot.say('!ping') == []
    assert bot.say('!ping', channel='#other') == ['pong']
    assert bot.private('!ping') == ['pong']
    assert bot.say('!enable dice', nick='mal') == ["mal: 'dice' enabled in #test"]
    assert bot.say('!ping') == ['pong']


def test_all_turns_it_off_everywhere(tmp_path):
    bot = bot_with(tmp_path)
    assert bot.say('!disable dice all', nick='mal') == ["mal: 'dice' disabled everywhere"]
    assert bot.say('!ping', channel='#other') == []
    assert bot.private('!ping') == []
    assert bot.say('!enable dice', nick='mal') == ["mal: 'dice' enabled in #test"]
    assert bot.say('!ping') == ['pong']
    assert bot.say('!ping', channel='#other') == []


def test_from_a_private_message_it_means_everywhere(tmp_path):
    bot = bot_with(tmp_path)
    bot.private('!disable dice', nick='mal')
    assert bot.say('!ping') == []


def test_another_channel_can_be_named(tmp_path):
    bot = bot_with(tmp_path)
    bot.private('!disable dice #games', nick='mal')
    assert bot.say('!ping', channel='#games') == []
    assert bot.say('!ping') == ['pong']


def test_commands_and_listeners_can_be_switched_by_name(tmp_path):
    bot = bot_with(tmp_path)
    assert bot.say('!disable !ping', nick='mal') == ["mal: '!ping' disabled in #test"]
    assert bot.say('!ping') == []
    assert bot.say('!enable ping', nick='mal') == ["mal: 'ping' enabled in #test"]
    assert bot.say('!ping') == ['pong']


def test_a_message_handler_is_listed_and_switched_by_its_name(tmp_path):
    (tmp_path / 'thanks.py').write_text(
        "from pinhook import on\n\n\n"
        "@on('message')\n"
        "async def thanks(ctx):\n"
        "    await ctx.reply('any time')\n")
    bot = bot_with(tmp_path)
    assert 'listeners: thanks' in ' '.join(bot.private('!help'))
    assert bot.say('!disable thanks', nick='mal') == ["mal: 'thanks' disabled in #test"]
    assert bot.say('thanks gamebot') == []
    assert bot.say('!ping') == ['pong']
    bot.say('!enable thanks', nick='mal')
    assert bot.say('thanks gamebot') == ['any time']


def test_a_handler_can_be_named(tmp_path):
    (tmp_path / 'polite.py').write_text(
        "from pinhook import on\n\n\n"
        "@on('message', name='thanker')\n"
        "async def thanks(ctx):\n"
        "    await ctx.reply('any time')\n")
    bot = bot_with(tmp_path)
    assert 'listeners: thanker' in ' '.join(bot.private('!help'))
    assert bot.say('!disable thanks', nick='mal') == ["mal: 'thanks' not found"]
    bot.say('!disable thanker', nick='mal')
    assert bot.say('thanks gamebot') == []


def test_saying_so_twice_says_it_already_is(tmp_path):
    bot = bot_with(tmp_path)
    bot.say('!disable dice', nick='mal')
    assert bot.say('!disable dice', nick='mal') == ["mal: 'dice' is already disabled in #test"]
    assert bot.say('!enable dice all', nick='mal') == ["mal: 'dice' enabled everywhere"]
    assert bot.say('!enable dice all', nick='mal') == ["mal: 'dice' is already enabled everywhere"]


def test_bad_arguments_get_the_usage_line(tmp_path):
    bot = bot_with(tmp_path)
    usage = ['mal: usage: !disable <plugin> [all | #channel]']
    assert bot.say('!disable', nick='mal') == usage
    assert bot.say('!disable dice somewhere', nick='mal') == usage
    assert bot.say('!disable nope', nick='mal') == ["mal: 'nope' not found"]


def test_only_ops_can_switch_plugins(tmp_path):
    bot = bot_with(tmp_path)
    assert bot.say('!disable dice', nick='troll') == []
    assert bot.say('!ping') == ['pong']


def test_plugin_channels_keeps_a_plugin_to_its_channels(tmp_path):
    bot = bot_with(tmp_path, plugin_channels={'dice': ['#Games']})
    assert bot.say('!ping', channel='#games') == ['pong']
    assert bot.say('!ping') == []
    assert bot.private('!ping') == ['pong']
    # !enable in a channel adds it there
    bot.say('!enable dice', nick='mal')
    assert bot.say('!ping') == ['pong']


def test_switches_last_through_reload_and_restart(tmp_path):
    (tmp_path / 'plugins').mkdir()
    (tmp_path / 'plugins' / 'dice.py').write_text(PING)
    w = Wire(tmp_path, ops=['mal']).ready()
    w.say('!disable dice', nick='mal')
    w.say('!reload', nick='mal')
    assert w.say('!ping') == []
    saved = json.loads((tmp_path / 'data' / 'pinbot.plugins.json').read_text())
    assert saved == {'dice': {'all': None, 'channels': {'#test': False}}}
    again = Wire(tmp_path, ops=['mal']).ready()
    assert again.say('!ping') == []
    assert again.say('!ping', channel='#other') == ['pong']
