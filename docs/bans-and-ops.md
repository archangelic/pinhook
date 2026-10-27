# Bans and ops

[`ops`](options.md#ops) decides who can run op-only commands, and [`banned_users`](options.md#banned_users) who the bot ignores. Both take the same three kinds of entry.

## Kinds of entry

| Entry | Example | Matches | How hard to dodge |
| --- | --- | --- | --- |
| Nick | `troll` | that nick, in any case | easy: anyone can change their nick |
| Hostmask | `*!*troll@203.0.113.7` | `nick!user@host`, with `*` and `?` wildcards | takes a new connection or address |
| Account | `$a:troll` | anyone logged in to that services account | takes registering a new account |

```yaml
ops:
    - "$a:mal"
banned_users:
    - "$a:troll"
    - "*!*@203.0.113.7"
```

Accounts are the strongest, for bans and for ops. With nick-only ops, anyone who takes an op's nick while they're away gets op powers. With `$a:mal`, they'd need mal's password.

!!! note
    Account entries need a server that supports [account tags](https://ircv3.net/specs/extensions/account-tag), which most modern networks do, Libera included. On a server without them, account entries never match, so use hostmasks there.

## Bans with !ban

`!ban troll` bans troll's account if they're logged in, or their username and host if not, so changing nick doesn't get around it. It can only do that if troll has spoken since the bot started. Otherwise it bans the nick and says so. [Built-in commands](commands.md#ban-and-unban) has the details.

Host bans include the username (`*!*troll@host`, not `*!*@host`) so other people sharing a host, like everyone on a tilde server, aren't caught too. To ban a whole host, give the mask yourself: `!ban *!*@203.0.113.7`.

Bans made with `!ban` are saved to [`ban_file`](options.md#ban_file) and last through restarts.

## require_account

With [`require_account`](options.md#require_account) on, the bot only answers people logged in to a services account. Every dodge then needs a new registered account, but guests can't use the bot.

If the server doesn't support account tags, the bot would ignore everyone. It logs an error when it connects to warn you.

## In plugins

Use `msg.is_op` to check whether the sender is an op. It understands accounts and hostmasks, where `msg.nick in msg.ops` only compares nicks.

```python
@pinhook.plugin.command('!announce')
def announce(msg):
    if not msg.is_op:
        return pinhook.plugin.message('only ops can announce')
    ...
```

For a command that's only ever for ops, `@command('!announce', ops=True)` does the check for you.

## What bans don't do

A pinhook ban only means the bot ignores someone. It doesn't kick or ban them from the channel. That's still a job for the channel's own `+b` bans.
