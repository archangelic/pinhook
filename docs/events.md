# Events

`@on` runs a handler when something happens in a channel: someone joins, a topic changes, the bot connects.

```python
from pinhook import on


@on('join')
async def greet(ctx):
    await ctx.reply(f'welcome, {ctx.nick}')
```

Handlers never see the bot's own joins or messages, so the bot never welcomes itself.

## The events

| Event | When | Extra on `ctx` |
| --- | --- | --- |
| `message` | a message that isn't a command, `/me` actions included | `text`, `kind` |
| `notice` | a notice | `text` |
| `join` | someone joins a channel | |
| `part` | someone leaves | `text`, the reason |
| `kick` | someone is kicked | `kicked`, `text` |
| `quit` | someone quits the network | `text` |
| `nick` | someone changes nick | `new_nick`. `nick` is the old one |
| `topic` | a channel's topic changes | `text`, the new topic |
| `invite` | the bot, or with `invite-notify` anyone, is invited | `invited` |
| `mode` | a channel's modes change | `modes`, like `['+o', 'mal']` |
| `netsplit` | servers split and people drop off together | `nicks`, `text` |
| `netjoin` | they come back | `nicks`, `text` |
| `connected` | the bot has connected and is about to join its channels | |
| `disconnected` | the bot has lost the connection | |

`ctx.channel` is the channel the event happened in, and `None` for events that aren't in one, like `nick` and `quit`.

## Read every message

`@on('message')` sees every message that isn't a command:

```python
from pinhook import on


@on('message')
async def thanks(ctx):
    if 'thanks gamebot' in ctx.text.lower():
        await ctx.reply('any time')
```

A netsplit is one event for everyone who left, not one per person, so a bot never answers a netsplit with a flood.

## Test an event

```python
from pinhook.testing import TestBot


def test_greet():
    bot = TestBot(plugin_dir='plugins')
    assert [s.text for s in bot.event('join', nick='ana')] == ['welcome, ana']
```

[TestBot](testbot.md#events) covers the other events.
