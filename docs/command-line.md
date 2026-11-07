# Command line

`pinhook` makes bots, checks them and runs them.

| Command | What it does |
| --- | --- |
| `pinhook new bot NAME` | makes the folder `NAME/`: a config, an example plugin and its test, and `recipes/`, `data/` and `logs/` |
| `pinhook new plugin NAME` | makes `plugins/NAME.py`, a class plugin, and `tests/test_NAME.py` |
| `pinhook new recipe NAME` | makes `recipes/NAME.yaml` |
| `pinhook check [CONFIG]` | checks the config, plugins and recipes without connecting |
| `pinhook run [CONFIG]` | connects and runs the bot |
| `pinhook connect twitch [CONFIG]` | saves a Twitch token in `secrets.env` |
| `pinhook --version` | the installed version |

CONFIG is `config.yaml` in the current folder unless given.

## pinhook new

`new plugin` and `new recipe` offer to open the new file in an editor: `$VISUAL` or `$EDITOR`, or a list of the editors on the PATH. `--edit` opens it without asking, and `--no-edit` just saves it. Outside a terminal, the file is just saved.

The templates ship inside pinhook, so what `new` makes matches the installed version.

## pinhook check

```bash
pinhook check config.yaml
pinhook check --strict config.yaml
```

`check` loads the config and its plugins and recipes the way `run` does, without connecting. Plugins' `setup` runs, then their `teardown`. It lists every warning and error, and fails on errors. `--strict` fails on warnings too, for CI.

## pinhook run

```bash
pinhook run config.yaml
pinhook run --reload config.yaml
```

`run` reads `secrets.env` beside the config, then the config, then connects. It runs until `!quit` or SIGTERM, which lets running commands finish and sends what's waiting before it quits. `--reload` reloads plugins and recipes whenever their files change, for development.

`pinhook config.yaml`, with no command, still runs the bot, with a warning: the shorthand will be deprecated in a future version.

## pinhook connect

```bash
pinhook connect twitch config.yaml
```

Asks for the bot account's token without showing it, saves it as `TWITCH_TOKEN` in `secrets.env` beside the config, readable only by you, and says what the config still needs. The config is `config.yaml` in the current folder unless given. A script pipes the token in instead: `pinhook connect twitch < token.txt`.

## Config formats

The format comes from the file's extension: `.yaml`, `.yml` or `.json`. `--format yaml` or `--format json` sets it for another name.
