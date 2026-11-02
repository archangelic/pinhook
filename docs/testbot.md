# TestBot

`TestBot` runs the real bot on a fake network: plugins, recipes, access and the built-in commands all work, with no server and no waiting on rate limits. Stores live in memory, and a plugin that raises fails the test.

```python
from pinhook.testing import TestBot


def test_roll():
    bot = TestBot(plugin_dir='plugins')
    assert bot.say('!roll 3 1', nick='ana') == ['ana rolled 3 [1, 1, 1]']
```

## Say something

| Call | Sends | Returns |
| --- | --- | --- |
| `bot.say(text, nick='ana')` | a channel message | the bot's replies in that channel |
| `bot.action(text, nick='ana')` | a `/me` | the bot's replies in that channel |
| `bot.private(text, nick='ana')` | a private message | the bot's replies to them |

`channel=` picks the channel, the first of `channels` by default. `account=`, `user=` and `host=` say who's speaking, for ops, bans and access:

```python
bot = TestBot(plugin_dir='plugins', ops=['$a:mal'])
assert bot.say('!reload', nick='mal', account='mal') == ['Plugins reloaded']
```

## Check what else it sent

`bot.sent_to('ana')` is everything the bot sent to `ana`, like `!help`'s private reply. `bot.sent` is everything it sent, as `Sent` records with `kind`, `target` and `text`.

## Events

```python
bot.event('join', nick='ana')
bot.event('kick', nick='mal', kicked='troll', text='bye')
bot.event('nick', nick='ana', new_nick='ana_')
bot.event('mode', nick='mal', modes=['+o', 'ana'])
```

Each returns what the bot sent, as `Sent` records. A mode change gives the member that mode, the way a real one would.

## Timers

Time stands still until the test moves it. `bot.tick(1800)` lets 30 minutes pass, runs the `@every` timers that come due, and returns what they sent.

## Stores and settings

`bot.store('dice')` is the `dice` plugin's store. `TestBot` takes the bot's [options](options.md), like `plugin_config`, `access` and `recipe_dir`:

```python
bot = TestBot(plugin_dir='plugins', recipe_dir='recipes',
              plugin_config={'weather': {'units': 'metric'}})
```

## Errors

A plugin that raises, or one that can't load, fails the test with a `PluginError` and the plugin's traceback.

## Type-check plugins

pinhook ships its type hints. Run mypy on your plugins to catch mistakes like `ctx.reply(42)` or `ctx.acount` before the bot runs:

```bash
mypy plugins
```
