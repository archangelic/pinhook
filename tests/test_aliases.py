import pytest

from pinhook import command
from pinhook.testing import PluginError, TestBot

DICE = '''
from pinhook import command


@command('roll', help='roll a die', aliases=['r', 'dice'])
async def roll(ctx, sides: int = 6):
    await ctx.reply(f'{ctx.nick} rolled {sides}')
'''


def make(tmp_path, ops=('mal',), **files):
    (tmp_path / 'plugins').mkdir(exist_ok=True)
    for name, text in dict({'dice': DICE}, **files).items():
        (tmp_path / 'plugins' / (name + '.py')).write_text(text)
    return TestBot(plugin_dir=str(tmp_path / 'plugins'), ops=list(ops))


def test_an_alias_runs_the_command(tmp_path):
    bot = make(tmp_path)
    assert bot.say('!r 20', nick='ana') == ['ana rolled 20']
    assert bot.say('!dice', nick='ana') == ['ana rolled 6']
    assert bot.say('testbot: r 4', nick='ana') == ['ana rolled 4']


def test_help_lists_the_name_and_shows_the_aliases(tmp_path):
    bot = make(tmp_path)
    assert bot.private('!help', nick='ana') == ['commands: !help, !roll | !help <command> for more']
    assert bot.private('!help r', nick='ana') == [
        '!roll -- roll a die', 'also !r, !dice', 'usage: roll [sides=6]']
    assert [(c.name, c.aliases) for c in bot.commands()] == [('roll', ('r', 'dice'))]


def test_access_and_switches_go_by_the_command(tmp_path):
    bot = make(tmp_path)
    assert bot.say('!disable !r', nick='mal') == ["mal: '!r' disabled in #test"]
    assert bot.say('!roll', nick='ana') == []
    assert bot.say('!access dice', nick='mal')[0].startswith('plugin dice')
    assert bot.say('!access !r', nick='mal') == ['!roll: open']


def test_an_alias_another_plugin_has_stops_it_loading(tmp_path):
    other = ("from pinhook import command\n\n\n"
             "@command('r')\nasync def r(ctx):\n    await ctx.reply('mine')\n")
    with pytest.raises(PluginError, match='registers command !r, which plugin dice already has'):
        make(tmp_path, zother=other)


def test_an_alias_cant_be_a_built_in(tmp_path):
    clash = ("from pinhook import command\n\n\n"
             "@command('bans', aliases=['banlist'])\nasync def bans(ctx):\n    pass\n")
    with pytest.raises(PluginError, match='registers command !banlist, which the bot itself'):
        make(tmp_path, clash=clash)


def test_aliases_are_checked_when_the_decorator_runs():
    with pytest.raises(ValueError, match='command names are letters'):
        command('roll', aliases=['!r'])
    with pytest.raises(ValueError, match="roll's aliases repeat a name"):
        command('roll', aliases=['roll'])
