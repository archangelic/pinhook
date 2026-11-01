import functools
import os
import re

import click
import yaml
from .bot import Bot
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
        try:
            to_yaml = yaml.safe_load(config.read())
        except yaml.YAMLError as e:
            raise click.ClickException("{} isn't valid YAML, or holds something configs don't "
                                       "allow:\n{}".format(config.name, e))
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
