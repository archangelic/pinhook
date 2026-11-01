import asyncio
from unittest import mock

from click.testing import CliRunner

from pinhook.cli import cli
from pinhook.testing import TestBot

HELLO = ("from pinhook import command\n\n\n"
         "@command('hello')\nasync def hello(ctx):\n    await ctx.reply('{}')\n")


def watch_while(bot, change):
    # run the watcher, make a change, and give it a few checks to notice
    async def go():
        watcher = asyncio.create_task(bot.watch_files())
        await asyncio.sleep(0.05)
        change()
        await asyncio.sleep(0.1)
        watcher.cancel()
    asyncio.run(go())


def make(tmp_path):
    (tmp_path / 'plugins').mkdir()
    (tmp_path / 'recipes').mkdir()
    (tmp_path / 'plugins' / 'hello.py').write_text(HELLO.format('hi'))
    bot = TestBot(plugin_dir=str(tmp_path / 'plugins'), recipe_dir=str(tmp_path / 'recipes'))
    bot.watch_interval = 0.01
    return bot


def test_a_changed_plugin_is_reloaded(tmp_path, caplog):
    bot = make(tmp_path)
    assert bot.say('!hello') == ['hi']
    watch_while(bot, lambda: (tmp_path / 'plugins' / 'hello.py').write_text(
        HELLO.format('hello again')))
    assert bot.say('!hello') == ['hello again']
    assert 'reloading plugins, since hello.py changed' in caplog.text


def test_new_and_removed_files_are_noticed(tmp_path):
    bot = make(tmp_path)

    def change():
        (tmp_path / 'recipes' / 'hug.yaml').write_text("version: 1\nsteps:\n  - reply: hug\n")
        (tmp_path / 'plugins' / 'hello.py').unlink()
    watch_while(bot, change)
    assert bot.say('!hug') == ['hug']
    assert bot.say('!hello') == []


def test_other_files_are_ignored(tmp_path, caplog):
    bot = make(tmp_path)
    watch_while(bot, lambda: (tmp_path / 'plugins' / 'notes.txt').write_text('x'))
    assert 'reloading' not in caplog.text


def test_run_reload_turns_the_watcher_on(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text("nickname: 'pinbot'\nserver: 'localhost'\nchannels: ['#test']\n")
    with mock.patch('pinhook.cli.Bot') as bot:
        assert CliRunner().invoke(cli, ['run', '--reload', str(path)]).exit_code == 0
        assert bot.return_value.reload_on_change is True
        CliRunner().invoke(cli, ['run', str(path)])
        assert bot.return_value.reload_on_change is False
