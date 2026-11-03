"""The pinhook command: new, check, run and connect."""
import logging
import os

import click
from . import connect as connecting
from . import log
from . import scaffold
from .config import Config, ConfigError, load_bot
from .recipes.engine import RECIPES

__all__ = ['cli', 'Config', 'ConfigError']


def warn(text):
    click.echo('warning: ' + text, err=True)


class Pinhook(click.Group):
    """pinhook's commands. `pinhook config.yaml`, with no command, still runs the bot, as in 1.x."""

    def parse_args(self, ctx, args):
        if args and args[0] not in self.commands and not args[0].startswith('-'):
            warn("'pinhook {0}' is shorthand for 'pinhook run {0}', and the shorthand will "
                 "be deprecated in a future version. Use 'pinhook run {0}'".format(args[0]))
            args = ['run'] + list(args)
        return super().parse_args(ctx, args)


@click.group(cls=Pinhook)
@click.version_option(package_name='pinhook')
def cli():
    """Run, check and create pinhook bots."""


@cli.command()
@click.argument('config', default='config.yaml',
                type=click.Path(exists=True, dir_okay=False))
@click.option('--format', '-f', 'conf_format', type=click.Choice(['json', 'yaml']))
@click.option('--reload', is_flag=True,
              help='Reload plugins and recipes when their files change, for development.')
def run(config, conf_format, reload):
    """Connect and run the bot that CONFIG describes, config.yaml unless given.

    Variables in secrets.env, beside CONFIG, are set first, for ${NAME} to read.
    """
    try:
        bot = load_bot(config, conf_format, warn=warn)
    except (ValueError, OSError) as e:
        # a config mistake, a bad log_level or ban file, or a file that can't be read or
        # written, like ssl_certfile: what's wrong, without a traceback
        raise click.ClickException(str(e))
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
@click.argument('config', default='config.yaml',
                type=click.Path(exists=True, dir_okay=False))
@click.option('--format', '-f', 'conf_format', type=click.Choice(['json', 'yaml']))
@click.option('--strict', is_flag=True, help='Fail on warnings too, for CI.')
def check(config, conf_format, strict):
    """Check CONFIG, config.yaml unless given, and its plugins and recipes, without connecting.

    Plugins are loaded to check them, so their setup runs, then their teardown.
    Errors fail the check, and with --strict, so do warnings.
    """
    name = config
    found = Collect()
    # the bot's warnings come back as a list here, not as log lines
    log.logger.addHandler(found)
    log.logger.removeHandler(log.streamhandler)
    try:
        bot = load_bot(config, conf_format, warn=warn, log_level='warning',
                       log_file=os.devnull)
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
        warn(text)
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
