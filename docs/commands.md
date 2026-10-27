# Built-in commands

Every bot has these commands. They're shown with the default `!` prefix, change it with [`cmd_prefix`](options.md#cmd_prefix).

## For everyone

| Command | What it does |
| --- | --- |
| `!help` | Private messages the list of commands and listeners. Ops also see the op-only commands. Turn it off with [`disable_help`](options.md#disable_help) |

## For ops

Who counts as an op is set by [`ops`](options.md#ops).

| Command | What it does |
| --- | --- |
| `!join #channel [key]` | Join a channel, with its key if it has one |
| `!quit [message]` | Disconnect and stop the bot. The quit message defaults to "See y'all later!" |
| `!reload` | Reload every plugin from the plugin folder. Picks up new, changed and deleted plugins. Disabled plugins stay disabled |
| `!enable <plugin>` | Turn a plugin back on |
| `!disable <plugin>` | Turn a plugin off without removing it |
| `!op <nick>` | Add a bot operator, until the bot restarts |
| `!deop <nick>` | Remove a bot operator, until the bot restarts |
| `!ops` | List bot operators |
| `!ban <nick>` | Make the bot ignore someone. See below |
| `!unban <nick>` | Remove a ban. See below |
| `!banlist` | List current bans |

`!enable` and `!disable` take a command's name (like `!roll`) or a listener's name.

## !ban and !unban

`!ban` picks the hardest ban to dodge that it can:

1. If they're logged in to a services account, it bans the account: `$a:troll`
2. If not, it bans their username and host: `*!*troll@203.0.113.7`
3. If they haven't spoken since the bot started, it can only ban the nick: `troll`

The reply says which one it used:

```
<mal> !ban troll
<ph-bot> mal: banned troll (account trollacct)
```

You can also give a hostmask or account yourself: `!ban *!*@203.0.113.*` or `!ban $a:troll`.

`!unban` with the nick they're using now removes whatever bans them, account and host bans included. Bans made with `!ban` are saved to [`ban_file`](options.md#ban_file). A ban from the config file can be lifted with `!unban`, but it comes back after a restart until you remove it from the config.

[Bans and ops](bans-and-ops.md) explains the kinds of entries in more detail.
