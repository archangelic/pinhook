import importlib.util
import os

from click.testing import CliRunner

from pinhook import scaffold
from pinhook.cli import cli


def new(*args):
    return CliRunner().invoke(cli, ['new'] + list(args))


def run_test_file(path):
    # the generated test, run as pytest would, from the bot folder
    spec = importlib.util.spec_from_file_location('generated_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in dir(module):
        if name.startswith('test_'):
            getattr(module, name)()


def test_new_bot_makes_a_folder_that_checks_and_whose_test_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = new('bot', 'gamebot')
    assert result.exit_code == 0, result.output
    assert 'Made gamebot/ with config.yaml, plugins/hello.py, tests/test_hello.py' in result.output
    for folder in ('recipes', 'data', 'logs'):
        assert (tmp_path / 'gamebot' / folder).is_dir()
    config = (tmp_path / 'gamebot' / 'config.yaml').read_text()
    assert "nickname: 'gamebot'" in config
    assert "  - '#gamebot-test'" in config
    monkeypatch.chdir(tmp_path / 'gamebot')
    checked = CliRunner().invoke(cli, ['check', 'config.yaml'])
    assert checked.exit_code == 0, checked.output
    assert 'config.yaml is fine. Loaded 1 plugin with 1 command, and 0 recipes' in checked.output
    run_test_file('tests/test_hello.py')


def test_new_bot_leaves_an_existing_folder_alone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'gamebot').mkdir()
    result = new('bot', 'gamebot')
    assert result.exit_code == 1
    assert 'gamebot already exists, so it was left alone' in result.output


def test_new_plugin_makes_a_class_plugin_with_a_passing_test(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = new('plugin', 'dice_roll')
    assert result.exit_code == 0, result.output
    assert result.output == 'Made plugins/dice_roll.py and tests/test_dice_roll.py\n'
    assert 'class DiceRoll(Plugin):' in (tmp_path / 'plugins' / 'dice_roll.py').read_text()
    run_test_file('tests/test_dice_roll.py')


def test_new_plugin_names_are_checked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert 'should be lowercase letters' in new('plugin', 'Dice').output
    assert 'should be lowercase letters' in new('plugin', 'class').output
    assert 'reload is a built-in command' in new('plugin', 'reload').output
    assert 'setup is a Plugin method' in new('plugin', 'setup').output
    assert not (tmp_path / 'plugins').exists()


def test_new_recipe_makes_a_recipe_that_loads(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = new('recipe', 'gamenight')
    assert result.exit_code == 0, result.output
    from pinhook.testing import TestBot
    bot = TestBot(recipe_dir='recipes')
    assert bot.say('!gamenight ana', nick='bo') == ['bo says hello to ana']
    assert new('recipe', 'gamenight').exit_code == 1


def test_outside_a_terminal_the_file_is_just_saved(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    opened = []
    monkeypatch.setattr('click.edit', lambda **kw: opened.append(kw))
    monkeypatch.setenv('EDITOR', 'nano')
    assert new('recipe', 'hug').exit_code == 0
    assert opened == []


def test_edit_opens_it_in_the_editor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    opened = []
    monkeypatch.setattr('click.edit', lambda **kw: opened.append(kw))
    monkeypatch.delenv('VISUAL', raising=False)
    monkeypatch.setenv('EDITOR', 'micro')
    assert new('recipe', 'hug', '--edit').exit_code == 0
    assert opened == [{'filename': os.path.join('recipes', 'hug.yaml'), 'editor': 'micro'}]


def test_in_a_terminal_it_asks_which_editor(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    opened = []
    monkeypatch.setattr('click.edit', lambda **kw: opened.append(kw))
    monkeypatch.setattr(scaffold, 'interactive', lambda: True)
    monkeypatch.delenv('VISUAL', raising=False)
    monkeypatch.delenv('EDITOR', raising=False)
    monkeypatch.setattr(scaffold.shutil, 'which', lambda name: name in ('nano', 'vim'))
    result = CliRunner().invoke(cli, ['new', 'recipe', 'hug'], input='2\n')
    assert '1. nano' in result.output and '2. vim' in result.output
    assert '0. just save it' in result.output
    assert opened == [{'filename': os.path.join('recipes', 'hug.yaml'), 'editor': 'vim'}]


def test_choosing_to_just_save_opens_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    opened = []
    monkeypatch.setattr('click.edit', lambda **kw: opened.append(kw))
    monkeypatch.setattr(scaffold, 'interactive', lambda: True)
    monkeypatch.setenv('EDITOR', 'nano')
    result = CliRunner().invoke(cli, ['new', 'plugin', 'dice'], input='n\n')
    assert 'Open plugins/dice.py in nano? [Y/n]' in result.output
    assert opened == []
    assert (tmp_path / 'plugins' / 'dice.py').exists()


def test_edit_with_no_editor_says_how_to_set_one(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('VISUAL', raising=False)
    monkeypatch.delenv('EDITOR', raising=False)
    monkeypatch.setattr(scaffold.shutil, 'which', lambda name: None)
    result = new('recipe', 'hug', '--edit')
    assert result.exit_code == 1
    assert 'no editor was found to open it. Set EDITOR' in result.output
    assert (tmp_path / 'recipes' / 'hug.yaml').exists()
