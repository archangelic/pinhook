"""Which messages run which commands: prefixes and addressing the bot by nick."""
import json

import pytest

from pinhook.testing import TestBot

PING = ("@p.command('!ping')\n"
        "def ping(msg): return p.message('pong')\n")
ECHO = ("@p.listener('echo')\n"
        "def echo(msg): return p.message('heard ' + msg.text)\n")


def bot_with(tmp_path, *plugins, **options):
    for i, code in enumerate(plugins):
        (tmp_path / 'p{}.py'.format(i)).write_text('import pinhook.plugin as p\n' + code)
    return TestBot(plugin_dir=str(tmp_path), nickname='pinbot', **options)


# prefixes

def test_a_bot_can_have_several_prefixes(tmp_path):
    bot = bot_with(tmp_path, PING, cmd_prefix=['!', '.'], ops=['mal'])
    assert bot.say('!ping') == ['pong']
    assert bot.say('.ping') == ['pong']
    assert bot.say('.ops', nick='mal') == ['current ops: mal']


def test_commands_written_without_a_prefix_use_the_bots(tmp_path):
    bot = bot_with(tmp_path, "@p.command('ping')\ndef ping(msg): return p.message('pong')\n")
    assert bot.say('!ping') == ['pong']
    assert bot.say('ping') == []


def test_a_bad_prefix_is_a_clear_error(tmp_path):
    with pytest.raises(ValueError, match='cmd_prefix must be a prefix'):
        bot_with(tmp_path, cmd_prefix=[])


def test_use_prefix_for_plugins_is_retired_with_a_warning(tmp_path, caplog):
    bot = bot_with(tmp_path, PING, use_prefix_for_plugins=True)
    assert 'use_prefix_for_plugins is retired' in caplog.text
    assert bot.say('!ping') == ['pong']


# addressing the bot by nick

@pytest.mark.parametrize('text', ['pinbot: ping', 'pinbot, ping', 'PinBot: ping', '@pinbot ping',
                                  '@pinbot: ping', 'pinbot: !ping'])
def test_addressing_the_bot_runs_a_command_without_its_prefix(tmp_path, text):
    assert bot_with(tmp_path, PING).say(text) == ['pong']


@pytest.mark.parametrize('text', ['ping', 'pinbotx: ping', 'pinbot ping', 'hey pinbot: ping'])
def test_other_messages_dont_count_as_addressing_the_bot(tmp_path, text):
    assert bot_with(tmp_path, PING).say(text) == []


def test_addressing_runs_built_in_commands_too(tmp_path):
    assert bot_with(tmp_path, ops=['mal']).say('pinbot: ops', nick='mal') == ['current ops: mal']


def test_addressed_messages_that_arent_commands_reach_listeners(tmp_path):
    assert bot_with(tmp_path, PING, ECHO).say('pinbot: how are you') == [
        'heard pinbot: how are you']


def test_addressing_can_be_turned_off(tmp_path):
    bot = bot_with(tmp_path, PING, address_by_nick=False)
    assert bot.say('pinbot: ping') == []
    assert bot.say('!ping') == ['pong']


def test_addressing_follows_the_bots_nick(tmp_path):
    bot = bot_with(tmp_path, PING)
    bot.transport.nick = 'pinbot_'
    assert bot.say('pinbot_: ping') == ['pong']
    assert bot.say('pinbot: ping') == []


# the config file

def test_config_takes_a_list_of_prefixes(tmp_path):
    from unittest import mock
    from click.testing import CliRunner
    from pinhook.cli import cli
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'nickname': 'pinbot', 'server': 'localhost',
                                'channels': ['#test'], 'cmd_prefix': ['!', '.']}))
    with mock.patch('pinhook.cli.Bot') as bot:
        assert CliRunner().invoke(cli, [str(path)]).exit_code == 0
    assert bot.call_args.kwargs['cmd_prefix'] == ['!', '.']
    path.write_text(json.dumps({'nickname': 'pinbot', 'server': 'localhost',
                                'channels': ['#test'], 'cmd_prefix': ['']}))
    with mock.patch('pinhook.cli.Bot'):
        result = CliRunner().invoke(cli, [str(path)])
    assert result.exit_code != 0
    assert 'should be a prefix' in result.output
