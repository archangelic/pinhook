# Twitch

pinhook runs Twitch bots over Twitch's chat servers, with the same plugins, recipes and access rules as on IRC.

## Connect the bot account

Make an OAuth token for the bot's Twitch account, with the `chat:read` and `chat:edit` scopes. Then, beside the config:

```bash
pinhook connect twitch twitch.yaml
```

It asks for the token without showing it, saves it as `TWITCH_TOKEN` in `secrets.env`, readable only by you, and says what the config still needs.

## Configure it

Save this as `twitch.yaml`:

```yaml
platform: twitch
nickname: 'gamebot'
channels:
  - '#yourchannel'
token: '${TWITCH_TOKEN}'
bot_dir: '.'
```

A Twitch bot joins one channel, and needs no `server`. A token pasted with `oauth:` in front works too.

## Run it

```bash
pinhook check twitch.yaml
pinhook run twitch.yaml
```

## How Twitch differs

| | On Twitch |
| --- | --- |
| Rate limits | 20 lines in any 30 seconds, and one a second in channels where the bot isn't a moderator, VIP or the broadcaster |
| Message length | 500 characters. Longer replies are split |
| Repeats | Twitch drops a line identical to the last one, so the bot adds an invisible character to every other repeat |
| `ctx.account` | the sender's numeric user ID, which stays the same when they rename |
| `ctx.is_chanop` | `True` for the broadcaster and moderators |
| `ctx.action` | sent as `/me` |
| `ctx.notice` | a notice to the channel is sent as a message. One to a person isn't sent, and the bot logs a warning once per plugin |
| Private replies and `!help` | answered in the channel, addressed to the person |
| Join and part events | late, and not for everyone in a big channel |

`ctx.supports('notice')` and `ctx.supports('private')` are `False` on Twitch, so a plugin picks its own fallback.

## Use badges for access

Badges are [access groups](access-levels.md#use-groups): `broadcaster`, `moderator`, `vip` and `subscriber`, from each person's latest message. `chanops` is the broadcaster and moderators, and `voiced` adds VIPs.

```yaml
access:
  plugins:
    clips:
      allow: [subscriber, vip]
```

Entries on Twitch are nicks and `$a:` user IDs. Hostmasks stop the bot with an error.
