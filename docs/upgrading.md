# Upgrading to 1.11

Most bots upgrade with no changes. Check this list for the ones that might affect yours. The [changelog](changelog.md) has everything that changed.

## Might need a change

**Your server uses a self-signed ssl certificate.** pinhook now checks certificates, so the bot stops connecting until you set [`ssl_verify`](options.md#ssl_verify) to `false`. The log says exactly this when it happens.

**You're on Python 3.7 or older.** pinhook now needs 3.8 or newer.

**A plugin imports another plugin by its filename.** Plugins are now loaded as `pinhook_plugins.<filename>`, so `import dice` from another plugin no longer works.

**Your Bot subclass overrides `call_plugins` or `call_internal_commands`.** Both take new arguments: `botnick` and `op`.

**Something parses the bot's log lines.** Lines now include the bot's logger name, like `bot.ph-bot`, before the module name.

## Works differently, nothing to change

* **TwitchBot connects over ssl** to `irc.chat.twitch.tv` on port 6697.
* **Bots mark themselves as bots** on servers that support it. Set [`bot_mode`](options.md#bot_mode) to `false` to stop that.
* **`!ban` bans accounts and hosts**, not just nicks, and saves bans to `<nickname>.bans.json` in the folder the bot runs from. See [Bans and ops](bans-and-ops.md).
* **`!banlist` is ops only**, since bans can now include hostmasks.
* **`log_level: off` turns logging off completely.** It used to still log warnings and errors.
* **Each bot has its own logger**, log level and log file, so several bots in one process no longer share them.

## Worth doing

* **Use accounts for ops**: `$a:yourname` instead of a nick, so nobody can borrow an op's nick. See [Bans and ops](bans-and-ops.md).
* **Use `msg.is_op` in plugins** instead of `msg.nick in msg.ops`.
* **Swap `@register` and `@ops` for `@command`.** They'll be removed in 2.0.
