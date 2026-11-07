# Grants & denies

Ops give and take access from chat. Grants and denies are saved in `data_dir` and last through restarts.

## Give someone access

```
<mal> !allow weather carol
<gamebot> mal: gave access to plugin weather to carol (account carol)
```

`!allow` takes a plugin or a command, then one or more people or groups. A command is written with or without its prefix: `!allow !weather carol`.

## Keep someone off

```
<mal> !deny games troll
```

A deny beats a grant, and works on open plugins too.

## Take it back

```
<mal> !revoke weather carol
```

`!revoke` removes grants and denies for that person, by their nick or whatever was saved for them. Grants and denies in the config stay until they're taken out of the config.

## What gets saved

A nick is easy to change, so `!allow`, `!deny` and `!ban` save the entry that's hardest to dodge:

| Platform | Saved |
| --- | --- |
| IRC | their account, `$a:carol`, when they're logged in. Otherwise their user and host, `*!*carol@203.0.113.7` |
| Twitch | their user ID, `$a:12345678` |

Someone who hasn't spoken since the bot started is saved by nick on IRC, and the reply says so. An entry or group name is saved as written: `!allow weather $a:carol`, `!allow weather regulars`.

## Who can't be given access

An `ops` level is set only in the config, so `!allow` and `!deny` refuse it. `!allow` refuses an open plugin, since everyone already has access.

Every `!allow`, `!deny` and `!revoke` is logged as an [audit line](deployment.md#logs).
