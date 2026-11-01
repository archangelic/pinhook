"""pinhook connect: setting up a platform that needs a token, and keeping it in secrets.env.

secrets.env sits beside the config, readable only by its owner, and pinhook run
loads it before reading the config, which refers to each secret as ${NAME}.
"""
import os
import sys

import click
import yaml

from .config import parse_secret_line, secrets_path

PLATFORMS = {'twitch': 'TWITCH_TOKEN'}


def save_secret(path, name, value):
    """Set name=value in the secrets.env at path, replacing any line already setting name,
    and leave the file readable only by its owner."""
    lines = []
    if os.path.exists(path):
        with open(path) as f:
            lines = [line for line in f.read().splitlines()
                     if (parse_secret_line(line) or ('',))[0] != name]
    lines.append('{}={}'.format(name, value))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    os.chmod(path, 0o600)


def config_uses(config_path, name):
    """What the config is missing to use the secret name on Twitch, as lines to add."""
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        config = {}
    missing = []
    if config.get('platform') != 'twitch':
        missing.append('platform: twitch')
    if config.get('token') != '${{{}}}'.format(name):
        missing.append("token: '${{{}}}'".format(name))
    return missing


def connect_twitch(config_path):
    """Ask for the bot account's token and keep it in secrets.env beside the config."""
    if sys.stdin.isatty():
        click.echo("Paste the bot account's OAuth token. It needs the chat:read and chat:edit "
                   'scopes. It is saved, not shown.')
        token = click.prompt('Token', hide_input=True)
    else:
        token = sys.stdin.readline()
    token = token.strip().removeprefix('oauth:')
    if not token:
        raise click.ClickException('no token was given, so nothing was saved')
    path = secrets_path(config_path)
    save_secret(path, PLATFORMS['twitch'], token)
    click.echo('Saved TWITCH_TOKEN in {}, which only you can read'.format(path))
    missing = config_uses(config_path, PLATFORMS['twitch'])
    if missing:
        click.echo('Add this to {}:\n{}'.format(
            config_path, '\n'.join('  ' + line for line in missing)))
    else:
        click.echo('{} already uses it. Start the bot with pinhook run {}'.format(
            config_path, config_path))
