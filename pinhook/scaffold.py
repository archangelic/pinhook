"""What pinhook new makes: a bot folder, a plugin with its test, or a recipe.

The templates ship inside the package, in pinhook/templates, so what's made always
matches the installed pinhook.
"""
import keyword
import os
import re
import shutil
import sys
from importlib import resources

import click

from .bot import Bot
from .recipes.loader import RECIPE_NAME

PLUGIN_NAME = re.compile(r'^[a-z][a-z0-9_]*$')
BOT_NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_-]*$')
EDITORS = ('nano', 'micro', 'vim', 'nvim', 'vi', 'emacs', 'hx')


def template(file_name, **names):
    """A template, with <name> and <Name> filled in."""
    text = resources.files('pinhook').joinpath('templates', file_name).read_text()
    for key, value in names.items():
        text = text.replace('<{}>'.format(key), value)
    return text


def write(path, text):
    if os.path.exists(path):
        raise click.ClickException('{} already exists, so it was left alone'.format(path))
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, 'w') as f:
        f.write(text)


def reserved():
    return Bot.builtins


def check_plugin_name(name):
    if not PLUGIN_NAME.match(name) or keyword.iskeyword(name):
        raise click.ClickException('{!r} should be lowercase letters, digits and _, starting with '
                                   'a letter, like dice. It names the file, class and command'
                                   .format(name))
    if name in reserved():
        raise click.ClickException('{} is a built-in command, pick another name'.format(name))
    if name in ('setup', 'teardown'):
        raise click.ClickException('{} is a Plugin method, pick another name'.format(name))


def new_bot(name):
    """Make the folder name/, with a config, an example plugin and its test, and the
    bot_dir layout. Returns what it made."""
    if not BOT_NAME.match(name):
        raise click.ClickException('{!r} should be letters, digits, - and _, starting with a '
                                   'letter, like gamebot. It becomes the nick'.format(name))
    if os.path.exists(name):
        raise click.ClickException('{} already exists, so it was left alone'.format(name))
    made = ['config.yaml', 'plugins/hello.py', 'tests/test_hello.py']
    write(os.path.join(name, 'config.yaml'), template('config.yaml', name=name))
    write(os.path.join(name, 'plugins', 'hello.py'),
          template('plugin.py.tmpl', name='hello', Name='Hello'))
    write(os.path.join(name, 'tests', 'test_hello.py'),
          template('test_plugin.py.tmpl', name='hello'))
    for folder in ('recipes', 'data', 'logs'):
        os.makedirs(os.path.join(name, folder))
        made.append(folder + '/')
    return made


def new_plugin(name):
    """Make plugins/name.py and its test, tests/test_name.py. Returns the plugin's path."""
    check_plugin_name(name)
    path = os.path.join('plugins', name + '.py')
    test = os.path.join('tests', 'test_{}.py'.format(name))
    for existing in (path, test):
        if os.path.exists(existing):
            raise click.ClickException('{} already exists, so it was left alone'.format(existing))
    write(path, template('plugin.py.tmpl', name=name, Name=name.title().replace('_', '')))
    write(test, template('test_plugin.py.tmpl', name=name))
    return path, test


def new_recipe(name):
    """Make recipes/name.yaml. Returns its path."""
    if not RECIPE_NAME.match(name):
        raise click.ClickException('{!r} should be letters, digits, - and _, like gamenight. '
                                   'It becomes the command'.format(name))
    if name in reserved():
        raise click.ClickException('{} is a built-in command, pick another name'.format(name))
    path = os.path.join('recipes', name + '.yaml')
    write(path, template('recipe.yaml', name=name))
    return path


def interactive():
    return sys.stdin.isatty() and sys.stdout.isatty()


def editors():
    """The editor to offer: $VISUAL or $EDITOR when set, or else the ones on the PATH."""
    chosen = os.environ.get('VISUAL') or os.environ.get('EDITOR')
    if chosen:
        return [chosen]
    return [editor for editor in EDITORS if shutil.which(editor)]


def offer_editor(path, edit):
    """Open path in an editor. edit is True to open it, False to just save it, or None to
    ask, which outside a terminal also just saves it."""
    if edit is False or (edit is None and not interactive()):
        return
    found = editors()
    if not found:
        if edit:
            raise click.ClickException('{} is saved, but no editor was found to open it. Set '
                                       'EDITOR, like EDITOR=nano'.format(path))
        return
    editor = found[0]
    if edit is None and len(found) == 1:
        if not click.confirm('Open {} in {}?'.format(path, editor), default=True):
            return
    elif edit is None:
        for number, name in enumerate(found, 1):
            click.echo('  {}. {}'.format(number, name))
        click.echo('  0. just save it')
        choice = click.prompt('Open {} in'.format(path), type=click.IntRange(0, len(found)),
                              default=1)
        if choice == 0:
            return
        editor = found[choice - 1]
    click.edit(filename=path, editor=editor)
