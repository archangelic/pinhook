# The context

Every handler gets `ctx`: who spoke, where, how to answer, and the plugin's own data and settings. It's the only thing a handler needs from the bot.

```python
from pinhook import command


@command('whoami')
async def whoami(ctx):
    who = ctx.account or 'not logged in'
    await ctx.reply(f'{ctx.nick} in {ctx.channel}, account: {who}')
```

## Who and where

| Attribute | What it holds |
| --- | --- |
| `ctx.nick`, `ctx.user`, `ctx.host` | who sent it |
| `ctx.account` | their services account, or `None`. On Twitch, their numeric user ID |
| `ctx.channel` | where to answer: the channel, or the sender for a private message |
| `ctx.is_private` | `True` for a private message to the bot |
| `ctx.is_op` | `True` for one of the bot's [ops](bans-and-ops.md) |
| `ctx.is_chanop` | `True` for a channel operator (+o or above) in this channel |
| `ctx.is_bot` | `True` when the server marks the sender as a bot |
| `ctx.addressed` | `True` when the message started with the bot's nick, like `gamebot: roll` |
| `ctx.text` | the whole message |
| `ctx.command`, `ctx.arg` | the command's name, and everything after it |
| `ctx.time` | when it was sent, the server's time when it says |
| `ctx.tags`, `ctx.msgid` | the message's IRCv3 tags and ID |
| `ctx.bot.nick`, `ctx.bot.channels` | the bot's nick and channels, read only |
| `ctx.logger` | the bot's logger |

## Answer

```python
await ctx.reply('done')                      # where the message came from
await ctx.reply('done', thread=True)         # as a reply to this message
await ctx.reply('just you', private=True)    # a private message to the sender
await ctx.action('waves')                    # a /me
await ctx.notice('a notice to the sender')
await ctx.send('#announcements', 'liftoff')  # anywhere else
```

A string with line breaks, or a list, is sent a line at a time. Every line goes through the output queue, which keeps to the network's rate limits, so a long answer never floods the bot off the server.

`thread=True` uses the IRCv3 reply tag where the server supports it, and starts the line with the sender's nick elsewhere.

## Show it's working

```python
async with ctx.typing():
    forecast = await fetch_forecast(city)
await ctx.reply(forecast)
```

Clients that show typing notifications show the bot typing until the block ends.

## Save data

`ctx.store` is a dict saved as JSON in `data_dir` after each run of the handler, and kept between reloads and restarts. Each plugin file has its own:

```python
@command('count')
async def count(ctx):
    ctx.store['count'] = ctx.store.get('count', 0) + 1
    await ctx.reply(f"counted {ctx.store['count']} times")
```

Values are what JSON holds: strings, numbers, lists, dicts, `True`, `False` and `None`.

## Settings

`ctx.config` is the plugin's section of [`plugin_config`](options.md#commands-and-plugins), read only. `ctx.config.shared` is the section every plugin reads.

```python
@command('weather')
async def weather(ctx, city: str):
    units = ctx.config.get('units', 'metric')
    ...
```

`ctx.config['api_key']` for a setting that isn't there raises an error naming the setting and the plugin.

## The channel's people

```python
ctx.members()            # everyone in this channel, as Members
ctx.member('ana')        # one Member, or None
await ctx.whois('ana')   # asks the server, and waits for the answer
```

A `Member` has `nick`, `account`, `modes`, `is_chanop`, `is_voiced`, `away` and `is_bot`. `members()` comes from what the bot already knows, so it never waits.

## Recent messages

`ctx.history()` is this channel's recent messages, oldest first, for channels the [`history`](options.md#history) option lists:

```python
for entry in ctx.history(limit=5):
    ctx.logger.info(f'{entry.nick}: {entry.text}')
```

## What the network supports

`ctx.supports('typing')`, `ctx.supports('reply')`, `ctx.supports('notice')` and `ctx.supports('private')` say what this network does. On Twitch, notices to people and private messages aren't sent, so `ctx.reply(private=True)` answers in the channel.
