# Migrating from 1.x

1.x plugins run on 2.0 through a compatibility layer, and log a deprecation warning saying what to use instead. This page lists what changed, then shows a plugin and a config moved to 2.0.

## Upgrade

```bash
pip install --upgrade pinhook
pinhook check config.yaml
```

`check` loads the config and every plugin without connecting, and lists what needs changing.

## What breaks

| Change | What to do |
| --- | --- |
| Python 3.11 or newer | upgrade Python |
| TOML configs aren't read | move the settings to YAML, [below](#move-a-toml-config-to-yaml) |
| `pinhook config.yaml` is now `pinhook run config.yaml` | the old form still works, with a warning |
| relative paths start from the config file's folder | a bot run from a different folder than its config moves its paths, or uses absolute ones |
| `msg.bot` has only the bot's nick and channels, read only | use `msg.reply()`, `msg.send()` and `msg.botnick`, and [`plugin_config`](configuration.md#give-plugins-their-settings) for settings |
| `bot.connection` and `bot.channels` are gone, and `Bot` no longer subclasses the `irc` library's bot | send through plugins. A `Bot` subclass's `on_join` and other irc library events don't run |
| `@register` and `@ops` are removed | `@command('!x')`, and `@command('!x', ops=True)` |
| `use_prefix_for_plugins` is retired | commands answer to `cmd_prefix`. A 1.x command written without a prefix, like `@command('roll')`, needs it now: `!roll` |
| two plugins with the same command is a load error naming both | rename one |
| built-in command names are reserved | a plugin command called `help`, `ban` or another built-in's name doesn't load |
| plugins import as `pinhook_plugins.<bot>.<name>` | a plugin that imports another by `pinhook_plugins.<name>` uses the new name |
| `hide=True` hides a command from ops too | take `hide=True` off commands ops look for in `!help` |
| each 1.x plugin runs on a thread of its own, one call at a time | a plugin that blocks holds up only its own calls, not the bot. State shared between plugins needs a lock |

`pytest -W error::DeprecationWarning` turns each warning into a failing test that points at the line to change.

## Move a plugin to 2.0

A 1.x plugin:

```python
import random

import pinhook.plugin


@pinhook.plugin.command('!roll', help_text='roll a die')
def roll(msg):
    sides = int(msg.arg or 6)
    return pinhook.plugin.message('{} rolled {}'.format(msg.nick, random.randint(1, sides)))
```

The same plugin on 2.0:

```python
import random

from pinhook import command


@command('roll', help='roll a die')
async def roll(ctx, sides: int = 6):
    await ctx.reply(f'{ctx.nick} rolled {random.randint(1, sides)}')
```

| 1.x | 2.0 |
| --- | --- |
| `@pinhook.plugin.command('!roll')` | `@command('roll')`, without the prefix |
| `def roll(msg)` | `async def roll(ctx, ...)`, with [typed arguments](typed-commands.md) |
| `msg.arg`, parsed by hand | arguments in the signature |
| `return message(text)` | `await ctx.reply(text)` |
| `return action(text)` | `await ctx.action(text)` |
| `@listener('name')` | `@on('message')` |
| `msg.store`, `msg.config` | `ctx.store`, `ctx.config` |
| `msg.is_op` | `ctx.is_op`, or `ops=True` on the command |
| `ops_msg='...'` | `denied_msg='...'` |

[The context](the-context.md) lists everything `ctx` has.

## Move a TOML config to YAML

`config.toml`:

```toml
nickname = "gamebot"
server = "irc.libera.chat"
port = 6697
ssl_required = true
channels = ["#games"]
ops = ["$a:mal"]
```

The same settings as `config.yaml`, with every channel name quoted:

```yaml
nickname: 'gamebot'
server: 'irc.libera.chat'
port: 6697
ssl_required: true
channels:
  - '#games'
ops:
  - '$a:mal'
```

## Keep running 1.x

1.x gets security fixes as 1.12.x releases, from the `1.x` branch. Pin it with `pip install 'pinhook<2'`.
