# Timers

`@every` runs a handler on a timer, while the bot is connected.

```python
from pinhook import every


@every(minutes=30)
async def reminder(ctx):
    await ctx.send('#games', 'game night is friday at 8')
```

A timer has no channel or sender, so it answers with `ctx.send(target, text)`.

## Set the interval

`@every(seconds=..., minutes=..., hours=...)` adds them together. The first run is one interval after the plugin loads, and `!reload` starts the count again.

A run still going when the next one is due is left to finish, and the next run waits for the one after.

## Turn a timer off

[`!disable reminder`](built-in-commands.md#for-ops) stops it everywhere, since a timer runs in no channel, and `!enable reminder` starts it again. Disabling its whole plugin in a channel leaves it running; `!disable <plugin> all` stops it. The name is the function's. Give it another with `name`:

```python
@every(minutes=30, name='friday')
```

## Test a timer

Time stands still in `TestBot` until the test moves it:

```python
from pinhook.testing import TestBot


def test_reminder():
    bot = TestBot(plugin_dir='plugins', channels=('#games',))
    assert bot.tick(1799) == []
    assert [s.text for s in bot.tick(1)] == ['game night is friday at 8']
```
