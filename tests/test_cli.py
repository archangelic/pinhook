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
    with mock.patch('pinhook.cli.Bot', side_effect=ValueError("couldn't read ban file bans.json: oops")):
        result = CliRunner().invoke(cli, [str(path)])
    assert result.exit_code != 0
    assert "Error: couldn't read ban file bans.json: oops" in result.output


def test_environment_variables_are_filled_in(tmp_path, monkeypatch):
    monkeypatch.setenv('PH_NS_PASS', 'hunter2')
    monkeypatch.setenv('PH_CHAN', 'games')
    result, bot = run_cli(tmp_path, dict(BASE, ns_pass='${PH_NS_PASS}', channels=['#${PH_CHAN}', '#chat']))
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
    result, bot = run_cli(tmp_path, 'nickname: pinbot\nserver: "${PH_SERVER}"\nchannels: ["#test"]\n', name='config.yaml')
    assert bot.call_args.kwargs['server'] == 'irc.libera.chat'
