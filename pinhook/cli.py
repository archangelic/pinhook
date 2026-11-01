import functools
import logging
import os
import re

import click
import yaml
from . import log
from .bot import Bot
from .recipes.engine import RECIPES
from marshmallow import Schema, fields, validate, INCLUDE, ValidationError


class PrefixField(fields.Field):
    # one prefix, like "!", or a list of them
    def _deserialize(self, value, attr, data, **kwargs):
        if isinstance(value, str):
            return value
        if isinstance(value, list) and value and all(isinstance(v, str) and v for v in value):
            return value
        raise ValidationError('should be a prefix like "!", or a list of them')


class Config(Schema):
    nickname = fields.Str(required=True)
    channels = fields.List(fields.Str(), required=True)
    server = fields.Str(required=True)
    port = fields.Int()
    ops = fields.List(fields.Str())
    ssl_required = fields.Bool()
    ssl_verify = fields.Bool()
    plugin_dir = fields.Str()
    ns_pass = fields.Str()
    nickserv = fields.Str()
    log_level = fields.Str(validate=validate.OneOf(['off'] + list(Bot.log_levels)))
    log_file = fields.Str()
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


# ${NAME} is read from the environment, $${ is a literal ${
ENV_VAR = re.compile(r'\$\$\{|\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


def expand_env(value, name):
    if isinstance(value, dict):
        return {k: expand_env(v, name) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v, name) for v in value]
    if not isinstance(value, str):
        return value

    def replace(match):
        if match.group(1) is None:
            return '${'
        if match.group(1) not in os.environ:
            raise click.ClickException("{} uses ${{{}}}, but that environment variable isn't set"
                                       .format(name, match.group(1)))
        return os.environ[match.group(1)]
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


def check_conf(schema, data, name):
    data = expand_env(data, name)
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
def run(config, conf_format):
    """Connect and run the bot that CONFIG describes."""
    config_file = config.name
    config = read_conf(config, conf_format)
    try:
        bot = Bot(**config)
    except ValueError as e:
        # a bad log_level or ban file, say what's wrong without a traceback
        raise click.ClickException(str(e))
    bot.config_file = config_file
    bot.config_loader = functools.partial(load_conf_file, config_file, conf_format)
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
    return text


def plural(count, word):
    return '{} {}{}'.format(count, word, '' if count == 1 else 's')


@cli.command()
@click.argument('config', type=click.File('rb'))
@click.option('--format', '-f', 'conf_format', type=click.Choice(['json', 'yaml']))
def check(config, conf_format):
    """Check CONFIG, and the plugins and recipes it uses, without connecting.

    Plugins are loaded to check them, so their setup runs, then their teardown.
    """
    name = config.name
    settings = read_conf(config, conf_format)
    found = Collect()
    # the bot's warnings come back as a list here, not as log lines
    log.logger.addHandler(found)
    log.logger.removeHandler(log.streamhandler)
    try:
        bot = Bot(**dict(settings, log_level='warning', log_file=os.devnull))
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
    if warnings:
        click.echo('{} has {}. Loaded {}'.format(name, plural(len(warnings), 'warning'), loaded))
    else:
        click.echo('{} is fine. Loaded {}'.format(name, loaded))
