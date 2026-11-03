import pathlib

import pytest

from pinhook.testing import PluginError, Sent, TestBot

EXAMPLE_PLUGINS = str(pathlib.Path(__file__).parent.parent / 'examples' / 'irc' / 'plugins')


def plugins(tmp_path, **files):
    for name, code in files.items():
        (tmp_path / '{}.py'.format(name)).write_text(code)
    return str(tmp_path)


ECHO = (
    "import pinhook.plugin as p\n"
    "@p.command('!echo')\n"
    "def echo(msg): return p.message(msg.arg)\n"
    "@p.command('!wave')\n"
    "def wave(msg): return p.action('waves at {}'.format(msg.nick))\n"
)


# the example plugin, tested the way a plugin author would

def test_example_dice_plugin():
    bot = TestBot(plugin_dir=EXAMPLE_PLUGINS)
    assert bot.say('!roll 1d1') == ['1']
    assert bot.say('!roll 2d1+3') == ['1, 1 = 2 + 3 = 5']
    assert bot.say('!roll lots', nick='mal') == ['mal: improper format, should be NdN+N']


# talking to the bot

def test_say_returns_replies_in_that_channel(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, echo=ECHO))
    assert bot.say('!echo hi') == ['hi']
    assert bot.say('!wave', nick='mal') == ['waves at mal']
    assert bot.sent == [Sent('message', '#test', 'hi'), Sent('action', '#test', 'waves at mal')]


def test_say_in_another_channel(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, echo=ECHO))
    assert bot.say('!echo hi', channel='#other') == ['hi']
    assert 'tester' in bot.channels['#other'].users()


def test_private_messages_reply_to_the_sender(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, echo=ECHO))
    assert bot.private('!echo psst', nick='mal') == ['psst']
    assert bot.sent[-1].target == 'mal'


def test_actions_reach_listeners(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, seen=(
        "import pinhook.plugin as p\n"
        "@p.listener('seen')\n"
        "def seen(msg): return p.message('{} {}'.format(msg.msg_type, msg.text))\n"
    )))
    assert bot.action('dances') == ['action dances']


def test_help_goes_to_the_sender_privately(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, echo=ECHO))
    assert bot.say('!help', nick='mal') == []
    assert bot.sent_to('mal') == ['commands: !echo, !help, !wave | !help <command> for more']


def test_flood_pauses_are_recorded_not_waited(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, lines=(
        "import pinhook.plugin as p\n"
        "@p.command('!lines')\n"
        "def lines(msg): return p.message(['1', '2', '3', '4', '5', '6'])\n"
    )))
    assert bot.say('!lines') == ['1', '2', '3', '4', '5', '6']
    assert bot.pauses == [2, 2]


# ops and bans work as on a real server

def test_ops_by_account(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, echo=ECHO), ops=['$a:mal'])
    assert bot.say('!ops', nick='anyone', account='mal') == ['current ops: $a:mal']
    assert bot.say('!ops', nick='mal') == []


def test_bans_by_host(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, echo=ECHO), banned_users=['*!*@bad.example'])
    assert bot.say('!echo hi', host='bad.example') == []
    assert bot.say('!echo hi', host='good.example') == ['hi']


def test_join_command_adds_the_channel(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, echo=ECHO), ops=['mal'])
    bot.say('!join #new', nick='mal')
    assert '#new' in bot.channels


def test_quit_command_stops_the_bot(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, echo=ECHO), ops=['mal'])
    with pytest.raises(SystemExit):
        bot.say('!quit bye', nick='mal')
    assert bot.quit_message == 'bye'


# plugin mistakes fail the test

def test_plugin_exception_fails_the_test(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, broken=(
        "import pinhook.plugin as p\n"
        "@p.command('!broken')\n"
        "def broken(msg): return 1 / 0\n"
    )))
    with pytest.raises(PluginError, match='issue with command !broken') as error:
        bot.say('!broken')
    assert isinstance(error.value.__cause__, ZeroDivisionError)


def test_returning_a_plain_string_fails_the_test(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, plain=(
        "import pinhook.plugin as p\n"
        "@p.command('!plain')\n"
        "def plain(msg): return 'oops'\n"
    )))
    with pytest.raises(PluginError) as error:
        bot.say('!plain')
    assert 'got str' in str(error.value.__cause__)


def test_plugin_that_wont_load_fails_at_startup(tmp_path):
    with pytest.raises(PluginError, match='could not load plugin') as error:
        TestBot(plugin_dir=plugins(tmp_path, typo="import pinhook.plugin as p\ndef broken(:\n"))
    assert isinstance(error.value.__cause__, SyntaxError)


def test_writes_no_files(tmp_path, monkeypatch):
    plugin_dir = tmp_path / 'plugins'
    plugin_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    bot = TestBot(plugin_dir=plugins(plugin_dir, echo=ECHO), ops=['mal'])
    bot.say('!ban troll', nick='mal')
    # no log file and no ban file, only the plugins folder
    assert sorted(p.name for p in tmp_path.iterdir()) == ['plugins']
