"""Reading a bot's config: the file, secrets.env, ${NAME} and ${file:PATH}, YAML's traps
for IRC, and the bot it describes.

    from pinhook.config import load_bot

    bot = load_bot('gamebot/config.yaml')
    bot.start()

That's what pinhook run does. A mistake raises ConfigError, saying what's wrong.
"""
import functools
import os
import re

import yaml
from marshmallow import (Schema, fields, validate, validates_schema, INCLUDE,
                         ValidationError)

from . import log
from .bot import Bot, TwitchBot


class ConfigError(ValueError):
    """A config, or secrets.env, with a mistake, and what it is."""


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
    in the environment wins, so a service manager or container can supply it instead.
    Returns warnings about the file, as text."""
    path = os.path.join(os.path.dirname(config_name), 'secrets.env')
    if not os.path.isfile(path):
        return []
    found = []
    if os.name == 'posix' and os.stat(path).st_mode & 0o077:
        found.append('other users can read {0}. Make it yours only: chmod 600 {0}'.format(path))
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
                raise ConfigError('{} line {} should be NAME=value'.format(path, number))
            if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
                value = value[1:-1]
            os.environ.setdefault(key, value)
    return found


def read_secret_file(path, name):
    # relative paths are beside the config. A file's last line break isn't part of it
    path = os.path.join(os.path.dirname(name), os.path.expanduser(path))
    try:
        with open(path) as f:
            return f.read().rstrip('\r\n')
    except OSError as e:
        raise ConfigError("{} uses ${{file:{}}}, but it can't be read: {}".format(
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
            raise ConfigError("{} uses ${{{}}}, but that environment variable isn't set"
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
        raise ConfigError('{} has problems:\n{}'.format(name, '\n'.join(problems)))


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
            raise ConfigError(
                '{} is TOML, which pinhook 2.0 no longer reads. Write the same settings to a '
                'YAML or JSON file'.format(config.name))
        else:
            raise ConfigError(
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
            raise ConfigError("{} isn't valid YAML, or holds something configs don't "
                              "allow:\n{}{}".format(config.name, e, hint))
        traps = yaml_traps(to_yaml, text)
        if traps:
            raise ConfigError('{} has problems:\n{}'.format(
                config.name, '\n'.join('  {}: {}'.format(*trap) for trap in traps)))
        output = check_conf(schema, to_yaml, config.name)
    return output


def load_bot(path, conf_format=None, warn=None, **overrides):
    """The bot the config at path describes, ready to start(), the way pinhook run makes it.

    secrets.env beside the config is read first. Relative paths start from the config's
    folder, and !reload reads plugin_config and access from the file again.

    Args:
        path: the config file, YAML or JSON.
        conf_format: 'yaml' or 'json', when the file's extension doesn't say.
        warn: called with each warning about secrets.env. They're logged by default.
        **overrides: options set over the config's, like log_level='debug'.
    """
    for warning in load_secrets(path):
        (warn or log.logger.warning)(warning)
    with open(path, 'rb') as f:
        settings = read_conf(f, conf_format)
    bot = make_bot(dict(settings, **overrides), path)
    bot.config_file = path
    bot.config_loader = functools.partial(load_conf_file, path, conf_format)
    return bot
