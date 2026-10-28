# pinhook

The pluggable python framework for IRC bots and Twitch bots.

You write small plugins, each one a python function, and pinhook handles connecting, joining channels, ops, bans and getting your replies back to the right place.

```python
import pinhook.plugin

@pinhook.plugin.command('!hello')
def hello(msg):
    return pinhook.plugin.message('hi {}!'.format(msg.nick))
```

## Quick start

```bash
pip install pinhook
```

Make a `plugins` folder, save the plugin above in it as `hello.py`, then start a bot:

```python
from pinhook.bot import Bot

bot = Bot(
    channels=['#foo'],
    nickname='ph-bot',
    server='irc.libera.chat',
    port=6697,
    ssl_required=True,
)
bot.start()
```

Say `!hello` in `#foo` and the bot answers.

## Where to next

* [Getting started](getting-started.md): config files, the command line tool and your first plugin
* [Options](options.md): everything you can set on a bot
* [Writing plugins](plugins.md): commands, listeners and what a plugin gets to work with
* [Testing plugins](testing.md): check your plugins with pytest, no server needed
* [Bans and ops](bans-and-ops.md): who can run what, and bans that are hard to dodge
* [Troubleshooting](troubleshooting.md): what the log messages mean
* Coming from an older version? See [Upgrading to 1.11](upgrading.md)

pinhook is made with love on [tilde.town](https://tilde.town). Live bots using it include [pinhook-tilde](https://github.com/archangelic/pinhook-tilde) and [adminbot](https://github.com/tildetown/adminbot).
