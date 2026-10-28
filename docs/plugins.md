# Writing plugins

A plugin is a `.py` file in the bot's [plugin folder](options.md#plugin_dir) with one or more decorated functions in it. There are two kinds:

* **Commands** run when a message starts with their command word, like `!roll 2d6`
* **Listeners** see every message that isn't a command, and decide for themselves what to do

## Commands

```python
import random

import pinhook.plugin

@pinhook.plugin.command('!roll', help_text='roll a die, or !roll 20 for a d20')
def roll(msg):
    sides = int(msg.arg) if msg.arg.isdigit() else 6
    return pinhook.plugin.message('{} rolled a {}'.format(msg.nick, random.randint(1, sides)))
```

The function gets one argument, the [message](#the-message). `msg.arg` holds everything after the command word.

`@command` takes:

| Argument | Default | What it does |
| --- | --- | --- |
| `help_text` | `'N/A'` | shown next to the command in `!help` |
| `ops` | `False` | only [ops](bans-and-ops.md) can run it |
| `ops_msg` | `''` | what anyone else gets told when they try. Empty means no reply |
| `hide` | `False` | leave it out of `!help` |

```python
@pinhook.plugin.command('!shutdown-games', ops=True, ops_msg='only ops can do that')
def shutdown_games(msg):
    return pinhook.plugin.message('games are closed for tonight')

@pinhook.plugin.command('!secret', hide=True)
def secret(msg):
    return pinhook.plugin.message('you found it!')
```

## Listeners

A listener is given a name instead of a command word. It's called for every message that isn't a command, including `/me` actions, and returns nothing when it has nothing to say.

```python
import pinhook.plugin

@pinhook.plugin.listener('hello')
def say_hi(msg):
    if 'hello' in msg.text.lower():
        return pinhook.plugin.message('hi {}!'.format(msg.nick))
```

## Replying

There are two ways to reply: return what to say, or say it straight away.

Return one of these to reply where the message came from, the channel or the private message:

* `pinhook.plugin.message(text)`: a normal message
* `pinhook.plugin.action(text)`: a `/me` action

Both take a string or a list of strings. Each line is sent as its own message, with a short pause between lines so the bot doesn't flood the channel.

```python
return pinhook.plugin.message(['line one', 'line two'])
```

Returning anything else, like a plain string, is logged as an error and nothing is sent.

Or use the message's methods, which send straight away, so a plugin can reply more than once or send to several places:

| Method | Sends |
| --- | --- |
| `msg.reply(text)` | a message where this one came from |
| `msg.action(text)` | a `/me` action where this one came from |
| `msg.notice(text)` | a notice to the sender only |
| `msg.send(target, text)` | a message to another channel or nick |
| `msg.action(target, text)` | a `/me` action to another channel or nick |
| `msg.notice(target, text)` | a notice to another channel or nick |

```python
@pinhook.plugin.command('!countdown')
def countdown(msg):
    msg.reply('3... 2... 1...')
    msg.send('#announcements', 'liftoff in {}'.format(msg.channel))
    msg.notice('thanks for launching!')
```

They get the same line splitting and flood protection as returned replies. `msg.reply`, `msg.send` and the one-argument forms are new in 1.12. `msg.privmsg(target, text)` still works too.

## The message

| Attribute | What it is |
| --- | --- |
| `nick` | who sent it |
| `user` | the username part of their hostmask (`nick!user@host`) |
| `account` | the services account they're logged in to, or `None`. Needs a server with account tags, see [Bans and ops](bans-and-ops.md) |
| `channel` | where it was sent. For a private message, the sender's nick |
| `is_private` | `True` if it was a private message to the bot |
| `cmd` | (commands) the command word that triggered it |
| `arg` | (commands) everything after the command word |
| `text` | (listeners) the whole message |
| `msg_type` | `"message"`, or `"action"` for a `/me` |
| `nick_list` | nicks in the channel. Just the sender for private messages |
| `is_op` | `True` if the sender is a bot operator. Understands accounts and hostmasks, so use it rather than `nick in msg.ops` |
| `ops` | the list of bot operators, as written in the config |
| `botnick` | the bot's current nick |
| `store` | the plugin's saved data, see [Saving data](#saving-data) |
| `config` | the plugin's settings, see [Settings](#settings) |
| `logger` | the bot's logger, see [Logging](#logging) |
| `datetime` | when the message arrived, a timezone-aware `datetime` |
| `timestamp` | the same as a unix timestamp |
| `bot` | the bot itself. Deprecated, see [Preparing for 2.0](preparing-for-2.md) |

`account`, `is_private`, `store` and `config` are new in 1.12.

## Saving data

`msg.store` is a dictionary the plugin can keep things in. It's still there in the next message, after `!reload` and after the bot restarts:

```python
@pinhook.plugin.command('!karma')
def karma(msg):
    scores = msg.store.setdefault('scores', {})
    scores[msg.arg] = scores.get(msg.arg, 0) + 1
    return pinhook.plugin.message('{} has {} karma'.format(msg.arg, scores[msg.arg]))
```

* Each plugin file has its own store, named after the file. Commands and listeners in the same file share it
* The bot saves it after each plugin call if anything changed, including changes inside nested lists and dicts. There's nothing to call
* It's saved as `<plugin file name>.json` in [`data_dir`](options.md#data_dir), so `karma.py` keeps its data in `data/karma.json`
* Values have to be things JSON can hold: strings, numbers, lists, dicts, `True`, `False` and `None`. Keys are saved as strings. Store a `datetime` as a string or a timestamp

Stores are meant for small things: scores, quotes, last-seen times, settings changed by a command. For lots of data or lots of writes, use a proper database like `sqlite3`.

To clear a plugin's data, stop the bot and delete its file.

`msg.store` is new in 1.12.

## Settings

`msg.config` holds the plugin's settings, from [`plugin_config`](options.md#plugin_config) in the bot's config. Owners can change them without editing the plugin:

```yaml
plugin_config:
    weather:
        api_key: "${WEATHER_API_KEY}"
        units: "metric"
    shared:
        modteam: ["mal", "ana"]
```

```python
@pinhook.plugin.command('!weather')
def weather(msg):
    key = msg.config['api_key']
    units = msg.config.get('units', 'metric')
    ...
```

* Each plugin reads the section named after its file, so `weather.py` reads `weather`
* `msg.config.shared` is the `shared` section, which every plugin can read. Use it for settings several plugins need
* Settings are read only. For things the plugin changes itself, use [`msg.store`](#saving-data)
* After changing settings in the config file, an op can run `!reload` to use them without restarting. If the file has a mistake, the bot keeps the old settings and says so. Other options, like `server`, still need a restart
* A missing setting fails with a message naming it: `plugin_config has no 'api_key' setting for the weather plugin`. Use `msg.config.get('name', default)` for optional ones

`msg.config` is new in 1.12.

## Logging

Use `msg.logger` so a plugin's logs go to its bot's log file at its bot's log level:

```python
msg.logger.info('rolled {} for {}'.format(result, msg.nick))
```

If a plugin raises an exception, the bot logs it with the traceback and carries on.

## Loading and reloading

Every `.py` file in the plugin folder is loaded when the bot starts. An op can run `!reload` to pick up new, changed and deleted plugins without restarting, and `!disable` or `!enable` to switch one off and on.

Plugin files are loaded as `pinhook_plugins.<filename>`, so a plugin named after another module, like `json.py`, is fine.

## Testing plugins

`pinhook.testing` runs your plugins in a bot that never connects, so you can check what they reply with pytest. See [Testing plugins](testing.md).
