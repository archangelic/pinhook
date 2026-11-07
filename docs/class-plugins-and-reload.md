# Class plugins & reload

A plugin written as a class keeps state in its instance: a connection, a cache, a counter. Its methods are its commands and handlers.

```python
from pinhook import Plugin, command


class Counter(Plugin):
    def setup(self, previous):
        # on !reload, previous is the plugin as it was, so the count carries over
        self.count = previous.count if previous else 0

    @command('count')
    async def count_up(self, ctx):
        self.count += 1
        await ctx.reply(f'counted {self.count} times')
```

The bot makes one instance of each `Plugin` class in a plugin file. Methods take `self`, then `ctx`, then the command's [typed arguments](typed-commands.md).

## Make one with pinhook new

```bash
pinhook new plugin counter
```

This makes `plugins/counter.py`, a class plugin, and `tests/test_counter.py`, a passing test for it.

## Reload without restarting

`!reload`, from an op, loads every plugin and recipe again:

1. The bot makes a new instance of each class and calls its `setup(previous)` with the old instance, so it copies across what it wants to keep
2. It calls the old instance's `teardown()`
3. Commands, handlers and timers switch to the new code

`setup` gets `None` as `previous` the first time a plugin loads. `teardown` also runs when a plugin is removed and when the bot quits. Take anything that has to stay open away from the old instance, so its `teardown` doesn't close it:

```python
def setup(self, previous):
    if previous:
        self.conn, previous.conn = previous.conn, None
    else:
        self.conn = open_connection()

def teardown(self):
    if self.conn:
        self.conn.close()
```

`ctx.store` lives through a reload without any of this, since it's saved to disk.

## Reload on every save

```bash
pinhook run --reload config.yaml
```

The bot reloads whenever a plugin or recipe file is added, changed or removed, for development.
