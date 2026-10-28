import os
import re

import click
from .bot import Bot
from marshmallow import Schema, fields, validate, INCLUDE, ValidationError

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
    cmd_prefix = fields.Str()
    use_prefix_for_plugins = fields.Bool()
    disable_help = fields.Bool()
    banned_users = fields.List(fields.Str())
    bot_mode = fields.Bool()
    ban_file = fields.Str(allow_none=True)
    require_account = fields.Bool()
    bot_dir = fields.Str()
    data_dir = fields.Str()

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
            raise click.ClickException("{} uses ${{{}}}, but that environment variable isn't set".format(name, match.group(1)))
        return os.environ[match.group(1)]
    return ENV_VAR.sub(replace, value)

def check_conf(schema, data, name):
    data = expand_env(data, name)
    try:
        return schema.load(data)
    except ValidationError as e:
        problems = ['  {}: {}'.format(key, ' '.join(msgs) if isinstance(msgs, list) else msgs) for key, msgs in sorted(e.messages.items())]
        raise click.ClickException('{} has problems:\n{}'.format(name, '\n'.join(problems)))

def read_conf(config, conf_format):
    schema = Config()
    if not conf_format:
        if config.name.endswith('.json'):
            conf_format = 'json'
        elif config.name.endswith(('.yaml', '.yml')):
            conf_format = 'yaml'
        elif config.name.endswith(('.toml', '.tml')):
            conf_format = 'toml'
        else:
            raise click.ClickException('Could not detect file format, please supply using --format option')
    if conf_format == 'json':
        import json
        to_json = json.loads(config.read())
        output = check_conf(schema, to_json, config.name)
    elif conf_format == 'yaml':
        try:
            import yaml
        except ImportError:
            raise click.ClickException('yaml not installed, please use `pip3 install pinhook[yaml]` to install')
        else:
            to_yaml = yaml.load(config.read(), Loader=yaml.FullLoader)
            output = check_conf(schema, to_yaml, config.name)
    elif conf_format == 'toml':
        try:
            # built in from python 3.11
            import tomllib
        except ImportError:
            try:
                import toml
            except ImportError:
                raise click.ClickException('toml not installed, please use `pip3 install pinhook[toml]` to install')
            to_toml = toml.load(config.name)
        else:
            to_toml = tomllib.load(config)
        output = check_conf(schema, to_toml, config.name)
    return output

@click.command()
@click.argument('config', type=click.File('rb'))
@click.option('--format', '-f', 'conf_format', type=click.Choice(['json', 'yaml', 'toml']))
def cli(config, conf_format):
    config = read_conf(config, conf_format)
    try:
        bot = Bot(**config)
    except ValueError as e:
        # a bad log_level or ban file, say what's wrong without a traceback
        raise click.ClickException(str(e))
    bot.start()

