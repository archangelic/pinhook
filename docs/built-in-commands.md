# Built-in commands

Every bot has these. They use the bot's [`cmd_prefix`](options.md), `!` by default, and their names are reserved: no plugin or recipe can take them.

## For everyone

| Command | What it does |
| --- | --- |
| `!help` | lists the commands this person can run. On IRC it answers in a private message, packed into as few lines as fit |
| `!help <command>` | the command's help, its usage line and its arguments |

[`disable_help`](options.md#commands-and-plugins) turns the built-in `!help` off, and frees its name for a plugin's own `!help` command. The other names stay reserved.

## For ops

| Command | What it does |
| --- | --- |
| `!join #channel [key]` | joins a channel |
| `!quit [message]` | quits, after sending what's waiting |
| `!reload` | loads plugins and recipes again, with `plugin_config` and `access` from the config file. [Class plugins & reload](class-plugins-and-reload.md) |
| `!enable <name> [where]` | turns a plugin, command or listener on: here, `all`, or a `#channel` |
| `!disable <name> [where]` | turns one off |
| `!op <who>`, `!deop <who>` | adds or removes an op until the bot restarts |
| `!ops` | lists the ops |
| `!ban <who>`, `!unban <who>` | [bans](bans-and-ops.md) someone, or lifts it |
| `!banlist` | lists the bans |
| `!allow <name> <who>...` | gives access to a restricted plugin or command. [Grants & denies](grants-and-denies.md) |
| `!deny <name> <who>...` | keeps someone off a plugin or command |
| `!revoke <name> <who>...` | takes back a grant or deny |
| `!access <name>` | shows who can use a plugin or command |
| `!recipe add <name> <reply>` | adds a one-line reply [recipe](writing-recipes.md) |
| `!recipe del <name>` | removes a recipe |

`!enable` and `!disable`, from a private message, apply everywhere. Both are saved, and last through restarts.

A [timer](timers.md) runs in no channel, so only `all` switches it. `!disable notes` in a channel turns off the notes plugin's commands and handlers there and leaves its timers running; `!disable notes all` stops them too.

Every command that changes who can do what is logged as an [audit line](deployment.md#logs).
