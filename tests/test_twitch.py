"""Twitch: its rate limits, message length, repeats, badges, and no notices or whispers."""
import logging

from pinhook import bot as pinhook_bot
from pinhook.transport.base import Outgoing
from pinhook.transport.irc import TwitchTransport

from wire import Wire, lines

PLUGIN = '''
from pinhook import command

@command('roles')
async def roles(ctx):
    await ctx.reply('chanop={}'.format(ctx.is_chanop))

@command('psst')
async def psst(ctx):
    await ctx.notice('a secret')
    await ctx.notice(ctx.channel, 'for everyone')

@command('private')
async def private(ctx):
    await ctx.reply('just you', private=True)

@command('mod', restricted=True)
async def mod(ctx):
    await ctx.reply('mods only')

@command('me')
async def me(ctx):
    await ctx.action('waves')
'''


def twitch(tmp_path, **options):
    (tmp_path / 'plugins').mkdir(exist_ok=True)
    (tmp_path / 'plugins' / 'plugin.py').write_text(PLUGIN)
    bot = pinhook_bot.TwitchBot('pinbot', '#chan', 'secret', plugin_dir=str(tmp_path / 'plugins'),
                                log_file=str(tmp_path / 't.log'), data_dir=str(tmp_path / 'data'),
                                **options)
    w = Wire(bot=bot)
    w.connect()
    w.receive(':tmi.twitch.tv 001 pinbot :Welcome, GLHF!',
              ':tmi.twitch.tv CAP * ACK :twitch.tv/membership',
              ':pinbot!pinbot@pinbot.tmi.twitch.tv JOIN #chan')
    w.sent()
    return w


def say(w, text, nick='viewer', badges=''):
    tags = '@badges={};display-name={} '.format(badges, nick)
    w.receive('{}:{}!{}@{}.tmi.twitch.tv PRIVMSG #chan :{}'.format(tags, nick, nick, nick, text))
    return w.sent()


def test_the_capabilities_twitch_acks_are_recorded(tmp_path):
    w = twitch(tmp_path)
    assert w.bot.transport.supports('twitch.tv/membership')
    # and twitch has no WHO, so none is sent on joining
    assert not any(line.startswith('WHO') for line in lines(w.sent()))


def test_rate_limits_are_twitchs(tmp_path):
    limits = TwitchTransport.limits
    assert (limits.burst, limits.interval, limits.per_target) == (20, 1.5, 1.0)


def test_one_line_a_second_per_channel_unless_the_bot_is_a_mod(tmp_path):
    w = twitch(tmp_path)
    for n in range(3):
        w.bot.send_message('privmsg', '#chan', 'line {}'.format(n))
    w.driver.run()
    assert w.pauses == [1.0, 1.0]
    w.receive('@badges=moderator/1;mod=1 :tmi.twitch.tv USERSTATE #chan')
    for n in range(3):
        w.bot.send_message('privmsg', '#chan', 'more {}'.format(n))
    w.driver.run()
    assert w.pauses == [1.0, 1.0]


def test_long_messages_are_split_at_500_characters(tmp_path):
    w = twitch(tmp_path)
    w.driver.loop.run_until_complete(w.bot.transport.send(
        Outgoing('privmsg', '#chan', 'é' * 600)))
    assert [len(s.text) for s in w.sent()] == [500, 100]


def test_a_repeat_gets_an_invisible_character_so_twitch_takes_it(tmp_path):
    w = twitch(tmp_path)
    for _ in range(3):
        w.driver.loop.run_until_complete(w.bot.transport.send(Outgoing('privmsg', '#chan',
                                                                       'gg')))
    assert [s.text for s in w.sent()] == ['gg', 'gg \U000E0000', 'gg']


def roles(w, nick, badges):
    # the same reply twice running gets the invisible character, which doesn't matter here
    return [s.text.removesuffix(TwitchTransport.repeat_mark) for s in say(w, '!roles', nick,
                                                                          badges)]


def test_mods_and_the_broadcaster_are_chanops(tmp_path):
    w = twitch(tmp_path)
    assert roles(w, 'amod', 'moderator/1') == ['chanop=True']
    assert roles(w, 'streamer', 'broadcaster/1') == ['chanop=True']
    assert roles(w, 'viewer', 'subscriber/12') == ['chanop=False']
    # a mod who's lost the badge isn't one any more
    assert roles(w, 'amod', '') == ['chanop=False']


def test_the_chanops_access_group_works_with_badges(tmp_path):
    w = twitch(tmp_path, access={'plugins': {'plugin': {'commands': {
        'mod': {'allow': ['chanops']}}}}})
    assert say(w, '!mod', 'viewer') == []
    assert [s.text for s in say(w, '!mod', 'amod', 'moderator/1')] == ['mods only']


def test_notices_go_to_the_channel_or_nowhere(tmp_path, caplog):
    w = twitch(tmp_path)
    with caplog.at_level(logging.WARNING):
        sent = say(w, '!psst')
        say(w, '!psst')
    assert lines(sent) == ['PRIVMSG #chan for everyone']
    assert caplog.text.count('plugin plugin sent a notice to viewer') == 1


def test_private_replies_are_addressed_in_the_channel(tmp_path):
    w = twitch(tmp_path)
    assert lines(say(w, '!private')) == ['PRIVMSG #chan viewer: just you']


def test_help_answers_in_the_channel(tmp_path):
    w = twitch(tmp_path)
    assert all(s.target == '#chan' for s in say(w, '!help'))
    assert [s.text for s in say(w, '!help !roles')] == ['!roles -- N/A', 'usage: roles']


def test_actions_are_sent_with_me(tmp_path):
    w = twitch(tmp_path)
    assert lines(say(w, '!me')) == ['PRIVMSG #chan /me waves']
