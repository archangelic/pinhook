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
    plugin_dir = fields.Str()
    ns_pass = fields.Str()
    log_level = fields.Str(validate=validate.OneOf(['debug', 'warn', 'info', 'off', 'error']))
    server_pass = fields.Str()

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
            click.echo('Could not detect file format, please supply using --format option', err=True)
    if conf_format == 'json':
        import json
        to_json = json.loads(config.read())
        output = schema.load(to_json)
    elif conf_format == 'yaml':
        try:
            import yaml
        except ImportError:
            click.echo('yaml not installed, please use `pip3 install pinhook[yaml]` to install', err=True)
        else:
            to_yaml = yaml.load(config.read(), Loader=yaml.FullLoader)
            output = schema.load(to_yaml)
    elif conf_format == 'toml':
        try:
            import toml
        except ImportError:
            click.echo('toml not installed, please use `pip3 install pinhook[toml]` to install', err=True)
        else:
            to_toml = toml.load(config.name)
            output = schema.load(to_toml)
    return output

@click.command()
@click.argument('config', type=click.File('rb'))
@click.option('--format', '-f', 'conf_format', type=click.Choice(['json', 'yaml', 'toml']))
def cli(config, conf_format):
    config = read_conf(config, conf_format)
    bot = Bot(**config)
    bot.start()

