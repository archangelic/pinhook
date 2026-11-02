# Your first bot

This page makes a bot, gives it a dice command, tests the command and runs the bot on IRC.

## Create the bot

```bash
pinhook new bot gamebot
```

This makes the folder `gamebot/`:

```
gamebot/
├── config.yaml         the bot's settings
├── plugins/
│   └── hello.py        an example plugin
├── tests/
│   └── test_hello.py   its test
├── recipes/            commands written as YAML
├── data/               what plugins save
└── logs/
```

## Configure it

Edit `gamebot/config.yaml`:

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

`$a:youraccount` makes your services account an op, so nobody gets op powers by taking your nick. Quote channel names: YAML reads an unquoted `#` as the start of a comment. [Configuration](configuration.md) covers the file.

## Write a plugin

Save this as `gamebot/plugins/dice.py`:

```python
import random

from pinhook import command


@command('roll', help='roll dice, like roll 2 20')
async def roll(ctx, count: int = 1, sides: int = 6):
    rolls = [random.randint(1, sides) for _ in range(count)]
    await ctx.reply(f'{ctx.nick} rolled {sum(rolls)} {rolls}')
```

Arguments come from the message, converted to their annotated types. `!roll 2 20` runs `roll` with `count=2` and `sides=20`. `!roll two` gets the usage line back:

```
usage: roll [count=1] [sides=6] (count must be a whole number)
```

## Test it

Save this as `gamebot/tests/test_dice.py`:

```python
from pinhook.testing import TestBot


def test_roll():
    bot = TestBot(plugin_dir='plugins')
    assert bot.say('!roll 3 1', nick='ana') == ['ana rolled 3 [1, 1, 1]']
```

Run the tests from the bot folder:

```bash
cd gamebot
pytest
```

`TestBot` runs the real bot on a fake network, with no server. [TestBot](testbot.md) covers it.

## Run it

```bash
pinhook check config.yaml
pinhook run config.yaml
```

`check` loads the config, plugins and recipes without connecting, and lists anything wrong. `run` connects and joins `#gamebot-test`. Say `!roll 2 20` there.

## Change it while it runs

Edit `plugins/dice.py`, then say `!reload` as an op. The bot loads the new code without disconnecting. [Class plugins & reload](class-plugins-and-reload.md) covers keeping state across a reload.

Next: [The context](the-context.md), which is everything `ctx` gives a plugin.
