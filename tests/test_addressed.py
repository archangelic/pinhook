"""@on('addressed'): a plugin that takes messages starting with the bot's nick."""
from pinhook.testing import TestBot

DICE = '''
from pinhook import command

@command('roll')
async def roll(ctx, sides: int = 6):
    await ctx.reply('rolled {}'.format(sides))
'''
CHAT = '''
from pinhook import on

@on('addressed')
async def chat(ctx):
    await ctx.reply('{} said {!r}, addressed: {}'.format(ctx.nick, ctx.arg, ctx.addressed))
'''
ECHO = '''
from pinhook import on

@on('message')
async def echo(ctx):
    if ctx.addressed:
        await ctx.reply('echo: ' + ctx.text)
'''


def bot_with(tmp_path, **files):
    for name, code in files.items():
        (tmp_path / (name + '.py')).write_text(code)
    return TestBot(plugin_dir=str(tmp_path), ops=['mal'])


def test_an_addressed_message_goes_to_the_handler_with_the_rest_in_arg(tmp_path):
    bot = bot_with(tmp_path, chat=CHAT)
    assert bot.say('testbot: what is on tonight?', nick='ana') == [
        "ana said 'what is on tonight?', addressed: True"]
    assert bot.say('@testbot hi', nick='ana') == ["ana said 'hi', addressed: True"]


def test_a_message_that_isnt_addressed_never_reaches_it(tmp_path):
    bot = bot_with(tmp_path, chat=CHAT)
    assert bot.say('what is on tonight?') == []


def test_a_command_after_the_nick_goes_to_the_handler_instead(tmp_path):
    bot = bot_with(tmp_path, chat=CHAT, dice=DICE)
    assert bot.say('testbot: roll two d20s for mal', nick='ana') == [
        "ana said 'roll two d20s for mal', addressed: True"]
    assert bot.say('testbot: help', nick='ana') == ["ana said 'help', addressed: True"]


def test_commands_with_their_prefix_still_run(tmp_path):
    bot = bot_with(tmp_path, chat=CHAT, dice=DICE)
    assert bot.say('!roll 20') == ['rolled 20']
    assert bot.say('testbot: !roll 12') == ['rolled 12']


def test_without_a_handler_a_command_after_the_nick_runs(tmp_path):
    bot = bot_with(tmp_path, dice=DICE)
    assert bot.say('testbot: roll 8') == ['rolled 8']


def test_switched_off_in_a_channel_commands_after_the_nick_run_there_again(tmp_path):
    bot = bot_with(tmp_path, chat=CHAT, dice=DICE)
    bot.say('!disable chat', nick='mal')
    assert bot.say('testbot: roll 8') == ['rolled 8']
    assert bot.say('testbot: roll 8', channel='#other') == ["tester said 'roll 8', addressed: True"]


def test_listeners_still_see_the_message(tmp_path):
    bot = bot_with(tmp_path, chat=CHAT, echo=ECHO)
    assert sorted(bot.say('testbot: hi', nick='ana')) == [
        "ana said 'hi', addressed: True", 'echo: testbot: hi']


def test_help_lists_it_with_the_listeners(tmp_path):
    bot = bot_with(tmp_path, chat=CHAT)
    bot.say('!help', nick='ana')
    assert 'listeners: chat' in bot.sent_to('ana')[0]
