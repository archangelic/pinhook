import json
from unittest import mock

import pytest
from click.testing import CliRunner

from pinhook.bot import Bot
from pinhook.cli import Config, cli


def run_cli(tmp_path, config, name='config.json'):
    path = tmp_path / name
    path.write_text(config if isinstance(config, str) else json.dumps(config))
    with mock.patch('pinhook.cli.Bot') as bot:
        result = CliRunner().invoke(cli, [str(path)])
    return result, bot


BASE = {'nickname': 'pinbot', 'server': 'localhost', 'channels': ['#test']}


def test_config_schema_knows_every_bot_option():
    assert set(Config().fields) - {'nickname', 'channels', 'server'} == Bot.options


def test_quoted_booleans_in_config_become_real_booleans(tmp_path):
    result, bot = run_cli(tmp_path, dict(BASE, bot_mode='false', ssl_verify='false'))
    assert result.exit_code == 0
    assert bot.call_args.kwargs['bot_mode'] is False
    assert bot.call_args.kwargs['ssl_verify'] is False


def test_unknown_config_keys_are_passed_to_bot(tmp_path):
    # Bot warns about them, so the CLI should not drop them silently
    result, bot = run_cli(tmp_path, dict(BASE, ssl_requred=True))
    assert bot.call_args.kwargs['ssl_requred'] is True


def test_toml_config_without_toml_installed_gives_install_hint(tmp_path, monkeypatch):
    # makes "import tomllib" and "import toml" fail
    monkeypatch.setitem(__import__('sys').modules, 'tomllib', None)
    monkeypatch.setitem(__import__('sys').modules, 'toml', None)
    result, bot = run_cli(tmp_path, 'nickname = "pinbot"\n', name='config.toml')
    assert result.exit_code != 0
    assert 'pip3 install pinhook[toml]' in result.output


def test_toml_config_loads(tmp_path):
    try:
        import tomllib  # noqa: F401
    except ImportError:
        pytest.importorskip('toml')
    result, bot = run_cli(tmp_path, (
        'nickname = "pinbot"\n'
        'server = "localhost"\n'
        'channels = ["#test"]\n'
        'bot_mode = false\n'
    ), name='config.toml')
    assert result.exit_code == 0, result.output
    assert bot.call_args.kwargs['nickname'] == 'pinbot'
    assert bot.call_args.kwargs['bot_mode'] is False


def test_config_mistakes_are_listed_without_traceback(tmp_path):
    result, bot = run_cli(tmp_path, dict(BASE, port='sixsixsixseven', log_level='verbose'))
    assert result.exit_code != 0
    assert 'has problems:' in result.output
    assert 'port: Not a valid integer.' in result.output
    assert 'log_level: Must be one of' in result.output
    assert 'Traceback' not in result.output


def test_bot_startup_errors_are_shown_plainly(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(BASE))
    error = ValueError("couldn't read ban file bans.json: oops")
    with mock.patch('pinhook.cli.Bot', side_effect=error):
        result = CliRunner().invoke(cli, [str(path)])
    assert result.exit_code != 0
    assert "Error: couldn't read ban file bans.json: oops" in result.output


def test_environment_variables_are_filled_in(tmp_path, monkeypatch):
    monkeypatch.setenv('PH_NS_PASS', 'hunter2')
    monkeypatch.setenv('PH_CHAN', 'games')
    config = dict(BASE, ns_pass='${PH_NS_PASS}', channels=['#${PH_CHAN}', '#chat'])
    result, bot = run_cli(tmp_path, config)
    assert result.exit_code == 0, result.output
    assert bot.call_args.kwargs['ns_pass'] == 'hunter2'
    assert bot.call_args.kwargs['channels'] == ['#games', '#chat']


def test_missing_environment_variable_stops_with_its_name(tmp_path, monkeypatch):
    monkeypatch.delenv('PH_MISSING', raising=False)
    result, bot = run_cli(tmp_path, dict(BASE, ns_pass='${PH_MISSING}'))
    assert result.exit_code != 0
    assert "uses ${PH_MISSING}, but that environment variable isn't set" in result.output
    bot.assert_not_called()


def test_double_dollar_is_a_literal(tmp_path, monkeypatch):
    monkeypatch.setenv('PH_NS_PASS', 'nope')
    result, bot = run_cli(tmp_path, dict(BASE, ns_pass='pa$${PH_NS_PASS}ss'))
    assert bot.call_args.kwargs['ns_pass'] == 'pa${PH_NS_PASS}ss'


def test_environment_variables_work_in_yaml(tmp_path, monkeypatch):
    pytest.importorskip('yaml')
    monkeypatch.setenv('PH_SERVER', 'irc.libera.chat')
    config = 'nickname: pinbot\nserver: "${PH_SERVER}"\nchannels: ["#test"]\n'
    result, bot = run_cli(tmp_path, config, name='config.yaml')
    assert bot.call_args.kwargs['server'] == 'irc.libera.chat'


def test_plugin_config_is_passed_to_the_bot_with_environment_variables(tmp_path, monkeypatch):
    monkeypatch.setenv('PH_WEATHER_KEY', 'abc123')
    weather = {'api_key': '${PH_WEATHER_KEY}', 'units': 'metric'}
    result, bot = run_cli(tmp_path, dict(BASE, plugin_config={'weather': weather}))
    assert result.exit_code == 0, result.output
    expected = {'weather': {'api_key': 'abc123', 'units': 'metric'}}
    assert bot.call_args.kwargs['plugin_config'] == expected


def test_plugin_config_sections_must_be_mappings(tmp_path):
    result, bot = run_cli(tmp_path, dict(BASE, plugin_config={'weather': ['not', 'a', 'mapping']}))
    assert result.exit_code != 0
    assert 'plugin_config.weather: Not a valid mapping type.' in result.output
    assert 'defaultdict' not in result.output


WEATHER_PLUGIN = (
    "import pinhook.plugin as p\n"
    "@p.command('!units')\n"
    "def units(msg): return p.message(msg.config.get('units', 'none'))\n"
)


def start_from_config(tmp_path, config):
    # runs the real pinhook command, with start() stubbed so nothing connects
    from pinhook import bot as pinhook_bot
    (tmp_path / 'plugins').mkdir(exist_ok=True)
    (tmp_path / 'plugins' / 'weather.py').write_text(WEATHER_PLUGIN)
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    with mock.patch.object(pinhook_bot.Bot, 'start', autospec=True) as start:
        result = CliRunner().invoke(cli, [str(path)])
    assert result.exit_code == 0, result.output
    bot = start.call_args.args[0]
    conn = mock.MagicMock()
    conn.get_nickname.return_value = 'pinbot'
    bot.channels['#test'] = mock.MagicMock()
    bot.channels['#test'].users.return_value = []
    return bot, conn, path


def say(bot, conn, text, nick='mal'):
    from conftest import event
    conn.reset_mock()
    bot.process_event(conn, event(nick, '#test', text))
    return [c.args[1] for c in conn.privmsg.call_args_list]


def reload_config(tmp_path, **plugin_config):
    return dict(BASE, ops=['mal'], log_level='off', ban_file='', bot_dir=str(tmp_path),
                plugin_config=plugin_config)


def test_reload_reads_plugin_config_from_the_file_again(tmp_path):
    config = reload_config(tmp_path, weather={'units': 'metric'})
    bot, conn, path = start_from_config(tmp_path, config)
    assert say(bot, conn, '!units') == ['metric']
    path.write_text(json.dumps(reload_config(tmp_path, weather={'units': 'imperial'})))
    assert say(bot, conn, '!reload') == ['Plugins reloaded (and plugin_config from config.json)']
    assert say(bot, conn, '!units') == ['imperial']


def test_reload_keeps_old_settings_when_the_file_is_broken(tmp_path):
    config = reload_config(tmp_path, weather={'units': 'metric'})
    bot, conn, path = start_from_config(tmp_path, config)
    path.write_text('{"nickname": ')
    assert say(bot, conn, '!reload') == ["Plugins reloaded, but config.json has a problem "
                                         "so plugin_config wasn't changed, see the log"]
    assert say(bot, conn, '!units') == ['metric']


def test_reload_without_a_config_file_just_reloads(make_bot, conn):
    from conftest import event
    b = make_bot(ops=['mal'])
    b.process_event(conn, event('mal', '#test', '!reload'))
    conn.privmsg.assert_called_once_with('#test', 'Plugins reloaded')
