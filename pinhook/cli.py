import json

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

def read_conf(config):
    schema = Config()
    if config.name.endswith('.json'):
        to_json = json.loads(config.read())
        output = schema.load(to_json)
        return output
    else:
        raise click.BadArgumentUsage("Only json files at this time")

@click.command()
@click.argument('config', type=click.File('rb'))
def cli(config):
    config = read_conf(config)
    bot = Bot(**config)
    bot.start()

