# Testing plugins

`pinhook.testing` runs your plugins in a bot that never connects to a server, so you can test them with pytest or any other test runner.

```python
from pinhook.testing import TestBot

def test_roll():
    bot = TestBot(plugin_dir='plugins')
    assert bot.say('!roll 1d1') == ['1']
```

`TestBot` is a real `Bot`. Plugins, ops, bans and the [built-in commands](commands.md) all work the way they do on a server. The difference is that what the bot sends is recorded for you to check, flood protection pauses are skipped, and no log or ban files are written.

!!! note
    `TestBot` is new in 1.12.

## Talking to the bot

Three methods send the bot a message and return its replies, as a list of strings:

| Method | Sends | Returns the replies sent to |
| --- | --- | --- |
| `bot.say(text)` | a message in a channel | that channel |
| `bot.action(text)` | a `/me` action in a channel | that channel |
| `bot.private(text)` | a private message to the bot | the sender |

Replies include both messages and actions. Each takes the same optional arguments:

* `nick`: who's talking (default: `'tester'`)
* `channel`: which channel, for `say` and `action` (default: the bot's first channel, `'#test'`)
* `user` and `host`: the rest of their hostmask (default: the nick, and `'example.com'`)
* `account`: the services account they're logged in to (default: none)

```python
def test_greeting():
    bot = TestBot()
    assert bot.say('hello everyone', nick='mal') == ['hi mal!']
    assert bot.say('hello', channel='#other') == ['hi tester!']
```

## Checking everything that was sent

`bot.sent` is everything the bot has sent, as `Sent(kind, target, text)` entries, where `kind` is `'message'`, `'action'` or `'notice'`. Use it to check notices, or messages a plugin sent somewhere else:

```python
from pinhook.testing import Sent, TestBot

def test_whisper():
    bot = TestBot()
    bot.say('!whisper', nick='mal')
    assert Sent('notice', 'mal', 'psst') in bot.sent
```

`bot.sent_to(target)` returns the text of every message and action sent to one place. `!help`, for example, replies privately, so check it like this:

```python
def test_help_lists_roll():
    bot = TestBot()
    bot.say('!help', nick='mal')
    assert '!roll -- roll some dice' in bot.sent_to('mal')
```

## Options, ops and bans

`TestBot` takes any of the bot's [options](options.md), so you can test ops and bans the same way they're set up for real:

```python
def test_only_ops_can_announce():
    bot = TestBot(ops=['$a:mal'])
    assert bot.say('!announce hi', nick='mal', account='mal') == ['announced']
    assert bot.say('!announce hi', nick='mal') == ['only ops can announce']
```

It also takes `nickname` (default: `'testbot'`) and `channels` (default: `['#test']`).

## When a plugin breaks

On a real server, a plugin that raises an exception is logged and the bot carries on. In a `TestBot` it fails the test instead: you get a `PluginError` with the original exception and its traceback attached. The same happens when a plugin returns something other than `message()` or `action()`, or when a plugin file can't be loaded at all. That one fails as soon as you create the `TestBot`.

```python
import pytest
from pinhook.testing import PluginError, TestBot

def test_zero_sided_dice_crash():
    bot = TestBot()
    with pytest.raises(PluginError):
        bot.say('!roll 1d0')
```

Turning logging off with `log_level='off'` turns this off too, because the errors are caught from the bot's log.

## Other things to know

* `bot.pauses` lists the flood protection pauses the bot would have taken, in seconds
* `!quit` raises `SystemExit`, so wrap it in `pytest.raises(SystemExit)`. `bot.quit_message` holds the message it quit with
* `!join` adds the channel to `bot.channels`
* plugins are shared by every bot in the same python process, so make one `TestBot` at a time
