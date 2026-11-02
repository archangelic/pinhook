import os
import stat

from click.testing import CliRunner

from pinhook.cli import cli


def connect(tmp_path, token, config=None):
    path = tmp_path / 'config.yaml'
    if config is not None:
        path.write_text(config)
    return CliRunner().invoke(cli, ['connect', 'twitch', str(path)], input=token + '\n')


def test_the_token_goes_in_secrets_env_only_its_owner_can_read(tmp_path):
    result = connect(tmp_path, 'oauth:abc123', config=(
        "platform: twitch\nnickname: 'gamebot'\nchannels: ['#me']\n"
        "token: '${TWITCH_TOKEN}'\n"))
    assert result.exit_code == 0, result.output
    secrets = tmp_path / 'secrets.env'
    assert secrets.read_text() == 'TWITCH_TOKEN=abc123\n'
    assert stat.S_IMODE(os.stat(secrets).st_mode) == 0o600
    assert 'abc123' not in result.output
    assert 'already uses it. Start the bot with pinhook run' in result.output


def test_a_new_token_replaces_the_old_one_and_keeps_other_secrets(tmp_path):
    secrets = tmp_path / 'secrets.env'
    secrets.write_text('# mine\nWEATHER_KEY=xyz\nexport TWITCH_TOKEN=old\n')
    secrets.chmod(0o644)
    assert connect(tmp_path, 'new').exit_code == 0
    assert secrets.read_text() == '# mine\nWEATHER_KEY=xyz\nTWITCH_TOKEN=new\n'
    assert stat.S_IMODE(os.stat(secrets).st_mode) == 0o600


def test_it_says_what_the_config_still_needs(tmp_path):
    result = connect(tmp_path, 'abc', config="nickname: 'gamebot'\n")
    assert "Add this to {}:\n  platform: twitch\n  token: '${{TWITCH_TOKEN}}'".format(
        tmp_path / 'config.yaml') in result.output


def test_no_token_saves_nothing(tmp_path):
    result = connect(tmp_path, '   ')
    assert result.exit_code != 0
    assert not (tmp_path / 'secrets.env').exists()


def test_only_known_platforms(tmp_path):
    result = CliRunner().invoke(cli, ['connect', 'myspace'])
    assert result.exit_code == 2
    assert "'myspace' is not 'twitch'" in result.output
