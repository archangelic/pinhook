"""Recent history: per channel, in memory, and only where the config turns it on."""
from datetime import datetime, timedelta, timezone

import pytest

from pinhook.testing import TestBot

from wire import Wire

PLUGIN = '''
from pinhook import command

@command('recent')
async def recent(ctx, limit: int = 0):
    lines = ['{}{}:{}'.format('*' if e.own else '', e.nick, e.text)
             for e in ctx.history(limit or None)]
    await ctx.send('#log', ' | '.join(lines) or 'nothing')

@command('echo')
async def echo(ctx, text: str):
    await ctx.reply(text)
'''


def make(tmp_path, **history):
    (tmp_path / 'plugin.py').write_text(PLUGIN)
    return TestBot(plugin_dir=str(tmp_path), channels=('#test', '#games'),
                   history=history or None)


def recent(bot, channel='#test', limit=''):
    bot.say('!recent {}'.format(limit).strip(), channel=channel)
    return bot.sent_to('#log')[-1]


def test_history_is_off_unless_the_config_lists_the_channel(tmp_path):
    bot = make(tmp_path)
    bot.say('hello')
    assert recent(bot) == 'nothing'


def test_messages_and_the_bots_own_replies_are_kept(tmp_path):
    bot = make(tmp_path, channels=['#test'])
    bot.say('hello', nick='ana')
    bot.action('waves', nick='bob')
    bot.say('!echo hi there', nick='ana')
    assert recent(bot) == ('ana:hello | bob:waves | ana:!echo hi there | *testbot:hi there | '
                           'tester:!recent')


def test_a_plugin_only_reads_its_own_channel(tmp_path):
    bot = make(tmp_path, channels=['#test', '#games'])
    bot.say('in games', nick='ana', channel='#games')
    assert recent(bot) == 'tester:!recent'
    assert recent(bot, '#games') == 'ana:in games | tester:!recent'


def test_size_and_age_limits(tmp_path):
    bot = make(tmp_path, channels=['#test'], size=3, minutes=10)
    for n in range(5):
        bot.say('line {}'.format(n))
    assert recent(bot) == 'tester:line 3 | tester:line 4 | tester:!recent'
    assert recent(bot, limit=1) == 'tester:!recent 1'
    # eleven minutes on, everything is older than ten minutes
    later = datetime.now(timezone.utc) + timedelta(minutes=11)
    bot.history.now = lambda: later
    assert recent(bot) == 'nothing'


def test_banned_users_are_never_recorded(tmp_path):
    bot = make(tmp_path, channels=['#test'])
    bot.banned_users.append('troll')
    bot.say('spam', nick='troll')
    assert recent(bot) == 'tester:!recent'


@pytest.mark.parametrize('config, problem', [
    ({'channel': ['#test']}, "history has settings pinhook doesn't know: channel"),
    ({'channels': '#test'}, 'history.channels should be a list'),
    ({'channels': [], 'size': 0}, 'history.size should be'),
    ({'channels': [], 'minutes': 'ten'}, 'history.minutes should be'),
])
def test_config_problems_stop_the_bot_starting(tmp_path, config, problem):
    with pytest.raises(ValueError, match=problem):
        TestBot(plugin_dir=str(tmp_path), history=config)


# the bot's own lines on a real connection

def wire(tmp_path, caps):
    w = Wire(tmp_path, plugins={'plugin': PLUGIN}, history={'channels': ['#test']})
    w.connect()
    w.receive(':irc.example.net CAP * LS :' + caps, ':irc.example.net CAP * ACK :' + caps)
    w.welcome()
    w.sent()
    return w


def test_with_echo_message_the_bot_records_what_the_server_echoes(tmp_path):
    w = wire(tmp_path, 'echo-message message-tags')
    w.say('!echo hi')
    entries = w.bot.history.recent('#test')
    # sent, but not echoed yet
    assert [e.text for e in entries] == ['!echo hi']
    sent_at = datetime.now(timezone.utc).replace(microsecond=0)
    w.receive('@msgid=m9;time={} :pinbot!p@host PRIVMSG #test :hi'.format(
        sent_at.isoformat().replace('+00:00', 'Z')))
    own = w.bot.history.recent('#test')[-1]
    assert (own.text, own.own, own.msgid, own.time) == ('hi', True, 'm9', sent_at)


def test_without_echo_message_the_bot_records_what_it_sends(tmp_path):
    w = wire(tmp_path, 'account-tag')
    w.say('!echo hi')
    assert [(e.text, e.own) for e in w.bot.history.recent('#test')] == [
        ('!echo hi', False), ('hi', True)]
