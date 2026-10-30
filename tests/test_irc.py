"""The IRC transport: long lines, casemapping, channel members and reconnecting."""
import asyncio
import logging

import pytest

from pinhook import bot as pinhook_bot
from pinhook.__version__ import __version__
from pinhook.transport.base import Outgoing
from pinhook.transport.irc import IrcTransport, split_text

from wire import Wire, lines

ECHO = ("import pinhook.plugin as p\n"
        "@p.listener('echo')\n"
        "def echo(msg): return p.message(msg.text)\n")
WHO = ("import pinhook.plugin as p\n"
       "@p.command('!who')\n"
       "def who(msg): return p.message(' '.join(sorted(msg.nick_list)))\n")
WHOAMI = ("import pinhook.plugin as p\n"
          "@p.command('!whoami')\n"
          "def whoami(msg): return p.message(msg.botnick)\n")


def send(w, message):
    w.driver.loop.run_until_complete(w.bot.transport.send(message))
    return w.sent()


# long lines

def test_split_text_breaks_at_spaces():
    assert split_text('one two three four', 9) == ['one two', 'three', 'four']


def test_split_text_cuts_words_too_long_for_a_line():
    assert split_text('abcdefghij', 4) == ['abcd', 'efgh', 'ij']


def test_split_text_never_cuts_a_character_in_half():
    assert split_text('ééé', 5) == ['éé', 'é']
    assert [len(p.encode()) <= 5 for p in split_text('🎲🎲🎲', 5)] == [True] * 3


def test_split_text_splits_lines_and_drops_empty_ones():
    assert split_text('one\r\ntwo\n\nthree', 100) == ['one', 'two', 'three']
    assert split_text('', 100) == []


def relayed(sent, hostmask='!pinbot@example.com'):
    # the line as the server passes it on to everyone else. welcome() has the bot
    # join as pinbot!pinbot@example.com, so that's the hostmask it knows it has
    return ':pinbot{} {}\r\n'.format(hostmask, sent.line).encode()


def test_long_messages_are_split_to_fit_a_line(tmp_path):
    w = Wire(tmp_path).ready()
    text = ' '.join('word{}'.format(i) for i in range(200))
    sent = send(w, Outgoing('privmsg', '#test', text))
    assert len(sent) > 1
    assert ' '.join(s.text for s in sent) == text
    assert all(len(relayed(s)) <= 512 for s in sent)


def test_lines_use_the_room_left_by_the_bots_real_hostmask(tmp_path):
    w = Wire(tmp_path).ready()
    sent = send(w, Outgoing('privmsg', '#test', 'x ' * 400))
    assert 500 < len(relayed(sent[0])) <= 512


def test_lines_leave_room_for_the_longest_hostmask_until_the_bot_knows_its_own(tmp_path):
    w = Wire(tmp_path)
    w.connect()
    w.receive(':irc.example.net 001 pinbot :Welcome')
    w.sent()
    sent = send(w, Outgoing('privmsg', '#test', 'x ' * 400))
    longest = '!{}@{}'.format('u' * 10, 'h' * 63)
    assert all(len(relayed(s, longest)) <= 512 for s in sent)


def test_the_prefix_goes_on_every_line(tmp_path):
    w = Wire(tmp_path).ready()
    text = ' '.join('word{}'.format(i) for i in range(200))
    sent = send(w, Outgoing('privmsg', '#test', text, prefix='[llm model] '))
    assert len(sent) > 1
    assert all(s.text.startswith('[llm model] ') for s in sent)
    assert all(len(relayed(s)) <= 512 for s in sent)


def test_long_actions_are_split_into_actions(tmp_path):
    w = Wire(tmp_path).ready()
    sent = send(w, Outgoing('action', '#test', 'dances ' * 100))
    assert len(sent) > 1
    assert {s.command for s in sent} == {'ACTION'}
    assert all(len(relayed(s)) <= 512 for s in sent)


def test_newlines_cant_sneak_in_other_commands(tmp_path):
    w = Wire(tmp_path).ready()
    sent = send(w, Outgoing('privmsg', '#test', 'hi\r\nQUIT :bye'))
    assert lines(sent) == ['PRIVMSG #test hi', 'PRIVMSG #test QUIT :bye']


# names and casemapping

@pytest.mark.parametrize('isupport, ignored', [
    ('CHANTYPES=#', True),
    ('CHANTYPES=# CASEMAPPING=rfc1459', True),
    # with ascii, [ and { are different letters
    ('CHANTYPES=# CASEMAPPING=ascii', False),
])
def test_names_compare_by_the_servers_casemapping(tmp_path, isupport, ignored):
    w = Wire(tmp_path, plugins={'echo': ECHO}, banned_users=['Troll[1]']).ready(isupport=isupport)
    assert w.say('hello', nick='troll{1}') == ([] if ignored else ['hello'])


def test_the_nick_the_server_welcomes_is_the_bots_nick(tmp_path):
    w = Wire(tmp_path, plugins={'whoami': WHOAMI})
    w.connect()
    w.receive(':irc.example.net 433 * pinbot :Nickname is already in use',
              ':irc.example.net 001 pinbot_ :Welcome')
    assert w.say('!whoami') == ['pinbot_']


# channel members

def test_members_are_tracked_through_names_joins_and_leaving(tmp_path):
    w = Wire(tmp_path, plugins={'who': WHO}).ready()
    w.receive(':irc.example.net 353 pinbot = #test :pinbot @op +voice ~owner @+both',
              ':irc.example.net 366 pinbot #test :End of /NAMES list.')
    assert w.say('!who') == ['both op owner pinbot tester voice']
    w.receive(':newbie!n@example.com JOIN #test',
              ':voice!v@example.com PART #test',
              ':op!o@example.com KICK #test both :bye',
              ':owner!o@example.com NICK boss',
              ':tester!t@example.com QUIT :gone')
    assert w.say('!who', nick='newbie') == ['boss newbie op pinbot']


def test_member_modes_come_from_names_and_mode_changes(tmp_path):
    w = Wire(tmp_path).ready(isupport='CHANTYPES=# PREFIX=(ov)@+ CHANMODES=beI,k,l,imnpst')
    w.receive(':irc.example.net 353 pinbot = #test :pinbot @op +voice ana',
              ':irc.example.net 366 pinbot #test :End of /NAMES list.')
    modes = w.bot.transport.member_modes
    assert (modes('#test', 'OP'), modes('#test', 'voice'), modes('#test', 'ana')) == (
        {'o'}, {'v'}, set())
    # the ban and the key take an argument, the limit only when it's set, and m none
    w.receive(':op!o@example.com MODE #test +bvk-o *!*@bad ana secret voice',
              ':op!o@example.com MODE #test +lmo 10 voice',
              ':op!o@example.com MODE #test -lv ana')
    assert (modes('#test', 'voice'), modes('#test', 'ana')) == ({'o', 'v'}, set())
    w.receive(':voice!v@example.com NICK loud')
    assert modes('#test', 'loud') == {'o', 'v'}
    w.receive(':loud!v@example.com PART #test')
    assert modes('#test', 'loud') == set()


def test_leaving_a_channel_forgets_its_members(tmp_path):
    w = Wire(tmp_path).ready()
    w.join('mal')
    assert w.bot.transport.members('#test') == ['pinbot', 'mal']
    w.receive(':op!o@example.com KICK #test pinbot :out')
    assert w.bot.transport.members('#test') == []


# other lines

def test_pings_are_answered(tmp_path):
    w = Wire(tmp_path).ready()
    w.receive('PING :irc.example.net')
    assert lines(w.sent()) == ['PONG irc.example.net']


def test_ctcp_version_is_answered_and_kept_from_plugins(tmp_path):
    w = Wire(tmp_path, plugins={'echo': ECHO}).ready()
    sent = w.message('mal', '\x01VERSION\x01', target='pinbot')
    assert lines(sent) == ['NOTICE mal \x01VERSION pinhook {}\x01'.format(__version__)]


def test_twitch_asks_for_its_capabilities_after_registering(tmp_path):
    bot = pinhook_bot.TwitchBot('pinbot', '#chan', 'secret', plugin_dir=str(tmp_path / 'p'),
                                log_file=str(tmp_path / 't.log'))
    w = Wire(bot=bot)
    assert lines(w.connect()) == ['PASS oauth:secret', 'NICK pinbot', 'USER pinbot 0 * pinbot']
    w.receive(':tmi.twitch.tv 001 pinbot :Welcome, GLHF!')
    assert lines(w.sent()) == ['CAP REQ twitch.tv/membership', 'CAP REQ twitch.tv/tags',
                               'CAP REQ twitch.tv/commands', 'JOIN #chan']


# connecting and reconnecting

class Writer:
    # a connection's sending side, keeping what's sent

    def __init__(self):
        self.data = b''

    def write(self, data):
        self.data += data

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass

    def lines(self):
        return self.data.decode().split('\r\n')[:-1]


class Server:
    # each connection gets the next list of lines, then the server hangs up

    def __init__(self, *sessions):
        self.sessions = list(sessions)
        self.writers = []

    async def open_connection(self, *args, **kwargs):
        if not self.sessions:
            raise ConnectionRefusedError(61, 'Connection refused')
        reader = asyncio.StreamReader()
        for line in self.sessions.pop(0):
            reader.feed_data((line + '\r\n').encode())
        reader.feed_eof()
        self.writers.append(Writer())
        return reader, self.writers[-1]


def transport(server):
    t = IrcTransport(logging.getLogger('test'), 'irc.example.net', 6667, 'pinbot')
    t.open_connection = server.open_connection
    t.retry_first = 0.01
    return t


def test_a_dropped_connection_is_reported_and_reconnected(caplog):
    server = Server([':s 001 pinbot :Welcome'], [':s 001 pinbot :Welcome'])
    t = transport(server)

    async def main():
        running = asyncio.create_task(t.run())
        seen = []
        async for event in t.events():
            seen.append(event.type)
            if len(seen) == 4:
                await t.close()
        await running
        return seen
    assert asyncio.run(main()) == ['connected', 'disconnected', 'connected', 'disconnected']
    assert server.writers[1].lines()[:3] == ['CAP LS 302', 'NICK pinbot', 'USER pinbot 0 * pinbot']
    assert 'disconnected from irc.example.net' in caplog.text


def test_failed_connections_are_retried_until_closed(caplog):
    t = transport(Server())

    async def main():
        running = asyncio.create_task(t.run())
        await asyncio.sleep(0.1)
        await t.close()
        await asyncio.wait_for(running, 1)
    asyncio.run(main())
    assert caplog.text.count('connection refused, check the server and port') >= 2


def test_a_silent_server_is_pinged_then_given_up_on(caplog):
    t = transport(Server())
    t.ping_after = 0.05
    writer = Writer()

    async def main():
        await asyncio.wait_for(t.session(asyncio.StreamReader(), writer), 1)
    asyncio.run(main())
    assert writer.lines()[-1] == 'PING pinhook'
    assert 'the server stopped answering' in caplog.text


def test_close_sends_quit(tmp_path):
    w = Wire(tmp_path).ready()
    w.driver.loop.run_until_complete(w.bot.transport.close('bye'))
    assert lines(w.sent()) == ['QUIT bye']


# events from server lines

EVENTS = ("from pinhook import on\n"
          "@on('join')\n"
          "async def joined(ctx): await ctx.send('#log', 'join ' + ctx.nick + ' ' + ctx.channel)\n"
          "@on('kick')\n"
          "async def kicked(ctx): await ctx.send('#log', 'kick ' + ctx.kicked + ' ' + ctx.text)\n"
          "@on('mode')\n"
          "async def mode(ctx): await ctx.send('#log', 'mode ' + ' '.join(ctx.modes))\n"
          "@on('notice')\n"
          "async def notice(ctx): await ctx.send('#log', 'notice ' + ctx.text)\n")


def logged(sent):
    return [s.text for s in sent if s.target == '#log']


def test_server_lines_become_events(tmp_path):
    w = Wire(tmp_path, plugins={'events': EVENTS})
    w.connect()
    # the bot's own join isn't passed to plugins
    assert logged(w.welcome()) == []
    w.receive(':ana!a@example.com JOIN #test')
    w.receive(':op!o@example.com KICK #test troll :spamming')
    w.receive(':op!o@example.com MODE #test +o ana')
    w.receive(':ana!a@example.com NOTICE pinbot :psst')
    assert logged(w.sent()) == ['join ana #test', 'kick troll spamming', 'mode +o ana',
                                'notice psst']


def test_server_notices_and_modes_are_left_out(tmp_path):
    w = Wire(tmp_path, plugins={'events': EVENTS}).ready()
    w.receive(':irc.example.net NOTICE * :*** Looking up your hostname',
              ':irc.example.net MODE pinbot +i')
    assert logged(w.sent()) == []


def test_an_empty_name_is_not_a_channel():
    from pinhook.transport.base import is_channel
    assert not is_channel('')
    assert is_channel('#test')
