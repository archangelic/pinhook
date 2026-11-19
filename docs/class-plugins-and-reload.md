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

## Use the bot from a plugin

`self.config` is the plugin's [`plugin_config`](options.md#commands-and-plugins) section, as `ctx.config` is, from `setup` on, so a plugin can check its settings as it loads. `!reload` reads `plugin_config` again, and the new instance gets the new settings.

`self.bot` is the bot, from `setup` on, and handlers get the same as `ctx.bot`. It's read only:

| Member | What it is |
| --- | --- |
| `nick`, `channels` | the bot's nick and channels |
| `prefix` | the command prefix, like `!` |
| `logger` | the bot's logger, as `ctx.logger` |
| `data_dir` | the bot's data folder, for files a plugin keeps |
| `is_op(who)` | `True` if `who`, a `Source` or a `Member`, is one of the bot's ops |
| `matches(entry, who)` | `True` if an entry like `'$a:mal'` names `who`, as ops and bans match |
| `keeps_history(channel)` | `True` if the [`history`](options.md#history) option lists the channel |
| `split(target, text, prefix)` | the lines `text` would go to `target` as, split to fit the network |

## Add recipes and grant access from a plugin

A class plugin can change its own commands, and nothing else of the bot's, from `setup` on:

| Method | What it does |
| --- | --- |
| `self.set_recipes(recipes)` | adds [recipes](writing-recipes.md) as commands of the plugin, in place of the ones it added before |
| `self.allow(command, who)` | gives `who` access to one of the plugin's restricted commands, as `!allow` does |

A plugin that keeps recipes somewhere other than `recipe_dir` adds them in `setup`:

```python
from pinhook import Plugin, recipes


class Moves(Plugin):
    def setup(self, previous):
        found = [recipes.load_recipe(path) for path in self.saved_paths()]
        self.set_recipes(found)
```

They load after the recipe folder's, so a name a recipe file has is left out, and `set_recipes` returns the problems. Setting them again replaces them at once. Access and `!disable` treat them as the plugin's commands, so `!disable moves` turns them off too.

`allow` takes only the plugin's own commands, and refuses one that's ops only, as `!allow` does. It returns `False` when they had access already, or the command is open to everyone. Each grant is logged as an audit line.

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

## Load a plugin from a package

Install the package, then name its plugin in `plugins`:

```bash
pip install pinhook-dice
```

```yaml
plugins:
  - dice
```

The name is the plugin's own: it names its store, its `plugin_config` section, and what `!enable` and `!disable` take. `!reload` makes new instances of its classes, and calls `setup(previous)` as it does for files. Code from an upgraded package loads when the bot restarts.

## Publish a plugin as a package

Point a `pinhook.plugins` entry point at the module holding the plugin's handlers and classes, in `pyproject.toml`:

```toml
[project.entry-points."pinhook.plugins"]
dice = "pinhook_dice.plugin"
```

`dice` is the name bots list in `plugins`. The module uses the 2.0 API: `@command`, `@on`, `@every` and `Plugin` classes, defined in that module.

## Reload on every save

```bash
pinhook run --reload config.yaml
```

The bot reloads whenever a plugin or recipe file is added, changed or removed, for development.
