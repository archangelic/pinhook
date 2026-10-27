import json
from unittest import mock

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
    monkeypatch.setitem(__import__('sys').modules, 'toml', None)  # makes "import toml" fail
    result, bot = run_cli(tmp_path, 'nickname = "pinbot"\n', name='config.toml')
    assert result.exit_code != 0
    assert 'pip3 install pinhook[toml]' in result.output
