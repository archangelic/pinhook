"""The async core: each message handled on its own, slow and broken plugins, quitting."""
import asyncio

from pinhook.testing import TestBot
from pinhook.transport.base import Event, Outgoing, Source

from wire import Wire

PING = ("@p.command('!ping')\n"
        "def ping(msg): return p.message('pong')\n")
SLOW = ("@p.command('!slow')\n"
        "def slow(msg):\n"
        "    time.sleep(0.3)\n"
        "    return p.message('done ' + msg.nick)\n")


def plugins(tmp_path, **files):
    for name, code in files.items():
        (tmp_path / (name + '.py')).write_text(
            'import time\nimport pinhook.plugin as p\n' + code)
    return str(tmp_path)


def message(nick, text, channel='#test'):
    return Event('message', Source(nick, nick, 'example.com'), channel, text, 'privmsg')


# slow and broken plugins

def test_other_messages_are_answered_while_a_plugin_is_slow(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, slow=SLOW, ping=PING))
    bot.driver.run(message('mal', '!slow'), message('kim', '!ping'))
    assert bot.sent_to('#test') == ['pong', 'done mal']


def test_a_busy_command_ignores_the_same_person_until_it_finishes(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, slow=SLOW))
    bot.driver.run(message('mal', '!slow'), message('mal', '!slow'), message('kim', '!slow'))
    assert sorted(bot.sent_to('#test')) == ['done kim', 'done mal']
    assert bot.say('!slow', nick='mal') == ['done mal']


def test_a_plugin_past_its_timeout_is_given_up_on(tmp_path, caplog):
    bot = TestBot(plugin_dir=plugins(tmp_path, slow=SLOW))
    bot.handler_timeout = 0.05
    assert bot.say('!slow') == []
    assert '!slow took longer than 0.05 seconds' in caplog.text


def test_a_crashing_command_says_nothing_and_the_bot_carries_on(tmp_path, caplog):
    w = Wire(tmp_path, plugins={'crash': (
        "import pinhook.plugin as p\n"
        "@p.command('!crash')\n"
        "def crash(msg): raise RuntimeError('oops')\n"
        "@p.command('!ping')\n"
        "def ping(msg): return p.message('pong')\n")}).ready()
    assert w.say('!crash') == []
    assert 'issue with command !crash' in caplog.text
    assert w.say('!ping') == ['pong']


# the output queue

def test_a_flood_past_the_backlog_is_cut_off(tmp_path, caplog):
    bot = TestBot(plugin_dir=plugins(tmp_path, flood=(
        "@p.command('!flood')\n"
        "def flood(msg): return p.message([str(i) for i in range(60)])\n")))
    assert bot.say('!flood') == [str(i) for i in range(50)]
    assert caplog.text.count('50 lines are already waiting to go to #test') == 1
    assert bot.pauses == [2] * 46


def test_a_disconnect_drops_what_was_waiting(tmp_path, caplog):
    bot = TestBot(plugin_dir=plugins(tmp_path, ping=PING))
    bot.output.put(Outgoing('privmsg', '#test', 'stale'))
    bot.driver.run(Event('disconnected'))
    assert bot.sent == []
    assert 'disconnected, dropping 1 messages' in caplog.text


def test_a_prefix_goes_in_front_of_the_line(tmp_path):
    w = Wire(tmp_path).ready()
    w.sent()
    asyncio.run(w.bot.transport.send(Outgoing('privmsg', '#test', 'hello', prefix='[note] ')))
    assert [s.text for s in w.sent()] == ['[note] hello']


# running and quitting

def run_until_quit(bot, *events):
    async def main():
        running = asyncio.create_task(bot.run())
        for event in events:
            bot.transport.queue.put_nowait(event)
        await asyncio.wait_for(running, 5)
    asyncio.run(main())


def test_run_answers_until_quit(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, ping=PING), ops=['mal'])
    run_until_quit(bot, Event('connected'), message('kim', '!ping'), message('mal', '!quit bye'))
    assert bot.sent_to('#test') == ['pong']
    assert bot.quit_message == 'bye'


def test_quitting_waits_for_answers_on_their_way(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, slow=SLOW), ops=['mal'])
    run_until_quit(bot, message('kim', '!slow'), message('mal', '!quit'))
    assert bot.sent_to('#test') == ['done kim']
    assert bot.quit_message == "See y'all later!"


def test_nothing_is_handled_after_quit(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, ping=PING, echo=(
        "@p.listener('echo')\n"
        "def echo(msg): return p.message(msg.text)\n")), ops=['mal'])
    run_until_quit(bot, message('mal', '!quit'), message('kim', '!ping'))
    assert bot.sent_to('#test') == []
