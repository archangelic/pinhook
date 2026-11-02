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

## Test a timer

Time stands still in `TestBot` until the test moves it:

```python
from pinhook.testing import TestBot


def test_reminder():
    bot = TestBot(plugin_dir='plugins', channels=('#games',))
    assert bot.tick(1799) == []
    assert [s.text for s in bot.tick(1)] == ['game night is friday at 8']
```
