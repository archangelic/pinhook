# Access levels

Every plugin and command has one of three levels:

| Level | Who runs it |
| --- | --- |
| `open` | everyone who isn't banned |
| `restricted` | the bot's ops, and the people given access |
| `ops` | the bot's ops |

Ops run everything. Bans beat everything.

## Set a level in the plugin

```python
from pinhook import command


@command('weather', restricted=True)
async def weather(ctx, city: str):
    ...


@command('shutdown', ops=True)
async def shutdown(ctx):
    ...
```

## Set levels in the config

The `access` section sets levels for a whole plugin, or for single commands, and the default for everything else:

```yaml
access:
  default: open
  groups:
    regulars: ['$a:ana', '$a:bob']
  plugins:
    weather: restricted
    games:
      allow: [regulars, chanops]
      commands:
        reset: ops
  recipes:
    gamenight:
      allow: [regulars]
```

A command's own setting wins. Otherwise its level is the stricter of what its author chose and its plugin's level. An `allow` list makes a plugin or command restricted.

## Name people

An entry names people:

| Entry | Matches | Platforms |
| --- | --- | --- |
| `ana` | the nick | IRC, Twitch |
| `*!*@203.0.113.7` | a hostmask, with `*` and `?` as wildcards | IRC |
| `$a:ana` | a services account. On Twitch, a numeric user ID | IRC, Twitch |

An entry the platform doesn't use stops the bot with an error naming the platform.

## Use groups

`groups` in the config names lists of entries. The built-in groups need no list:

| Group | IRC | Twitch |
| --- | --- | --- |
| `ops` | the bot's ops | the bot's ops |
| `chanops` | +o or above in the channel | the broadcaster and moderators |
| `voiced` | +v or above in the channel | the broadcaster, moderators and VIPs |
| `logged-in` | logged in to a services account | everyone |
| `broadcaster`, `moderator`, `vip`, `subscriber` | | from the person's badges |

`chanops` and `voiced` are checked in the channel the command runs in.

## See who has access

```
<mal> !access weather
<gamebot> plugin weather: open
<gamebot> !weather: restricted, allowed: ops, $a:carol
```

It shows the plugin, then each command whose access differs from the plugin's.

[Grants & denies](grants-and-denies.md) covers changing it from chat.

## Check from code

`bot.access.can_run(who, 'weather', '#games')` makes the same check the bot does.
