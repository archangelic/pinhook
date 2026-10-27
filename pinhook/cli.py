import click
from .bot import Bot
from marshmallow import Schema, fields, validate, INCLUDE

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

    class Meta:
        unknown = INCLUDE

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
        output = schema.load(to_json)
    elif conf_format == 'yaml':
        try:
            import yaml
        except ImportError:
            raise click.ClickException('yaml not installed, please use `pip3 install pinhook[yaml]` to install')
        else:
            to_yaml = yaml.load(config.read(), Loader=yaml.FullLoader)
            output = schema.load(to_yaml)
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
        output = schema.load(to_toml)
    return output

@click.command()
@click.argument('config', type=click.File('rb'))
@click.option('--format', '-f', 'conf_format', type=click.Choice(['json', 'yaml', 'toml']))
def cli(config, conf_format):
    config = read_conf(config, conf_format)
    bot = Bot(**config)
    bot.start()

