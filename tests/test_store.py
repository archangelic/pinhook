import json

import pytest

from pinhook import bot as pinhook_bot
from pinhook.store import Store
from pinhook.testing import PluginError, TestBot

from conftest import event

KARMA = (
    "import pinhook.plugin as p\n"
    "@p.command('!karma')\n"
    "def karma(msg):\n"
    "    scores = msg.store.setdefault('scores', {})\n"
    "    scores[msg.arg] = scores.get(msg.arg, 0) + 1\n"
    "    return p.message('{} has {} karma'.format(msg.arg, scores[msg.arg]))\n"
    "@p.listener('karma-watch')\n"
    "def watch(msg):\n"
    "    msg.store['last_seen'] = msg.nick\n"
)

QUOTES = (
    "import pinhook.plugin as p\n"
    "@p.command('!quote')\n"
    "def quote(msg):\n"
    "    msg.store.setdefault('quotes', []).append(msg.arg)\n"
    "    return p.message('{} quotes'.format(len(msg.store['quotes'])))\n"
)


def plugin_dir(folder, **plugins):
    folder.mkdir(parents=True, exist_ok=True)
    for name, code in plugins.items():
        (folder / '{}.py'.format(name)).write_text(code)
    return str(folder)


def real_bot(bot_dir, **options):
    return pinhook_bot.Bot(['#test'], 'pinbot', 'localhost', bot_dir=str(bot_dir),
                           log_level='off', **options)


# in a TestBot

def test_store_is_kept_between_messages(tmp_path):
    bot = TestBot(plugin_dir=plugin_dir(tmp_path, karma=KARMA))
    assert bot.say('!karma pinhook') == ['pinhook has 1 karma']
    assert bot.say('!karma pinhook') == ['pinhook has 2 karma']


def test_each_plugin_file_has_its_own_store(tmp_path):
    bot = TestBot(plugin_dir=plugin_dir(tmp_path, karma=KARMA, quotes=QUOTES))
    bot.say('!karma pinhook')
    bot.say('!quote hello')
    # commands don't reach listeners, so only the command touched the karma store
    assert bot.store('karma') == {'scores': {'pinhook': 1}}
    assert bot.store('quotes') == {'quotes': ['hello']}


def test_commands_and_listeners_in_one_file_share_a_store(tmp_path):
    bot = TestBot(plugin_dir=plugin_dir(tmp_path, karma=KARMA))
    bot.say('just chatting', nick='mal')
    bot.say('!karma pinhook')
    assert bot.store('karma') == {'last_seen': 'mal', 'scores': {'pinhook': 1}}


def test_store_survives_reload(tmp_path):
    bot = TestBot(plugin_dir=plugin_dir(tmp_path, karma=KARMA), ops=['mal'])
    bot.say('!karma pinhook')
    bot.say('!reload', nick='mal')
    assert bot.say('!karma pinhook') == ['pinhook has 2 karma']


def test_non_json_value_fails_with_a_clear_message(tmp_path):
    bot = TestBot(plugin_dir=plugin_dir(tmp_path, when=(
        "import datetime\nimport pinhook.plugin as p\n"
        "@p.command('!when')\n"
        "def when(msg): msg.store['at'] = datetime.datetime.now()\n"
    )))
    with pytest.raises(PluginError) as error:
        bot.say('!when')
    assert 'the store for when can only hold JSON values' in str(error.value.__cause__)


def test_test_bot_keeps_stores_in_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    bot = TestBot(plugin_dir=plugin_dir(tmp_path / 'plugins', karma=KARMA))
    bot.say('!karma pinhook')
    assert not (tmp_path / 'data').exists()


# saved to disk

def test_store_is_saved_to_the_data_folder(tmp_path):
    bot = real_bot(tmp_path, plugin_dir=plugin_dir(tmp_path / 'plugins', karma=KARMA))
    bot.channels['#test'] = mock_channel()
    bot.process_event(mock_conn(), event('mal', '#test', '!karma pinhook'))
    assert json.loads((tmp_path / 'data' / 'karma.json').read_text()) == {'scores': {'pinhook': 1}}


def test_store_survives_a_restart(tmp_path):
    plugins = plugin_dir(tmp_path / 'plugins', karma=KARMA)
    for expected in (1, 2):
        bot = real_bot(tmp_path, plugin_dir=plugins)
        bot.channels['#test'] = mock_channel()
        conn = mock_conn()
        bot.process_event(conn, event('mal', '#test', '!karma pinhook'))
        assert conn.privmsg.call_args.args == ('#test', 'pinhook has {} karma'.format(expected))


def test_nested_changes_are_saved(tmp_path):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'karma.json').write_text(json.dumps({'scores': {'pinhook': 41}}))
    bot = real_bot(tmp_path, plugin_dir=plugin_dir(tmp_path / 'plugins', karma=KARMA))
    bot.channels['#test'] = mock_channel()
    bot.process_event(mock_conn(), event('mal', '#test', '!karma pinhook'))
    assert json.loads((tmp_path / 'data' / 'karma.json').read_text())['scores'] == {'pinhook': 42}


def test_unchanged_store_writes_nothing(tmp_path):
    bot = real_bot(tmp_path, plugin_dir=plugin_dir(tmp_path / 'plugins', hello=(
        "import pinhook.plugin as p\n"
        "@p.command('!hello')\n"
        "def hello(msg): return p.message('hi')\n"
    )))
    bot.channels['#test'] = mock_channel()
    bot.process_event(mock_conn(), event('mal', '#test', '!hello'))
    assert not (tmp_path / 'data').exists()


def test_broken_store_file_is_left_alone(tmp_path, caplog):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'karma.json').write_text('{"scores": ')
    bot = pinhook_bot.Bot(['#test'], 'pinbot', 'localhost', bot_dir=str(tmp_path),
                          plugin_dir=plugin_dir(tmp_path / 'plugins', karma=KARMA))
    bot.channels['#test'] = mock_channel()
    conn = mock_conn()
    bot.process_event(conn, event('mal', '#test', '!karma pinhook'))
    assert "couldn't read the store for karma" in caplog.text
    assert (tmp_path / 'data' / 'karma.json').read_text() == '{"scores": '
    conn.privmsg.assert_not_called()


def test_store_class_round_trip(tmp_path):
    path = str(tmp_path / 'thing.json')
    s = Store('thing', path)
    s['count'] = 1
    s.save_if_changed()
    assert Store('thing', path) == {'count': 1}
    assert not (tmp_path / 'thing.json.tmp').exists()


def mock_conn():
    from unittest import mock
    c = mock.MagicMock()
    c.get_nickname.return_value = 'pinbot'
    return c


def mock_channel():
    from unittest import mock
    ch = mock.MagicMock()
    ch.users.return_value = []
    return ch
