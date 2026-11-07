# Configuration

A bot's settings live in one YAML file, `config.yaml`. JSON works too, as `config.json`.

## Write the config

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

`nickname`, `server` and `channels` are required. [Options](options.md) lists every setting.

## Quote channel names and nicks

YAML reads `#` as the start of a comment, and reads `no`, `off`, `yes` and `on` as true and false. Quote every channel name, and any nick that's one of those words:

```yaml
nickname: 'off'
channels:
  - '#games'
```

`pinhook check` catches both mistakes and says to quote the value.

## Keep the bot in one folder

`bot_dir` puts everything the bot keeps in one folder:

```
gamebot/                <- bot_dir
├── config.yaml
├── plugins/            <- plugin_dir
├── recipes/            <- recipe_dir
├── data/               <- data_dir: plugin stores, bans, grants, !enable and !disable
└── logs/
    └── gamebot.log     <- log_file
```

Relative paths in the config, `bot_dir`'s included, start from the folder the config is in. `bot_dir: '.'` is that folder, so `pinhook run gamebot/config.yaml` works from anywhere.

## Keep secrets out of the file

Write `${NAME}` for a value from the environment, and `${file:PATH}` for a value read from a file:

```yaml
sasl_password: '${SASL_PASSWORD}'
plugin_config:
  weather:
    api_key: '${file:/run/secrets/weather_key}'
```

Put the values in `secrets.env` beside the config, readable only by you:

```bash
echo 'SASL_PASSWORD=hunter2' >> secrets.env
chmod 600 secrets.env
```

`pinhook run` reads `secrets.env` before the config. A variable already set in the environment wins, so a service manager or container supplies its own. `$${` is a literal `${`.

Values from `${...}` in `token`, `sasl_password`, `ns_pass`, `server_pass` and `plugin_config` show as `***` in the log.

## Set defaults from the environment

`PINHOOK_` variables set any single-value option the config leaves out, like `PINHOOK_LOG_FILE=-` for `log_file`. The config wins. The [image](deployment.md#the-image) sets its defaults this way. Secrets can't be set like this: they come from `${...}`, so they stay masked.

## Give plugins their settings

`plugin_config` has a section per plugin file, and a `shared` section every plugin reads:

```yaml
plugin_config:
  weather:
    units: 'metric'
  shared:
    modteam: ['mal', 'ana']
```

A plugin reads its section as `ctx.config`, and the shared one as `ctx.config.shared`. [The context](the-context.md#settings) covers it.

## Check it

```bash
pinhook check config.yaml
```

`check` validates the config, loads the plugins and recipes, and lists every warning and error. It fails on errors. `pinhook check --strict` fails on warnings too, for CI.

## Run it from Python

`load_bot` makes the bot a config describes, the same way `pinhook run` does, with `secrets.env`, `${...}` and relative paths:

```python
from pinhook.config import load_bot

bot = load_bot('gamebot/config.yaml')
bot.start()
```

A mistake in the config raises `ConfigError`, saying what's wrong.

## Pick the platform

`platform` is `irc` unless set. A Twitch bot sets `platform: twitch`. [Twitch](twitch.md) covers it.
