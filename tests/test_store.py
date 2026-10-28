import pytest

from pinhook.store import Store
from pinhook.testing import PluginError, TestBot


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


def test_store_class_round_trip(tmp_path):
    path = str(tmp_path / 'thing.json')
    s = Store('thing', path)
    s['count'] = 1
    s.save_if_changed()
    assert Store('thing', path) == {'count': 1}
    assert not (tmp_path / 'thing.json.tmp').exists()
