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

Return one of these to reply where the message came from, the channel or the private message:

* `pinhook.plugin.message(text)`: a normal message
* `pinhook.plugin.action(text)`: a `/me` action

Both take a string or a list of strings. Each line is sent as its own message, with a short pause between lines so the bot doesn't flood the channel.

```python
return pinhook.plugin.message(['line one', 'line two'])
```

Returning anything else, like a plain string, is logged as an error and nothing is sent.

To send somewhere else, use the functions on the message: `msg.privmsg(target, text)`, `msg.action(target, text)` and `msg.notice(target, text)`.

```python
msg.notice(msg.nick, 'psst, only you can see this')
```

## The message

| Attribute | What it is |
| --- | --- |
| `nick` | who sent it |
| `user` | the username part of their hostmask (`nick!user@host`) |
| `channel` | where it was sent. For a private message, the sender's nick |
| `cmd` | (commands) the command word that triggered it |
| `arg` | (commands) everything after the command word |
| `text` | (listeners) the whole message |
| `msg_type` | `"message"`, or `"action"` for a `/me` |
| `nick_list` | nicks in the channel. Just the sender for private messages |
| `is_op` | `True` if the sender is a bot operator. Understands accounts and hostmasks, so use it rather than `nick in msg.ops` |
| `ops` | the list of bot operators, as written in the config |
| `botnick` | the bot's current nick |
| `logger` | the bot's logger, see [Logging](#logging) |
| `datetime` | when the message arrived, a timezone-aware `datetime` |
| `timestamp` | the same as a unix timestamp |
| `bot` | the bot itself |
| `privmsg`, `action`, `notice` | functions to [send somewhere else](#replying) |

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

pinhook's own tests build a bot without connecting it and feed it fake messages. The helpers in [tests/conftest.py](https://github.com/archangelic/pinhook/blob/master/tests/conftest.py) are a good starting point for testing your own plugins the same way.
