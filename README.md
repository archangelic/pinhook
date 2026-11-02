<p align="center"><img src="https://raw.githubusercontent.com/archangelic/pinhook/master/docs/assets/brand/pinhook-readme-header@2x.png" alt="pinhook: python irc bot framework" width="640"></p>

# pinhook

Python IRC bot framework. Write plugins as typed async functions. pinhook handles the connection, IRCv3, rate limits, access control and reloading.

[![Python versions](https://img.shields.io/pypi/pyversions/pinhook.svg)](https://pypi.org/project/pinhook) [![PyPI](https://img.shields.io/pypi/v/pinhook.svg)](https://pypi.org/project/pinhook) [![License](https://img.shields.io/pypi/l/pinhook.svg)](https://github.com/archangelic/pinhook/blob/master/LICENSE) [![With love from tilde.town](https://img.shields.io/badge/with%20love%20from-tilde%20town-e0b0ff.svg)](https://tilde.town)

## Install

pinhook needs Python 3.11 or newer.

```bash
pip install pinhook
```

## Create a bot

```bash
pinhook new bot gamebot
cd gamebot
```

This makes `config.yaml`, `plugins/` with an example plugin, `tests/` with its test, and the `recipes/`, `data/` and `logs/` folders.

## Configure it

Edit `config.yaml`:

```yaml
nickname: 'gamebot'
server: 'irc.libera.chat'
port: 6697
ssl_required: true
channels:
  - '#gamebot-test'
ops:
  - '$a:youraccount'
bot_dir: '.'
```

`$a:youraccount` makes your services account an op, so nobody else gets op powers by taking your nick. Quote channel names: YAML reads an unquoted `#` as the start of a comment.

## Write a plugin

Save this as `plugins/dice.py`:

```python
import random

from pinhook import command


@command('roll', help='roll dice, like roll 2 20')
async def roll(ctx, count: int = 1, sides: int = 6):
    rolls = [random.randint(1, sides) for _ in range(count)]
    await ctx.reply(f'{ctx.nick} rolled {sum(rolls)} {rolls}')
```

Arguments come from the message, converted to their annotated types. `!roll 2 20` runs `roll` with `count=2` and `sides=20`. `!roll two` gets the usage line back: `usage: roll [count=1] [sides=6] (count must be a whole number)`.

## Run it

```bash
pinhook check config.yaml
pinhook run config.yaml
```

`check` validates the config, plugins and recipes without connecting. `run` connects and joins `#gamebot-test`. Say `!roll 2 20` there. Say `!reload` to load plugin changes without restarting.

## Test it

Save this as `tests/test_dice.py`, then run `pytest`:

```python
from pinhook.testing import TestBot


def test_roll():
    bot = TestBot(plugin_dir='plugins')
    assert bot.say('!roll 3 1', nick='ana') == ['ana rolled 3 [1, 1, 1]']
```

`TestBot` runs the real bot on a fake network, with no server and no waiting on rate limits.

## Restrict a command

Mark the command restricted:

```python
@command('weather', restricted=True)
```

Give someone access from chat, as an op:

```
!allow !weather carol
!access !weather
```

pinhook saves carol's services account, or her user and host, not her nick. [Access levels](https://archangelic.github.io/pinhook/latest/access-levels/) covers groups, denies and setting levels in the config.

## Add a command without code

Save this as `recipes/gamenight.yaml`:

```yaml
version: 1
name: gamenight
help: pick tonight's game and who goes first
steps:
  - command: 'quote random games'
    save: game
  - reply: 'Tonight: {game}. {members|random} goes first'
```

`!gamenight` runs the steps in order, as the person who asked. Ops add one-line reply recipes from chat: `!recipe add hug {nick} hugs {arg|default:everyone}`.

## Run on Twitch

Save this as `twitch.yaml`:

```yaml
platform: twitch
nickname: 'gamebot'
channels:
  - '#yourchannel'
token: '${TWITCH_TOKEN}'
bot_dir: '.'
```

Save the bot account's OAuth token, then run the bot:

```bash
pinhook connect twitch twitch.yaml
pinhook run twitch.yaml
```

`connect` keeps the token in `secrets.env`, readable only by you. [Twitch](https://archangelic.github.io/pinhook/latest/twitch/) covers Twitch's rate limits, badges as access groups, and the private messages and notices Twitch doesn't deliver.

## Deploy it

```bash
docker run -d -v ./config.yaml:/bot/config.yaml:ro -v ./plugins:/bot/plugins:ro \
  -v gamebot-data:/bot/data ghcr.io/archangelic/pinhook:2
```

The image logs to stdout and serves a health endpoint on port 8080. [Deployment](https://archangelic.github.io/pinhook/latest/deployment/) has compose, systemd and Kubernetes examples.

## Upgrade from 1.x

Plugins written with `pinhook.plugin` run on 2.0 through a compatibility layer. [Migrating from 1.x](https://archangelic.github.io/pinhook/latest/migrating-from-1x/) lists what changed for plugins, `Bot` subclasses and config files.

## Docs

- [Your first bot](https://archangelic.github.io/pinhook/latest/your-first-bot/)
- [Typed commands](https://archangelic.github.io/pinhook/latest/typed-commands/)
- [Events](https://archangelic.github.io/pinhook/latest/events/) and [Timers](https://archangelic.github.io/pinhook/latest/timers/)
- [Writing recipes](https://archangelic.github.io/pinhook/latest/writing-recipes/)
- [Options](https://archangelic.github.io/pinhook/latest/options/) and [Built-in commands](https://archangelic.github.io/pinhook/latest/built-in-commands/)
- [Troubleshooting](https://archangelic.github.io/pinhook/latest/troubleshooting/)

## Bots using pinhook

- [pinhook-tilde](https://github.com/archangelic/pinhook-tilde): a fun bot for tilde.town
- [adminbot](https://github.com/tildetown/adminbot): an admin helper for tilde.town

## License

MIT
