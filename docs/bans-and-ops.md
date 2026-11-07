# Bans and ops

Ops run the bot's admin commands and every plugin. Banned people are ignored completely.

## Make someone an op

```yaml
ops:
  - '$a:mal'
```

Use an account entry for ops. A nick on its own lets anyone who takes that nick act as an op. `!op ana` adds an op until the bot restarts, and `!deop ana` removes one.

## Ban someone

```
<mal> !ban troll
<gamebot> mal: banned troll (account trollacct)
```

`!ban` saves the entry hardest to dodge, the same way [`!allow`](grants-and-denies.md#what-gets-saved) does. It also takes an entry: `!ban *!*@203.0.113.*` or `!ban $a:troll`. Bans made with `!ban` are saved in [`ban_file`](options.md#people).

Bans in the config stay there:

```yaml
banned_users:
  - '$a:troll'
  - '*!*@203.0.113.7'
```

## Lift a ban

```
<mal> !unban troll
```

`!unban` with the nick they use now removes every ban that matches them, account and host bans included. A ban from the config comes back on restart until it's taken out of the config.

## Only answer logged-in people

```yaml
require_account: true
```

The bot ignores anyone not logged in to a services account, which makes bans much harder to dodge. Guests can't use the bot at all. The server has to support the `account-tag` capability, and the bot logs an error when it doesn't.
