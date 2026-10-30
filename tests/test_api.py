"""The 2.0 plugin API: commands with typed arguments, @on events and class plugins."""
import asyncio

import pytest

from pinhook import Plugin, command, on
from pinhook.testing import PluginError, Sent, TestBot

HEAD = 'from typing import Annotated, Literal\nfrom pinhook import Plugin, command, on\n'


def bot_with(tmp_path, ops=('mal',), **files):
    for name, code in files.items():
        (tmp_path / (name + '.py')).write_text(HEAD + code)
    return TestBot(plugin_dir=str(tmp_path), ops=list(ops))


DICE = '''
@command('roll', help='roll dice, e.g. roll 2d6')
async def roll(ctx, dice: Annotated[str, 'dice like 2d6'] = '1d6', times: int = 1):
    await ctx.reply(f'{ctx.nick} rolled {dice} {times} times')
'''


# commands

def test_a_function_command_gets_typed_arguments(tmp_path):
    bot = bot_with(tmp_path, dice=DICE)
    assert bot.say('!roll 2d20 3', nick='ana') == ['ana rolled 2d20 3 times']
    assert bot.say('!roll') == ['tester rolled 1d6 1 times']


def test_bad_input_gets_the_usage_line(tmp_path):
    bot = bot_with(tmp_path, dice=DICE)
    assert bot.say('!roll 2d20 three') == [
        'usage: roll [dice=1d6] [times=1] (times must be a whole number)']


def test_help_for_one_command_shows_its_usage_and_arguments(tmp_path):
    bot = bot_with(tmp_path, dice=DICE)
    bot.say('!help roll', nick='ana')
    assert bot.sent_to('ana') == ['!roll -- roll dice, e.g. roll 2d6',
                                  'usage: roll [dice=1d6] [times=1]', 'dice: dice like 2d6']
    bot.say('!help nope', nick='ana')
    assert bot.sent_to('ana')[-1] == "there's no command called nope"


def test_help_falls_back_to_the_docstring(tmp_path):
    bot = bot_with(tmp_path, hi=(
        "@command('hi')\n"
        "async def hi(ctx):\n"
        "    '''say hello\n\n    longer words that help leaves out'''\n"
        "    await ctx.reply('hello')\n"))
    bot.say('!help !hi', nick='ana')
    assert bot.sent_to('ana') == ['!hi -- say hello', 'usage: hi']


def test_errors_are_logged_and_only_said_when_the_author_chose_words(tmp_path, caplog):
    bot = TestBot(plugin_dir=str(tmp_path))
    (tmp_path / 'broken.py').write_text(HEAD + (
        "@command('quiet')\nasync def quiet(ctx): raise ValueError('oops')\n"
        "@command('loud', error_msg='the weather service is down')\n"
        "async def loud(ctx): raise ValueError('oops')\n"))
    bot.registry.load(bot.plugin_dir)
    with pytest.raises(PluginError, match='issue with command !quiet'):
        bot.say('!quiet')
    with pytest.raises(PluginError, match='issue with command !loud'):
        bot.say('!loud')
    assert bot.sent_to('#test') == ['the weather service is down']


def test_a_command_past_its_own_timeout_is_cancelled(tmp_path, caplog):
    bot = bot_with(tmp_path, slow=(
        "import asyncio\n"
        "@command('slow', timeout=0.05, error_msg='too slow')\n"
        "async def slow(ctx):\n"
        "    await asyncio.sleep(5)\n"
        "    await ctx.reply('done')\n"))
    assert bot.say('!slow') == ['too slow']
    assert '!slow took longer than 0.05 seconds' in caplog.text


def test_ops_commands_tell_others_the_denied_message(tmp_path):
    bot = bot_with(tmp_path, admin=(
        "@command('shutdown', ops=True, denied_msg='ops only')\n"
        "async def shutdown(ctx): await ctx.reply('bye')\n"))
    assert bot.say('!shutdown', nick='troll') == ['ops only']
    assert bot.say('!shutdown', nick='mal') == ['bye']


def test_returning_a_value_is_ignored_with_a_warning(tmp_path, caplog):
    bot = bot_with(tmp_path, ret="@command('ret')\nasync def ret(ctx): return 'hi'\n")
    assert bot.say('!ret') == []
    assert 'answer with ctx.reply()' in caplog.text


def test_native_and_1x_commands_share_names(tmp_path):
    (tmp_path / 'a.py').write_text(HEAD + DICE)
    (tmp_path / 'b.py').write_text(
        "import pinhook.plugin as p\n@p.command('!roll')\ndef roll(msg): pass\n")
    with pytest.raises(PluginError, match='plugin b registers command !roll, which plugin a'):
        TestBot(plugin_dir=str(tmp_path))


def test_handlers_have_to_be_async():
    with pytest.raises(TypeError, match='has to be async'):
        command('sync')(lambda ctx: None)


def test_command_names_are_written_without_a_prefix():
    with pytest.raises(ValueError, match='without a prefix'):
        command('!roll')


def test_unsupported_argument_types_fail_the_plugin(tmp_path):
    with pytest.raises(PluginError, match='plugin odd: .* commands take str'):
        bot_with(tmp_path, odd="@command('odd')\nasync def odd(ctx, when: list = None): pass\n")


# class plugins

COUNTER = '''
class Counter(Plugin):
    """count things"""
    def setup(self, previous):
        self.count = previous.count if previous else 0
        log.append(('setup', id(self), previous is not None))

    def teardown(self):
        log.append(('teardown', id(self)))

    @command('count')
    async def bump(self, ctx, by: int = 1):
        self.count += by
        await ctx.reply(str(self.count))
'''


def counter_bot(tmp_path, log):
    import builtins
    builtins.__dict__['log'] = log
    return bot_with(tmp_path, counter=COUNTER)


def test_class_plugins_keep_state_through_reload(tmp_path):
    log = []
    bot = counter_bot(tmp_path, log)
    assert bot.say('!count 2') == ['2']
    bot.say('!reload', nick='mal')
    assert bot.say('!count') == ['3']
    first, second = log[0][1], log[1][1]
    # the new instance gets set up with the old one, then the old one is torn down
    assert log == [('setup', first, False), ('setup', second, True), ('teardown', first)]


def test_teardown_runs_when_the_plugin_is_removed(tmp_path):
    log = []
    bot = counter_bot(tmp_path, log)
    (tmp_path / 'counter.py').unlink()
    bot.say('!reload', nick='mal')
    assert log[-1][0] == 'teardown'
    assert bot.say('!count') == []


def test_teardown_runs_when_the_bot_quits(tmp_path):
    from pinhook.transport.base import Event, Source
    log = []
    bot = counter_bot(tmp_path, log)

    async def main():
        running = asyncio.create_task(bot.run())
        bot.transport.queue.put_nowait(Event('message', Source('mal', 'mal', 'h'), '#test',
                                             '!quit', 'privmsg'))
        await asyncio.wait_for(running, 5)
    asyncio.run(main())
    assert log[-1][0] == 'teardown'


def test_a_setup_that_fails_tears_down_what_was_set_up(tmp_path):
    import builtins
    log = []
    builtins.__dict__['log'] = log
    (tmp_path / 'two.py').write_text(HEAD + (
        "class A(Plugin):\n"
        "    def setup(self, previous): log.append('a setup')\n"
        "    def teardown(self): log.append('a teardown')\n"
        "class B(Plugin):\n"
        "    def setup(self, previous): raise RuntimeError('no')\n"))
    with pytest.raises(PluginError, match='could not load plugin two'):
        TestBot(plugin_dir=str(tmp_path))
    assert log == ['a setup', 'a teardown']


def test_plugins_can_be_switched_off_by_file_name(tmp_path):
    log = []
    bot = counter_bot(tmp_path, log)
    bot.say('!disable counter', nick='mal')
    assert bot.say('!count') == []


# events

EVENTS = '''
@on('join')
async def welcome(ctx):
    await ctx.notice(ctx.nick, f'welcome to {ctx.channel}')

@on('part')
async def bye(ctx):
    await ctx.send('#log', f'{ctx.nick} left {ctx.channel}: {ctx.text}')

@on('kick')
async def kicked(ctx):
    await ctx.send('#log', f'{ctx.nick} kicked {ctx.kicked}: {ctx.text}')

@on('nick')
async def renamed(ctx):
    await ctx.send('#log', f'{ctx.nick} is now {ctx.new_nick}, channel {ctx.channel}')

@on('quit')
async def gone(ctx):
    await ctx.send('#log', f'{ctx.nick} quit: {ctx.text}')

@on('topic')
async def topic(ctx):
    await ctx.send('#log', f'topic in {ctx.channel} is {ctx.text}')

@on('invite')
async def invited(ctx):
    await ctx.send('#log', f'{ctx.nick} invited me to {ctx.channel}')

@on('mode')
async def mode(ctx):
    await ctx.send('#log', f'{ctx.nick} set {ctx.modes} on {ctx.channel}')

@on('message')
async def heard(ctx):
    await ctx.send('#log', f'heard {ctx.text} addressed={ctx.addressed}')

@on('notice')
async def noticed(ctx):
    await ctx.send('#log', f'notice {ctx.text}')
'''


@pytest.mark.parametrize('kind, options, logged', [
    ('part', dict(text='brb'), 'ana left #test: brb'),
    ('kick', dict(kicked='troll', text='spam'), 'ana kicked troll: spam'),
    ('nick', dict(new_nick='ana_'), 'ana is now ana_, channel None'),
    ('quit', dict(text='gone'), 'ana quit: gone'),
    ('topic', dict(text='dice night'), 'topic in #test is dice night'),
    ('invite', dict(channel='#games'), 'ana invited me to #games'),
    ('mode', dict(modes=['+o', 'mal']), "ana set ['+o', 'mal'] on #test"),
    ('notice', dict(text='psst'), 'notice psst'),
])
def test_events_reach_their_handlers(tmp_path, kind, options, logged):
    bot = bot_with(tmp_path, events=EVENTS)
    assert bot.event(kind, nick='ana', **options) == [Sent('message', '#log', logged)]


def test_join_handlers_can_greet(tmp_path):
    bot = bot_with(tmp_path, events=EVENTS)
    assert bot.event('join', nick='ana') == [Sent('notice', 'ana', 'welcome to #test')]


def test_message_handlers_see_messages_that_arent_commands(tmp_path):
    bot = bot_with(tmp_path, events=EVENTS + DICE)
    bot.say('hello')
    bot.say('testbot: hi there')
    bot.say('!roll')
    assert bot.sent_to('#log') == ['heard hello addressed=False',
                                   'heard testbot: hi there addressed=True']


def test_notices_never_run_commands(tmp_path):
    bot = bot_with(tmp_path, dice=DICE)
    assert bot.event('notice', text='!roll') == []


def test_banned_users_events_are_ignored(tmp_path):
    bot = bot_with(tmp_path, events=EVENTS)
    bot.banned_users.append('troll')
    assert bot.event('join', nick='troll') == []


def test_an_event_handler_that_has_nowhere_to_answer_says_so(tmp_path):
    bot = bot_with(tmp_path, quits="@on('quit')\nasync def q(ctx): await ctx.reply('bye')\n")
    with pytest.raises(PluginError, match='use ctx.send'):
        bot.event('quit', nick='ana')


def test_on_only_takes_known_events():
    with pytest.raises(ValueError, match="@on takes one of"):
        on('sneeze')


def test_plugin_is_exported_for_subclassing():
    assert issubclass(type('Mine', (Plugin,), {}), Plugin)
