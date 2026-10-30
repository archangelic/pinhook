"""Running a command as someone, with their access, and capturing what it says."""
import asyncio

from pinhook.bot import RunResult
from pinhook.testing import TestBot
from pinhook.transport.base import Source

PLUGIN = '''
import asyncio
from pinhook import command

@command('roll')
async def roll(ctx, sides: int = 6):
    ctx.store['rolls'] = ctx.store.get('rolls', 0) + 1
    await ctx.reply('{} rolled {}'.format(ctx.nick, sides))
    await ctx.send('#log', 'a roll')

@command('weather', restricted=True, denied_msg='ask an op')
async def weather(ctx):
    ctx.store['asked'] = True
    await ctx.reply('sunny')

@command('shutdown', ops=True)
async def shutdown(ctx):
    await ctx.reply('bye')

@command('broken', error_msg='that went wrong')
async def broken(ctx):
    raise ValueError('oops')

@command('slow', timeout=0.05)
async def slow(ctx):
    await asyncio.sleep(1)

@command('wait')
async def wait(ctx):
    await asyncio.sleep(0.05)
    await ctx.reply('waited')
'''
OLD = '''
import pinhook.plugin as p

@p.command('!old')
def old(msg):
    msg.reply('from reply')
    return p.message('from return')
'''

ANA = Source('ana', 'ana', 'host', 'ana')
MAL = Source('mal', 'mal', 'host', 'mal')


def make(tmp_path, **options):
    (tmp_path / 'plugin.py').write_text(PLUGIN)
    (tmp_path / 'old.py').write_text(OLD)
    return TestBot(plugin_dir=str(tmp_path), ops=['$a:mal'], **options)


def run(bot, *args, **kwargs):
    return bot.driver.loop.run_until_complete(bot.run_as(*args, **kwargs))


def test_a_captured_run_returns_its_lines_and_sends_nothing(tmp_path):
    bot = make(tmp_path)
    assert run(bot, ANA, 'roll', '20', '#test') == RunResult(
        'ran', ('ana rolled 20', 'a roll'), None)
    bot.driver.run()
    assert bot.sent == []


def test_without_capture_the_command_answers_as_usual(tmp_path):
    bot = make(tmp_path)
    assert run(bot, ANA, '!roll', '', '#test', capture=False) == RunResult('ran', (), None)
    bot.driver.run()
    assert bot.sent_to('#test') == ['ana rolled 6']


def test_1x_commands_are_captured_too(tmp_path):
    bot = make(tmp_path)
    assert run(bot, ANA, 'old', '', '#test').lines == ('from reply', 'from return')


def test_runs_go_by_the_persons_own_access(tmp_path):
    bot = make(tmp_path)
    result = run(bot, ANA, 'weather', '', '#test')
    assert (result.status, result.error) == ('refused', "ana doesn't have access to !weather")
    # the denied message is what they'd have been told
    assert result.lines == ('ask an op',)
    assert 'asked' not in bot.store('plugin')
    assert run(bot, MAL, 'weather', '', '#test').lines == ('sunny',)
    assert run(bot, ANA, 'shutdown', '', '#test').status == 'refused'


def test_grants_and_deny_lists_apply(tmp_path):
    bot = make(tmp_path)
    bot.say('!allow weather $a:ana', nick='mal', account='mal')
    assert run(bot, ANA, 'weather', '', '#test').status == 'ran'
    bot.say('!deny weather $a:ana', nick='mal', account='mal')
    assert run(bot, ANA, 'weather', '', '#test').status == 'refused'


def test_banned_people_are_refused(tmp_path):
    bot = make(tmp_path, banned_users=['$a:ana'])
    result = run(bot, ANA, 'roll', '', '#test')
    assert result.status == 'refused' and 'banned' in result.error
    assert bot.store('plugin') == {}


def test_a_command_switched_off_here_is_refused(tmp_path):
    bot = make(tmp_path)
    bot.say('!disable roll', nick='mal', account='mal')
    assert run(bot, ANA, 'roll', '', '#test') == RunResult(
        'refused', (), '!roll is switched off here')


def test_unknown_commands(tmp_path):
    assert run(make(tmp_path), ANA, 'nope', '', '#test') == RunResult(
        'unknown', (), "there's no command called nope")


def test_failures_say_why(tmp_path):
    bot = make(tmp_path)
    assert run(bot, ANA, 'roll', 'six', '#test') == RunResult(
        'failed', (), 'usage: roll [sides=6] (sides must be a whole number)')
    result = run(bot, ANA, 'broken', '', '#test')
    assert (result.status, result.lines, result.error) == ('failed', ('that went wrong',),
                                                           'ValueError: oops')
    bot._errors.records.clear()
    assert run(bot, ANA, 'slow', '', '#test') == RunResult(
        'failed', (), '!slow took longer than 0.05 seconds')


def test_a_second_run_while_the_first_is_going_is_busy(tmp_path):
    bot = make(tmp_path)

    async def both():
        return await asyncio.gather(bot.run_as(ANA, 'wait', '', '#test'),
                                    bot.run_as(ANA, 'wait', '', '#test'))
    first, second = bot.driver.loop.run_until_complete(both())
    assert first.status == 'ran'
    assert second == RunResult('busy', (), '!wait is still running for ana')


def test_a_private_run_answers_the_person(tmp_path):
    bot = make(tmp_path)
    assert run(bot, ANA, 'roll', '', None, capture=False).status == 'ran'
    bot.driver.run()
    assert bot.sent_to('ana') == ['ana rolled 6']
