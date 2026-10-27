# Options

These work the same in a config file or as keyword arguments to `Bot`. `nickname`, `server` and `channels` are required, everything here is optional.

If pinhook doesn't recognise an option it logs a warning and suggests the closest match:

```
unknown option 'ssl_requred' ignored, did you mean 'ssl_required'?
```

| Option | Default | In short |
| --- | --- | --- |
| [`port`](#port) | `6667` | server port |
| [`ssl_required`](#ssl_required) | `False` | connect over ssl |
| [`ssl_verify`](#ssl_verify) | `True` | check the server's certificate |
| [`server_pass`](#server_pass) | none | server password |
| [`ns_pass`](#ns_pass) | none | nickserv password |
| [`nickserv`](#nickserv) | `"NickServ"` | nick of the nickserv service |
| [`ops`](#ops) | `[]` | bot operators |
| [`banned_users`](#banned_users) | `[]` | people the bot ignores |
| [`ban_file`](#ban_file) | `"<nickname>.bans.json"` | where `!ban` saves bans |
| [`require_account`](#require_account) | `False` | only answer logged-in users |
| [`plugin_dir`](#plugin_dir) | `"plugins"` | where plugins live |
| [`cmd_prefix`](#cmd_prefix) | `"!"` | prefix for built-in commands |
| [`use_prefix_for_plugins`](#use_prefix_for_plugins) | `False` | add the prefix to plugin commands |
| [`disable_help`](#disable_help) | `False` | turn off `!help` |
| [`bot_mode`](#bot_mode) | `True` | mark the bot as a bot |
| [`log_level`](#log_level) | `"info"` | how much to log |
| [`log_file`](#log_file) | `"<nickname>.log"` | where to log |

## Connecting

### port

The server port. Plain-text IRC is usually `6667`, ssl is usually `6697`.

### ssl_required

Connect over ssl. Set `port` to the server's ssl port too, usually `6697`.

### ssl_verify

Check the server's ssl certificate is valid and issued for that server name, so nobody in between can pretend to be the server. Leave this on.

Only turn it off for a server with a self-signed certificate. If the check fails, the log says why and whether turning it off would help, see [Troubleshooting](troubleshooting.md#connecting).

!!! tip
    On Python 3.13 and newer you can keep checking on for a self-signed server: point the `SSL_CERT_FILE` environment variable at the server's certificate.

### server_pass

Password for the server itself, if it needs one. This is not your nickserv password.

### ns_pass

Password to identify with nickserv. The bot sends it straight after connecting.

### nickserv

The nick of the nickserv service, if your network calls it something other than `NickServ`.

If the bot's nickname is taken when it connects, it tries `nickname_`, then `nickname__`, and so on.

## People

### ops

Bot operators, who can run the op-only [built-in commands](commands.md) and op-only plugin commands. Entries can be nicks, hostmasks or services accounts, see [Bans and ops](bans-and-ops.md).

```yaml
ops:
    - "$a:mal"
```

### banned_users

People the bot ignores completely. Same kinds of entries as `ops`. Bans added with `!ban` while the bot runs are saved separately, in [`ban_file`](#ban_file).

### ban_file

File where bans made with `!ban` are saved, so they last through restarts. Bans from `banned_users` stay in the config and aren't copied into it.

Set it to `""` to keep `!ban` bans in memory only. If the file can't be read the bot won't start, rather than quietly forgetting bans.

### require_account

Only answer people who are logged in to a services account. This makes bans much harder to dodge, but guests can't use the bot at all. Needs a server that supports account tags, see [Bans and ops](bans-and-ops.md#require_account).

## Plugins and commands

### plugin_dir

Folder the bot loads plugins from. Every `.py` file in it is loaded. It's created if it doesn't exist.

### cmd_prefix

Prefix for the [built-in commands](commands.md), so `"?"` makes it `?help`, `?reload` and so on.

### use_prefix_for_plugins

Add `cmd_prefix` to plugin commands too. With it on, `@command('roll')` answers to `!roll`. With it off, plugins choose their own command word, prefix and all.

### disable_help

Turn off the built-in `!help` command, for example when a plugin provides its own.

### bot_mode

Mark the bot as a bot on servers that support it, so `/whois` shows it as one. pinhook sets whichever user mode the server advertises for this ([IRCv3 bot mode](https://ircv3.net/specs/extensions/bot-mode)), and does nothing on servers that don't.

## Logging

### log_level

One of `"debug"`, `"info"`, `"warning"`, `"error"` or `"critical"`, in any case. `"off"` turns logging off completely.

### log_file

File to write logs to. Each bot has its own log file and log level, even several bots in one python process. Log lines name the bot they came from:

```
2026-10-27 22:33:18,491 - INFO - bot.ph-bot - bot - setting bot mode +B
```
