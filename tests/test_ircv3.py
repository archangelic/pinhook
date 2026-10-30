"""IRCv3 message details: server time, tags, message IDs, cap-notify, invites and replies."""
import logging
from datetime import datetime, timezone

from pinhook.testing import Sent, TestBot
from pinhook.transport.base import Outgoing

from wire import Wire, b64_login, lines

DETAILS = '''
from pinhook import command, on

@command('when')
async def when(ctx):
    await ctx.reply('{} {}'.format(ctx.time.isoformat(), ctx.msgid))

@on('join')
async def joined(ctx):
    await ctx.send('#log', '{} joined at {}'.format(ctx.nick, ctx.time.isoformat()))

@on('invite')
async def invited(ctx):
    await ctx.send('#log', '{} invited {} to {}'.format(ctx.nick, ctx.invited, ctx.channel))
'''


def ready(tmp_path, **options):
    return Wire(tmp_path, plugins={'details': DETAILS}, **options).ready()


def test_message_details_are_asked_for(tmp_path):
    w = Wire(tmp_path)
    w.connect()
    w.receive(':irc.example.net CAP * LS :server-time message-tags invite-notify cap-notify')
    assert lines(w.sent()) == ['CAP REQ server-time message-tags invite-notify cap-notify']


def test_server_time_and_message_ids_reach_ctx(tmp_path):
    w = ready(tmp_path)
    w.join('ana')
    w.sent()
    w.receive('@time=2026-10-30T01:02:03.456Z;msgid=abc123 :ana!ana@host PRIVMSG #test :!when')
    assert [s.text for s in w.sent()] == ['2026-10-30T01:02:03.456000+00:00 abc123']


def test_events_get_the_server_time_too(tmp_path):
    w = ready(tmp_path)
    w.receive('@time=2026-10-30T01:02:03Z :bob!b@host JOIN #test')
    assert [s.text for s in w.sent() if s.target == '#log'] == [
        'bob joined at 2026-10-30T01:02:03+00:00']


def test_without_server_time_ctx_time_is_now(tmp_path):
    (tmp_path / 'details.py').write_text(DETAILS)
    bot = TestBot(plugin_dir=str(tmp_path))
    before = datetime.now(timezone.utc)
    [reply] = bot.say('!when')
    assert before <= datetime.fromisoformat(reply.split()[0]) <= datetime.now(timezone.utc)


def test_invite_notify_says_who_was_invited(tmp_path):
    w = ready(tmp_path)
    w.receive(':op!o@host INVITE ana #test', ':op!o@host INVITE pinbot #games')
    assert [s.text for s in w.sent() if s.target == '#log'] == [
        'op invited ana to #test', 'op invited pinbot to #games']


def test_testbot_invites_are_for_the_bot(tmp_path):
    (tmp_path / 'details.py').write_text(DETAILS)
    bot = TestBot(plugin_dir=str(tmp_path))
    assert bot.event('invite', nick='op', channel='#games') == [
        Sent('message', '#log', 'op invited testbot to #games')]


def test_standard_replies_are_logged_in_plain_words(tmp_path, caplog):
    w = ready(tmp_path)
    with caplog.at_level(logging.INFO):
        w.receive(':irc.example.net FAIL JOIN CHANNEL_RENAMED #old #new :#old is now #new',
                  ':irc.example.net WARN REHASH CERTS_EXPIRED :certificate expired',
                  ':irc.example.net NOTE * OPER_MESSAGE :maintenance at midnight')
    found = {(r.levelname, r.getMessage()) for r in caplog.records
             if r.getMessage().startswith('the server said')}
    assert found == {
        ('ERROR', 'the server said JOIN CHANNEL_RENAMED (#old #new): #old is now #new'),
        ('WARNING', 'the server said REHASH CERTS_EXPIRED: certificate expired'),
        ('INFO', 'the server said * OPER_MESSAGE: maintenance at midnight')}


# cap-notify

def test_new_caps_are_asked_for_and_removed_ones_dropped(tmp_path):
    w = Wire(tmp_path)
    w.connect()
    w.receive(':irc.example.net CAP * LS :cap-notify away-notify',
              ':irc.example.net CAP * ACK :cap-notify away-notify')
    w.welcome()
    w.sent()
    w.receive(':irc.example.net CAP pinbot NEW :server-time example.org/other')
    assert lines(w.sent()) == ['CAP REQ server-time']
    w.receive(':irc.example.net CAP pinbot ACK :server-time')
    # registration is over, so there's no CAP END this time
    assert lines(w.sent()) == []
    assert w.bot.transport.supports('server-time')
    w.receive(':irc.example.net CAP pinbot DEL :away-notify')
    assert not w.bot.transport.supports('away-notify')


def test_sasl_coming_back_logs_the_bot_in(tmp_path):
    w = Wire(tmp_path, sasl_password='hunter2')
    w.connect()
    # services are down, so the server doesn't offer sasl yet
    w.receive(':irc.example.net CAP * LS :cap-notify', ':irc.example.net CAP * ACK :cap-notify')
    w.welcome()
    w.sent()
    w.receive(':irc.example.net CAP pinbot NEW :sasl=PLAIN')
    assert lines(w.sent()) == ['CAP REQ sasl']
    w.receive(':irc.example.net CAP pinbot ACK :sasl')
    assert lines(w.sent()) == ['AUTHENTICATE PLAIN']
    w.receive('AUTHENTICATE +')
    assert b64_login(w.sent()) == '\0pinbot\0hunter2'
    w.receive(':irc.example.net 903 pinbot :SASL authentication successful')
    assert lines(w.sent()) == []
    assert w.bot.sasl_logged_in


def test_authenticate_is_ignored_when_the_bot_didnt_ask(tmp_path):
    w = Wire(tmp_path, sasl_password='hunter2').ready()
    w.receive('AUTHENTICATE +')
    assert lines(w.sent()) == []


# UTF8ONLY

def test_text_is_always_sent_as_valid_utf8(tmp_path):
    w = Wire(tmp_path).ready(isupport='CHANTYPES=# UTF8ONLY')
    w.driver.loop.run_until_complete(w.bot.transport.send(
        Outgoing('privmsg', '#test', 'café \udc80')))
    assert lines(w.sent()) == ['PRIVMSG #test café ?']
