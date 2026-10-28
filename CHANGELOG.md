# Changelog

## 1.12.0 (not released yet)

### New

* `pinhook.testing`: a `TestBot` that runs your plugins without a server, so you can test them with pytest
* `msg.reply(text)` and `msg.send(target, text)` send straight away, so a plugin can reply more than once or to several places
* Given just the text, `msg.action(text)` replies where the message came from and `msg.notice(text)` sends the sender a notice
* `msg.account` (the sender's services account) and `msg.is_private`
* `bot_dir` keeps everything a bot uses in one folder, with `plugins/`, `data/` and `logs/` inside it. Without it, files go where they did in 1.11
* `msg.store`, a dictionary each plugin can keep data in. It lasts through `!reload` and restarts, and is saved to `data_dir` automatically
* `data_dir`, where plugins keep their saved data
* `plugin_config` gives each plugin its own settings, as `msg.config`, plus a `shared` section every plugin can read
* `!reload` also reads `plugin_config` from the config file again, so settings can change without a restart
* `${NAME}` in a config file is filled in from the environment, so passwords don't have to be in the file
* A [Preparing for 2.0](https://archangelic.github.io/pinhook/latest/preparing-for-2/) guide to getting plugins ready for 2.0

### Deprecated

* `msg.bot`, which will be read only in 2.0. Use `msg.reply()`, `msg.send()` and `msg.botnick` instead. It still works, and logs a warning once
* `@register` and `@ops` now raise a `DeprecationWarning` too, saying what to use instead. They'll be removed in 2.0

### Fixed

* The example dice plugins used an invalid escape in their regex, which newer Pythons warn about

## 1.11.0

### Before you upgrade

* **SSL now checks the server's certificate.** If your bot connects to a server with a self-signed certificate, it will stop connecting until you set `ssl_verify: false`. The log says exactly this when it happens.
* **TwitchBot connects over SSL** to `irc.chat.twitch.tv` on port 6697, so your oauth token isn't sent in plain text anymore.
* **Bots mark themselves as bots** on servers that support it. Set `bot_mode: false` to turn this off.
* **`!ban` bans accounts and hosts, not just nicks.** If the person has spoken since the bot started, `!ban troll` bans their account if they're logged in, or their user and host if not. Bans are now saved to `<nickname>.bans.json` in the bot's working directory, set `ban_file: ""` to keep them in memory only.
* **`!banlist` is ops only**, since bans can now include hostmasks.
* **Log lines show which bot they came from** (e.g. `bot.pinbot`), which adds a field to the log format. Each bot now has its own logger, log level and log file.
* **`log_level: off` turns logging off completely.** It used to still log warnings and errors.
* **Plugins are loaded as `pinhook_plugins.<filename>`.** This only matters if one plugin imported another by its filename.
* **If you subclass Bot:** `call_plugins` and `call_internal_commands` take new arguments (`botnick` and `op`).
* **Python 3.8 or newer is required.**

### New

* `ssl_verify` option for servers with self-signed certificates
* `bot_mode` option, sets the bot user mode the server advertises
* `ops` and `banned_users` can use hostmasks (`*!*@203.0.113.7`) and services accounts (`$a:troll`) as well as nicks
* `ban_file` option, bans made with `!ban` last through restarts
* `require_account` option, only answers people logged in to a services account
* `msg.is_op` for plugins, which understands accounts and hostmasks
* If the bot's nick is taken when it connects, it tries `nick_`, `nick__` and so on, instead of hanging
* When connecting fails the log says why (bad certificate, wrong port, server name typo, connection refused) instead of retrying silently
* Unknown options are logged with a suggestion, e.g. `unknown option 'ssl_requred' ignored, did you mean 'ssl_required'?`
* TOML config files work without extra packages on Python 3.11+
* Mistakes in a config file are listed plainly, instead of as a python traceback
* A documentation site, at https://archangelic.github.io/pinhook/
* Tests, and a workflow running them on Python 3.8 to 3.14 (closes #10)
* Publishing to PyPI uses trusted publishing

### Fixed

* SSL crashed on Python 3.12+
* `hide=True` on commands did nothing
* `!ban` didn't actually stop banned users, and bans and ops were case sensitive
* The bot didn't ignore messages from its own nick (#75)
* Private messages crashed the bot after its nick changed
* A plugin returning something other than `message()` or `action()` crashed the bot
* Newlines inside a list of output lines crashed the bot
* A plugin named like another module (e.g. `json.py`) replaced that module
* `log_level` crashed on capital letters or `warn`
* `!reload` left deleted plugins behind
* Log lines were written more than once when more than one Bot was created
* `!disable` said nothing for plugins that don't exist
* `!op` and `!ban` with no nick added an empty name
* `!quit` crashed when Python's `site` module isn't loaded
* The toml install hint crashed instead of showing
* Removed the `enum34` dependency, which could break Python's own `enum`
