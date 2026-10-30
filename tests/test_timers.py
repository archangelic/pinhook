"""@every timers."""
import asyncio
import time

import pytest

from pinhook import every
from pinhook.testing import PluginError, Sent, TestBot
from pinhook.transport.base import Event, Source

from wire import Wire

HEAD = 'from pinhook import Plugin, command, every\n'
REMIND = ("@every(minutes=30)\n"
          "async def remind(ctx):\n"
          "    await ctx.send('#games', 'dice night is friday')\n")


def bot_with(tmp_path, **files):
    for name, code in files.items():
        (tmp_path / (name + '.py')).write_text(HEAD + code)
    return TestBot(plugin_dir=str(tmp_path), ops=['mal'])


def test_a_timer_runs_one_interval_after_loading_then_every_interval(tmp_path):
    bot = bot_with(tmp_path, remind=REMIND)
    assert bot.tick(1799) == []
    assert bot.tick(1) == [Sent('message', '#games', 'dice night is friday')]
    assert bot.tick(1799) == []
    assert bot.tick(1) == [Sent('message', '#games', 'dice night is friday')]


def test_a_long_gap_runs_it_once_without_catching_up(tmp_path):
    bot = bot_with(tmp_path, remind=REMIND)
    assert len(bot.tick(1800 * 10)) == 1
    assert bot.tick(1799) == []
    assert len(bot.tick(1)) == 1


def test_class_plugins_can_have_timers(tmp_path):
    bot = bot_with(tmp_path, ticker=(
        "class Ticker(Plugin):\n"
        "    def setup(self, previous):\n"
        "        self.ticks = 0\n"
        "    @every(seconds=10)\n"
        "    async def tick(self, ctx):\n"
        "        self.ticks += 1\n"
        "        await ctx.send('#test', f'tick {self.ticks}')\n"))
    assert [s.text for s in bot.tick(10) + bot.tick(10)] == ['tick 1', 'tick 2']


def test_timers_stop_when_their_plugin_is_removed(tmp_path):
    bot = bot_with(tmp_path, remind=REMIND)
    (tmp_path / 'remind.py').unlink()
    bot.say('!reload', nick='mal')
    assert bot.tick(1800) == []


def test_reload_starts_timers_over(tmp_path):
    bot = bot_with(tmp_path, remind=REMIND)
    bot.tick(1000)
    bot.say('!reload', nick='mal')
    assert bot.tick(1000) == []
    assert len(bot.tick(800)) == 1


def test_timers_can_be_switched_off(tmp_path):
    bot = bot_with(tmp_path, remind=REMIND)
    bot.say('!disable remind all', nick='mal')
    assert bot.tick(1800) == []


def test_timers_only_run_while_connected(tmp_path):
    (tmp_path / 'plugins').mkdir()
    (tmp_path / 'plugins' / 'remind.py').write_text(HEAD + REMIND)
    w = Wire(tmp_path)
    w.connect()
    w.driver.tick(1800)
    assert [s for s in w.sent() if s.command == 'PRIVMSG'] == []
    w.welcome()
    w.driver.tick(1800)
    assert [s.text for s in w.sent() if s.command == 'PRIVMSG'] == ['dice night is friday']


def test_a_timer_has_nowhere_to_reply(tmp_path):
    bot = bot_with(tmp_path, bad="@every(seconds=5)\nasync def bad(ctx): await ctx.reply('hi')\n")
    with pytest.raises(PluginError, match='use ctx.send'):
        bot.tick(5)


def test_every_needs_a_time_and_an_async_function():
    with pytest.raises(ValueError, match='every\\(\\) needs a time'):
        every()
    with pytest.raises(TypeError, match='has to be async'):
        every(seconds=5)(lambda ctx: None)


def test_the_real_scheduler_runs_timers_and_never_overlaps_one(tmp_path):
    (tmp_path / 'fast.py').write_text(HEAD + (
        "import asyncio\n"
        "@every(seconds=0.05)\n"
        "async def fast(ctx):\n"
        "    await ctx.send('#test', 'fast')\n"
        "@every(seconds=0.05)\n"
        "async def slow(ctx):\n"
        "    await ctx.send('#test', 'slow')\n"
        "    await asyncio.sleep(0.3)\n"))
    bot = TestBot(plugin_dir=str(tmp_path), ops=['mal'])
    # the real clock, not TestBot's
    bot.clock = time.monotonic
    bot.reset_timers()

    async def main():
        running = asyncio.create_task(bot.run())
        await asyncio.sleep(0.45)
        bot.transport.queue.put_nowait(Event('message', Source('mal', 'mal', 'h'), '#test',
                                             '!quit', 'privmsg'))
        await asyncio.wait_for(running, 5)
    asyncio.run(main())
    texts = bot.sent_to('#test')
    assert texts.count('fast') >= 4
    assert texts.count('slow') <= 2
