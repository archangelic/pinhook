# Options

These work the same in a config file or as keyword arguments to `Bot`. `nickname`, `server` and `channels` are required, and everything else has a default. An option pinhook doesn't know is logged as a warning, with the closest match:

```
unknown option 'ssl_requred' ignored, did you mean 'ssl_required'?
```

## Connecting

| Option | Default | What it does |
| --- | --- | --- |
| `platform` | `irc` | `irc`, or `twitch` for a [Twitch](twitch.md) bot |
| `nickname` | required | the bot's nick |
| `server` | required on IRC | the server's name |
| `channels` | required | the channels to join, quoted: `['#games']` |
| `port` | `6667`, Twitch `6697` | the server's port. TLS is usually `6697` |
| `ssl_required` | `false` | connect over TLS |
| `ssl_verify` | `true` | check the server's certificate |
| `ssl_certfile`, `ssl_keyfile` | none | a client certificate, for [SASL EXTERNAL](ircv3-support.md#log-in-with-a-certificate) |
| `server_pass` | none | the server's password, not the bot's account password |
| `token` | none | a Twitch bot's OAuth token |
| `rate_limit` | `{burst: 4, interval: 2}`, Twitch `{burst: 20, interval: 1.5}` | how fast the bot sends: `burst` lines at once, then one every `interval` seconds |

### ssl_verify

Leave it on. Turn it off only for a server with a self-signed certificate. Pointing the `SSL_CERT_FILE` environment variable at the server's certificate keeps the check on.

## Logging in

| Option | Default | What it does |
| --- | --- | --- |
| `sasl_password` | none | log in with [SASL](ircv3-support.md#log-in-with-sasl) while connecting |
| `sasl_account` | the nickname | the account to log in to |
| `sasl_mechanism` | `auto` | `PLAIN`, `SCRAM-SHA-256` or `EXTERNAL`, or the strongest the server offers |
| `ns_pass` | none | identify to NickServ after connecting, where SASL isn't offered or fails |
| `nickserv` | `NickServ` | NickServ's nick on this network |

A nick that's taken gets `_` added, and the bot takes its own nick back when it frees up.

## People

| Option | Default | What it does |
| --- | --- | --- |
| `ops` | `[]` | the bot's [ops](bans-and-ops.md), as entries like `'$a:mal'` |
| `banned_users` | `[]` | people the bot ignores |
| `ban_file` | `data/<nickname>.bans.json` with `bot_dir`, `<nickname>.bans.json` without | where `!ban` saves bans. `''` keeps them in memory |
| `require_account` | `false` | ignore anyone not logged in to a services account |
| `access` | open | [access levels](access-levels.md), groups, grants and denies |

## Commands and plugins

| Option | Default | What it does |
| --- | --- | --- |
| `cmd_prefix` | `!` | the prefix for every command, or a list of them: `['!', '.']` |
| `address_by_nick` | `true` | commands also work after the bot's nick: `gamebot: roll`, `gamebot, roll` or `@gamebot roll` |
| `disable_help` | `false` | turn off `!help` |
| `plugin_config` | none | settings for plugins: a section per plugin file, and `shared` |
| `plugin_channels` | none | keep a plugin, command or listener to some channels: `{weather: ['#outside']}` |
| `history` | off | keep recent messages for `ctx.history()`: `{channels: ['#games'], size: 20, minutes: 10}` |
| `bot_mode` | `true` | mark the bot as a bot, where the server supports it |

`!enable` and `!disable` override `plugin_channels` per channel, and are saved.

### history

`channels` lists the channels to record. `size` is how many messages are kept per channel, and `minutes` how long. History is kept in memory only, and includes the bot's own lines.

## Files and folders

| Option | Default | What it does |
| --- | --- | --- |
| `bot_dir` | none | one folder for plugins, recipes, data and logs |
| `plugin_dir` | `plugins` | where plugins are loaded from |
| `recipe_dir` | `recipes` | where [recipes](writing-recipes.md) are loaded from |
| `data_dir` | `data` | plugin stores, grants and denies, `!enable` and `!disable`, STS policies |

Relative paths start from `bot_dir` when it's set, and `bot_dir` itself, like every relative path, starts from the config file's folder. `~` is the home folder.

## Logs and health

| Option | Default | What it does |
| --- | --- | --- |
| `log_level` | `info` | `debug`, `info`, `warning`, `error`, `critical` or `off` |
| `log_file` | `logs/<nickname>.log` with `bot_dir`, `<nickname>.log` without | where to log. `'-'` is stdout |
| `log_format` | `text` | `text`, or `json` for one JSON object per line |
| `health_port` | off | serve [`/healthz` and `/readyz`](deployment.md#health-checks) on this port |
| `health_host` | `127.0.0.1` | the address the health endpoint listens on |

## From the environment

`${NAME}` in any value reads an environment variable, and `${file:PATH}` reads a file. `PINHOOK_<OPTION>` sets a single-value option the config leaves out, like `PINHOOK_HEALTH_PORT=8080`. [Configuration](configuration.md#keep-secrets-out-of-the-file) covers both.

## Retired

`use_prefix_for_plugins` does nothing in 2.0, and logs a warning: plugin commands always use `cmd_prefix`.
