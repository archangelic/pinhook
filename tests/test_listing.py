"""The command listing: structured details of every command, for code."""
from pinhook.commands import Arg, CommandInfo
from pinhook.testing import TestBot
from pinhook.transport.base import Source

PLUGINS = {
    'dice': '''
from typing import Annotated, Literal, Optional
from pinhook import command

@command('roll', help='roll dice')
async def roll(ctx, dice: Annotated[str, 'dice like 2d6'] = '1d6', times: int = 1):
    pass

@command('pick', restricted=True)
async def pick(ctx, side: Literal['heads', 'tails'], note: Optional[str] = None):
    """pick a side"""

@command('secret', hide=True)
async def secret(ctx):
    pass

@command('shutdown', ops=True)
async def shutdown(ctx):
    pass
''',
    'old': '''
import pinhook.plugin as p

@p.command('.weather', help_text='the weather')
def weather(msg):
    pass
''',
}


def make(tmp_path):
    for name, code in PLUGINS.items():
        (tmp_path / (name + '.py')).write_text(code)
    return TestBot(plugin_dir=str(tmp_path), ops=['$a:mal'])


def test_every_command_with_its_details(tmp_path):
    bot = make(tmp_path)
    listing = {info.name: info for info in bot.commands()}
    assert sorted(listing) == ['.weather', 'pick', 'roll', 'secret', 'shutdown']
    assert listing['roll'] == CommandInfo(
        'roll', '!roll', 'roll dice', 'roll [dice=1d6] [times=1]',
        (Arg('dice', 'str', False, '1d6', 'dice like 2d6'), Arg('times', 'int', False, 1)),
        'dice', 'open', False, True)
    assert listing['pick'].args == (
        Arg('side', 'str', True, choices=('heads', 'tails')),
        Arg('note', 'str', False, rest=True))
    assert (listing['pick'].help, listing['pick'].level) == ('pick a side', 'restricted')
    assert listing['secret'].hidden and listing['shutdown'].level == 'ops'


def test_1x_commands_take_one_free_text_argument(tmp_path):
    # a 1.x command with a trigger of its own is named by it
    weather = {i.name: i for i in make(tmp_path).commands()}['.weather']
    assert (weather.label, weather.typed, weather.usage) == ('.weather', False,
                                                             '.weather [arg]')
    assert weather.args == (Arg('arg', 'str', False, '', 'everything after the command',
                                rest=True),)


def test_asked_for_one_person_it_holds_only_what_they_can_trigger(tmp_path):
    bot = make(tmp_path)
    anyone = Source('ana', 'ana', 'host', None)
    assert [i.name for i in bot.commands(anyone, '#test')] == ['.weather', 'roll', 'secret']
    op = Source('mal', 'mal', 'host', 'mal')
    assert len(bot.commands(op, '#test')) == 5
    bot.say('!allow pick $a:ana', nick='mal', account='mal')
    ana = Source('ana', 'ana', 'host', 'ana')
    assert 'pick' in [i.name for i in bot.commands(ana, '#test')]
    bot.banned_users.append('$a:ana')
    assert bot.commands(ana, '#test') == []
