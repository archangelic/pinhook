import os

import pytest

from pinhook.bot import Bot, TwitchBot
from pinhook.config import ConfigError, load_bot


def write(tmp_path, text, name='config.yaml'):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def test_load_bot_makes_the_bot_pinhook_run_would(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    (tmp_path / 'secrets.env').write_text('PH_NS=hunter2\n')
    (tmp_path / 'secrets.env').chmod(0o600)
    path = write(tmp_path, "nickname: 'gamebot'\nserver: 'localhost'\nchannels: ['#games']\n"
                           "bot_dir: '.'\nns_pass: '${PH_NS}'\nlog_level: 'off'\n")
    bot = load_bot(path)
    assert type(bot) is Bot
    assert bot.ns_pass == 'hunter2'
    assert bot.plugin_dir == os.path.join(str(tmp_path), '.', 'plugins')
    assert bot.config_file == path
    assert bot.config_loader()['nickname'] == 'gamebot'


def test_load_bot_makes_twitch_bots_and_takes_overrides(tmp_path):
    path = write(tmp_path, "platform: twitch\nnickname: 'gamebot'\nchannels: ['#me']\n"
                           "token: 'abc'\nlog_level: 'off'\n")
    bot = load_bot(path, data_dir=str(tmp_path / 'elsewhere'))
    assert type(bot) is TwitchBot
    assert bot.data_dir == str(tmp_path / 'elsewhere')


def test_load_bot_raises_config_error_saying_whats_wrong(tmp_path):
    path = write(tmp_path, "nickname: 'gamebot'\nchannels: ['#games']\n")
    with pytest.raises(ConfigError, match='server: Missing data for required field'):
        load_bot(path)


def test_secrets_env_warnings_go_to_warn(tmp_path, monkeypatch):
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    (tmp_path / 'secrets.env').write_text('A=1\n')
    (tmp_path / 'secrets.env').chmod(0o644)
    path = write(tmp_path, "nickname: 'gamebot'\nserver: 'x'\nchannels: ['#g']\n"
                           "log_level: 'off'\nban_file: ''\n")
    said = []
    load_bot(path, warn=said.append)
    assert said and said[0].startswith('other users can read')
