import pytest

from pinhook.testing import PluginError, TestBot

WEATHER = (
    "import pinhook.plugin as p\n"
    "@p.command('!weather')\n"
    "def weather(msg):\n"
    "    return p.message('{} in {}'.format(msg.config['api_key'], msg.config.get('units', 'metric')))\n"
    "@p.command('!mods')\n"
    "def mods(msg):\n"
    "    return p.message(', '.join(msg.config.shared.get('modteam', [])))\n"
)


def plugins(tmp_path, **files):
    for name, code in files.items():
        (tmp_path / '{}.py'.format(name)).write_text(code)
    return str(tmp_path)


def test_plugin_reads_its_own_section(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, weather=WEATHER),
                  plugin_config={'weather': {'api_key': 'abc', 'units': 'imperial'}})
    assert bot.say('!weather') == ['abc in imperial']


def test_get_gives_a_default(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, weather=WEATHER), plugin_config={'weather': {'api_key': 'abc'}})
    assert bot.say('!weather') == ['abc in metric']


def test_missing_setting_names_the_setting_and_plugin(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, weather=WEATHER))
    with pytest.raises(PluginError) as error:
        bot.say('!weather')
    assert "plugin_config has no 'api_key' setting for the weather plugin" in str(error.value.__cause__)


def test_every_plugin_can_read_the_shared_section(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, weather=WEATHER),
                  plugin_config={'shared': {'modteam': ['mal', 'ana']}})
    assert bot.say('!mods') == ['mal, ana']


def test_plugins_only_see_their_own_section(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, weather=WEATHER, other=(
        "import pinhook.plugin as p\n"
        "@p.command('!peek')\n"
        "def peek(msg): return p.message(str(dict(msg.config)))\n"
    )), plugin_config={'weather': {'api_key': 'secret'}})
    assert bot.say('!peek') == ['{}']


def test_config_is_read_only(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, writer=(
        "import pinhook.plugin as p\n"
        "@p.command('!write')\n"
        "def write(msg): msg.config['api_key'] = 'mine'\n"
    )), plugin_config={'writer': {'api_key': 'abc'}})
    with pytest.raises(PluginError) as error:
        bot.say('!write')
    assert isinstance(error.value.__cause__, TypeError)


def test_section_for_a_missing_plugin_warns_with_a_suggestion(tmp_path, caplog):
    TestBot(plugin_dir=plugins(tmp_path, weather=WEATHER), plugin_config={'weathr': {}, 'shared': {}})
    assert "plugin_config has settings for 'weathr', but there's no plugin called that, did you mean 'weather'?" in caplog.text
    assert "'shared'" not in caplog.text
