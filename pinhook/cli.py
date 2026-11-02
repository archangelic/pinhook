import functools
import logging
import os
import re

import click
import yaml
from . import connect as connecting
from . import log
from . import scaffold
from .bot import Bot, TwitchBot
from .recipes.engine import RECIPES
from marshmallow import (Schema, fields, validate, validates_schema, INCLUDE,
                         ValidationError)

PLATFORMS = ('irc', 'twitch')


class PrefixField(fields.Field):
    # one prefix, like "!", or a list of them
    def _deserialize(self, value, attr, data, **kwargs):
        if isinstance(value, str):
            return value
        if isinstance(value, list) and value and all(isinstance(v, str) and v for v in value):
            return value
        raise ValidationError('should be a prefix like "!", or a list of them')


class Config(Schema):
    # irc unless set. A Twitch bot needs its token, and no server
    platform = fields.Str(validate=validate.OneOf(PLATFORMS))
    token = fields.Str()
    nickname = fields.Str(required=True)
    channels = fields.List(fields.Str(), required=True)
    server = fields.Str()
    port = fields.Int()
    ops = fields.List(fields.Str())
    ssl_required = fields.Bool()
    ssl_verify = fields.Bool()
    plugin_dir = fields.Str()
    ns_pass = fields.Str()
    nickserv = fields.Str()
    log_level = fields.Str(validate=validate.OneOf(['off'] + list(Bot.log_levels)))
    log_file = fields.Str()
    log_format = fields.Str(validate=validate.OneOf(['text', 'json']))
    health_port = fields.Int(allow_none=True, validate=validate.Range(1, 65535))
    health_host = fields.Str()
    server_pass = fields.Str()
    cmd_prefix = PrefixField()
    use_prefix_for_plugins = fields.Bool()
    disable_help = fields.Bool()
    banned_users = fields.List(fields.Str())
    bot_mode = fields.Bool()
    ban_file = fields.Str(allow_none=True)
    require_account = fields.Bool()
    plugin_config = fields.Dict(keys=fields.Str(), values=fields.Dict(keys=fields.Str()))
    bot_dir = fields.Str()
    sasl_account = fields.Str()
    sasl_password = fields.Str()
    sasl_mechanism = fields.Str(validate=validate.OneOf(
        ['auto', 'PLAIN', 'SCRAM-SHA-256', 'EXTERNAL', 'plain', 'scram-sha-256', 'external']))
    ssl_certfile = fields.Str()
    ssl_keyfile = fields.Str()
    data_dir = fields.Str()
    address_by_nick = fields.Bool()
    plugin_channels = fields.Dict(keys=fields.Str(), values=fields.List(fields.Str()))
    # checked by the bot, which can say more about what's wrong
    access = fields.Dict(keys=fields.Str())
    history = fields.Dict(keys=fields.Str())
    recipe_dir = fields.Str(allow_none=True)

    class Meta:
        unknown = INCLUDE

    @validates_schema
    def platform_needs(self, data, **kwargs):
        if data.get('platform', 'irc') == 'irc' and not data.get('server'):
            raise ValidationError('Missing data for required field.', 'server')
        if data.get('platform') == 'twitch':
            if not data.get('token'):
                raise ValidationError("a Twitch bot needs the bot account's oauth token, "
                                      "like token: '${TWITCH_TOKEN}'", 'token')
            if len(data.get('channels') or []) != 1:
                raise ValidationError('a Twitch bot joins one channel in pinhook 2.0',
                                      'channels')


def make_bot(config, config_file):
    """The bot a checked config describes: a Bot, or a TwitchBot for platform: twitch. Its
    relative paths start from the config file's folder."""
    config = dict(config, config_dir=os.path.dirname(os.path.abspath(config_file)))
    if config.pop('platform', 'irc') == 'twitch':
        # Twitch's own tools give the token with oauth: in front, which TwitchBot adds
        token = config.pop('token').removeprefix('oauth:')
        channel = config.pop('channels')[0]
        return TwitchBot(config.pop('nickname'), channel, token, **config)
    return Bot(**config)


# ${NAME} is read from the environment and ${file:PATH} from a file, like a Docker or
# Kubernetes secret. $${ is a literal ${
ENV_VAR = re.compile(r'\$\$\{|\$\{(?:file:([^}]+)|([A-Za-z_][A-Za-z0-9_]*))\}')


ENV_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def load_secrets(config_name):
    """Set the variables in secrets.env, beside the config, for ${NAME} to read. One already
    in the environment wins, so a service manager or container can supply it instead."""
    path = os.path.join(os.path.dirname(config_name), 'secrets.env')
    if not os.path.isfile(path):
        return
    if os.name == 'posix' and os.stat(path).st_mode & 0o077:
        click.echo('warning: other users can read {0}. Make it yours only: chmod 600 {0}'
                   .format(path), err=True)
    with open(path) as f:
        for number, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[len('export '):].lstrip()
            key, equals, value = line.partition('=')
            key, value = key.strip(), value.strip()
            # the line itself isn't shown, since it holds a secret
            if not equals or not ENV_NAME.match(key):
                raise click.ClickException('{} line {} should be NAME=value'.format(path, number))
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                value = value[1:-1]
            os.environ.setdefault(key, value)


def read_secret_file(path, name):
    # relative paths are beside the config. A file's last line break isn't part of it
    path = os.path.join(os.path.dirname(name), os.path.expanduser(path))
    try:
        with open(path) as f:
            return f.read().rstrip('\r\n')
    except OSError as e:
        raise click.ClickException("{} uses ${{file:{}}}, but it can't be read: {}".format(
            name, path, e.strerror))


# options that can't come from a PINHOOK_ variable, since they hold secrets, which come
# from ${NAME} or ${file:PATH} so they're masked in the log
SECRET_OPTIONS = {'token', 'server_pass', 'ns_pass', 'sasl_password'}
MASKED_OPTIONS = SECRET_OPTIONS | {'plugin_config'}


def expand_config(data, name):
    """The config with ${NAME} and ${file:PATH} filled in. What fills in a secret setting,
    or anything in plugin_config, where API keys go, is masked in the log."""
    if not isinstance(data, dict):
        return expand_env(data, name)
    return {key: expand_env(value, name, secret=key in MASKED_OPTIONS)
            for key, value in data.items()}


def expand_env(value, name, secret=False):
    if isinstance(value, dict):
        return {k: expand_env(v, name, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v, name, secret) for v in value]
    if not isinstance(value, str):
        return value

    def replace(match):
        if match.group(1):
            found = read_secret_file(match.group(1), name)
        elif match.group(2) is None:
            return '${'
        elif match.group(2) not in os.environ:
            raise click.ClickException("{} uses ${{{}}}, but that environment variable isn't set"
                                       .format(name, match.group(2)))
        else:
            found = os.environ[match.group(2)]
        if secret:
            log.hide(found)
        return found
    return ENV_VAR.sub(replace, value)


# YAML's two traps for IRC: # starts a comment, so an unquoted channel name vanishes, and
# no, off, yes and on are read as false and true
QUOTE_CHANNELS = ("a channel name isn't quoted, so YAML read it as a comment. Quote channel "
                  "names, like channels: ['#games']")
# an unquoted # inside a flow list, like [#games] or ['#a', #b]
FLOW_CHANNEL = re.compile(r'[\[,]\s*#')


def channel_lists(data):
    # every list of channel names in a config, by where it is
    yield 'channels', data.get('channels', [])
    plugin_channels = data.get('plugin_channels')
    if isinstance(plugin_channels, dict):
        for name, channels in plugin_channels.items():
            yield 'plugin_channels.{}'.format(name), channels
    history = data.get('history')
    if isinstance(history, dict) and 'channels' in history:
        yield 'history.channels', history['channels']


def yaml_traps(data, text):
    """Problems from YAML's traps for IRC, as (setting, problem) pairs."""
    problems = []
    if not isinstance(data, dict):
        return problems
    for name, channels in channel_lists(data):
        if channels is None or (isinstance(channels, list) and None in channels):
            problems.append((name, QUOTE_CHANNELS))
    if isinstance(data.get('nickname'), bool):
        match = re.search(r'^nickname:\s*(\S+)', text, re.M)
        word = match.group(1) if match else str(data['nickname']).lower()
        problems.append(('nickname', "YAML read {} as {}, not a name. Quote it, like "
                         "nickname: '{}'".format(word, str(data['nickname']).lower(), word)))
    ops = data.get('ops')
    if isinstance(ops, list) and any(isinstance(op, bool) for op in ops):
        problems.append(('ops', "YAML read an op as true or false, not a name, which happens "
                         "to no, off, yes and on. Quote it, like - 'no'"))
    return problems


def flatten_problems(messages, path=''):
    # nested settings give nested errors, list them as plugin_config.weather: ...
    for key, msgs in messages.items():
        # marshmallow says whether a mapping's key or value was wrong, the path says enough
        if key in ('key', 'value') and path:
            name = path
        else:
            name = '.'.join(p for p in (path, str(key)) if p)
        if isinstance(msgs, dict):
            yield from flatten_problems(msgs, name)
        else:
            yield name, ' '.join(msgs) if isinstance(msgs, list) else str(msgs)


def env_defaults(schema, data):
    """data, with options it doesn't set taken from PINHOOK_ variables, like
    PINHOOK_LOG_FILE=- for log_file. The image sets its defaults this way, and the config
    wins. Only options that are a single value can be set like this."""
    if not isinstance(data, dict):
        return data
    data = dict(data)
    for key, field in schema.fields.items():
        variable = 'PINHOOK_' + key.upper()
        single = isinstance(field, (fields.Str, fields.Int, fields.Bool))
        if single and key not in SECRET_OPTIONS and key not in data and variable in os.environ:
            data[key] = os.environ[variable]
    return data


def check_conf(schema, data, name):
    data = env_defaults(schema, expand_config(data, name))
    try:
        return schema.load(data)
    except ValidationError as e:
        problems = ['  {}: {}'.format(key, msgs)
                    for key, msgs in sorted(flatten_problems(e.messages))]
        raise click.ClickException('{} has problems:\n{}'.format(name, '\n'.join(problems)))


def load_conf_file(path, conf_format):
    with open(path, 'rb') as f:
        return read_conf(f, conf_format)


def read_conf(config, conf_format):
    schema = Config()
    if not conf_format:
        if config.name.endswith('.json'):
            conf_format = 'json'
        elif config.name.endswith(('.yaml', '.yml')):
            conf_format = 'yaml'
        elif config.name.endswith(('.toml', '.tml')):
            raise click.ClickException(
                '{} is TOML, which pinhook 2.0 no longer reads. Write the same settings to a '
                'YAML or JSON file'.format(config.name))
        else:
            raise click.ClickException(
                'Could not detect file format, please supply using --format option')
    if conf_format == 'json':
        import json
        to_json = json.loads(config.read())
        output = check_conf(schema, to_json, config.name)
    elif conf_format == 'yaml':
        # safe_load, since the full loader can run code from the file
        text = config.read().decode('utf-8', 'replace')
        try:
            to_yaml = yaml.safe_load(text)
        except yaml.YAMLError as e:
            hint = '\n' + QUOTE_CHANNELS if FLOW_CHANNEL.search(text) else ''
            raise click.ClickException("{} isn't valid YAML, or holds something configs don't "
                                       "allow:\n{}{}".format(config.name, e, hint))
        traps = yaml_traps(to_yaml, text)
        if traps:
            raise click.ClickException('{} has problems:\n{}'.format(
                config.name, '\n'.join('  {}: {}'.format(*trap) for trap in traps)))
        output = check_conf(schema, to_yaml, config.name)
    return output


class Pinhook(click.Group):
    """pinhook's commands. `pinhook config.yaml`, with no command, still runs the bot, as in 1.x."""

    def parse_args(self, ctx, args):
        if args and args[0] not in self.commands and not args[0].startswith('-'):
            click.echo("warning: 'pinhook {0}' is shorthand for 'pinhook run {0}', and the "
                       "shorthand will be deprecated in a future version. Use 'pinhook run {0}'"
                       .format(args[0]), err=True)
            args = ['run'] + list(args)
        return super().parse_args(ctx, args)


@click.group(cls=Pinhook)
@click.version_option(package_name='pinhook')
def cli():
    """Run, check and create pinhook bots."""


@cli.command()
@click.argument('config', type=click.File('rb'))
@click.option('--format', '-f', 'conf_format', type=click.Choice(['json', 'yaml']))
@click.option('--reload', is_flag=True,
              help='Reload plugins and recipes when their files change, for development.')
def run(config, conf_format, reload):
    """Connect and run the bot that CONFIG describes.

    Variables in secrets.env, beside CONFIG, are set first, for ${NAME} to read.
    """
    config_file = config.name
    load_secrets(config_file)
    config = read_conf(config, conf_format)
    try:
        bot = make_bot(config, config_file)
    except ValueError as e:
        # a bad log_level or ban file, say what's wrong without a traceback
        raise click.ClickException(str(e))
    bot.config_file = config_file
    bot.config_loader = functools.partial(load_conf_file, config_file, conf_format)
    bot.reload_on_change = reload
    bot.start()


class Collect(logging.Handler):
    """Keeps the warnings and errors a bot logs, for pinhook check."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def describe(record):
    # the message, and for a plugin that failed to load, the error's last line
    text = record.getMessage()
    if record.exc_info and record.exc_info[1] is not None:
        error = record.exc_info[1]
        text += ': {}: {}'.format(type(error).__name__, error)
    return log.mask(text)


def plural(count, word):
    return '{} {}{}'.format(count, word, '' if count == 1 else 's')


@cli.command()
@click.argument('config', type=click.File('rb'))
@click.option('--format', '-f', 'conf_format', type=click.Choice(['json', 'yaml']))
@click.option('--strict', is_flag=True, help='Fail on warnings too, for CI.')
def check(config, conf_format, strict):
    """Check CONFIG, and the plugins and recipes it uses, without connecting.

    Plugins are loaded to check them, so their setup runs, then their teardown.
    Errors fail the check, and with --strict, so do warnings.
    """
    name = config.name
    load_secrets(name)
    settings = read_conf(config, conf_format)
    found = Collect()
    # the bot's warnings come back as a list here, not as log lines
    log.logger.addHandler(found)
    log.logger.removeHandler(log.streamhandler)
    try:
        bot = make_bot(dict(settings, log_level='warning', log_file=os.devnull), name)
        bot.registry.teardown()
    except (ValueError, OSError) as e:
        raise click.ClickException(str(e))
    finally:
        log.logger.removeHandler(found)
        log.logger.addHandler(log.streamhandler)
    errors = [describe(r) for r in found.records if r.levelno >= logging.ERROR]
    warnings = [describe(r) for r in found.records if r.levelno < logging.ERROR]
    for text in errors:
        click.echo('error: ' + text, err=True)
    for text in warnings:
        click.echo('warning: ' + text, err=True)
    plugins = [p for p in bot.registry.plugins if p != RECIPES]
    commands = sum(1 for p in plugins for h in bot.registry.plugins[p] if h.kind == 'command')
    loaded = '{} with {}, and {}'.format(
        plural(len(plugins), 'plugin'), plural(commands, 'command'),
        plural(len(bot.recipes), 'recipe'))
    if errors:
        raise click.ClickException('{} has {} and {}. Loaded {}'.format(
            name, plural(len(errors), 'error'), plural(len(warnings), 'warning'), loaded))
    if warnings and strict:
        raise click.ClickException('{} has {}, and --strict fails on warnings. Loaded {}'.format(
            name, plural(len(warnings), 'warning'), loaded))
    if warnings:
        click.echo('{} has {}. Loaded {}'.format(name, plural(len(warnings), 'warning'), loaded))
    else:
        click.echo('{} is fine. Loaded {}'.format(name, loaded))


@cli.group()
def new():
    """Make a bot folder, a plugin or a recipe from a template."""


EDIT = click.option('--edit/--no-edit', default=None,
                    help='Open it in an editor, or just save it. Asks when not given.')


@new.command('bot')
@click.argument('name')
def new_bot(name):
    """Make the folder NAME, with a config, an example plugin and its test."""
    made = scaffold.new_bot(name)
    click.echo('Made {}/ with {}'.format(name, ', '.join(made)))
    click.echo('Edit {0}/config.yaml, then run pinhook check {0}/config.yaml and pinhook run '
               '{0}/config.yaml'.format(name))


@new.command('plugin')
@click.argument('name')
@EDIT
def new_plugin(name, edit):
    """Make plugins/NAME.py, a class plugin, and its test in tests/."""
    path, test = scaffold.new_plugin(name)
    click.echo('Made {} and {}'.format(path, test))
    scaffold.offer_editor(path, edit)


@new.command('recipe')
@click.argument('name')
@EDIT
def new_recipe(name, edit):
    """Make recipes/NAME.yaml, a recipe with an example step."""
    path = scaffold.new_recipe(name)
    click.echo('Made {}'.format(path))
    scaffold.offer_editor(path, edit)


@cli.command()
@click.argument('platform', type=click.Choice(sorted(connecting.PLATFORMS)))
@click.argument('config', default='config.yaml')
def connect(platform, config):
    """Set up PLATFORM for the bot CONFIG describes, keeping its token in secrets.env.

    CONFIG is config.yaml in this folder unless given. secrets.env goes beside it,
    readable only by you, and pinhook run reads it.
    """
    connecting.connect_twitch(config)
