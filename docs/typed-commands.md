# Typed commands

A command's arguments come from its handler's signature. pinhook splits the message, converts each word to the annotated type, and answers bad input with a usage line built from the same signature.

```python
from pinhook import command


@command('roll', help='roll dice, like roll 2 20')
async def roll(ctx, count: int = 1, sides: int = 6):
    ...
```

| Message | Runs |
| --- | --- |
| `!roll` | `roll(ctx)`, so `count=1, sides=6` |
| `!roll 2 20` | `roll(ctx, count=2, sides=20)` |
| `!roll two` | nothing. The bot answers `usage: roll [count=1] [sides=6] (count must be a whole number)` |

## Name the command

`@command('roll')` answers to `!roll`. Names are letters, digits, `-` and `_`, written without a prefix. The bot's [`cmd_prefix`](options.md#commands-and-plugins) is the prefix, `!` by default. A message that starts with the bot's nick works too: `gamebot: roll 2 20`.

## Give it other names

```python
@command('roll', aliases=['r', 'dice'])
```

`!r` and `!dice` run `roll`. `!help` lists it once, as `!roll`, and `!help r` shows its other names. Access, `!enable` and `!disable` go by the command, whichever name is used. An alias another command already has stops the plugin loading, the same as a name.

## Use the types

| Annotation | Takes |
| --- | --- |
| `str` | a word. The last `str` argument takes the rest of the line as written |
| `int`, `float` | a number |
| `bool` | `true`, `yes`, `on` or `1`, and `false`, `no`, `off` or `0` |
| `Literal['add', 'list']` | one of the listed values |
| `Optional[int]`, `int \| None` | the type, or `None` when it's left out |

An argument with no annotation is a `str`. Quotes group words, so with `remind(ctx, when: str, what: str)`, `!remind "next friday" play games` gives `when='next friday'` and `what='play games'`.

## Describe the arguments

`Annotated` adds a description, which `!help` shows:

```python
from typing import Annotated, Literal

from pinhook import command


@command('games', help='keep a list of games')
async def games(ctx, action: Literal['add', 'list'] = 'list',
                name: Annotated[str, 'the game, like azul'] = ''):
    ...
```

`!help games` answers in a private message:

```
<ana> !help games
<gamebot> !games -- keep a list of games
<gamebot> usage: games [action=list] [name=]
<gamebot> action: one of add, list | name: the game, like azul
```

A wrong choice gets the usage line and what's allowed: `usage: games [action=list] [name=] (action must be one of add, list)`.

## Give it help

`help='...'` is the line `!help roll` shows. Without it, the first line of the docstring is used.

## Set who runs it

```python
@command('shutdown', ops=True)          # the bot's ops only
@command('weather', restricted=True)    # ops, and people given access
```

`denied_msg='...'` is what the bot says to someone who can't run it. [Access levels](access-levels.md) covers the rest.

## Handle failures

A command that raises is logged with its traceback, and says nothing in chat. `error_msg='...'` says something instead. A command that runs longer than 30 seconds is given up on and logged. `timeout=` changes that for one command.

Each person runs one copy of a command at a time. A second `!roll` from them while the first is still running is ignored.

## Hide it

`hide=True` leaves the command out of `!help` and the command listing.
