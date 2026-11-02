# IRCv3 support

pinhook asks for each IRCv3 capability the server offers, and each one has a fallback, so a bot works the same on servers without it.

## Capabilities

| Capability | What the bot gets | Without it |
| --- | --- | --- |
| `sasl` | logs in while it connects, before joining channels | `ns_pass` to NickServ after connecting |
| `account-tag`, `account-notify`, `extended-join` | `ctx.account` on every message, and account entries for ops, bans and access | accounts from WHO replies when it joins |
| `server-time` | `ctx.time` is when the server got the message | the time the bot read it |
| `message-tags` | `ctx.tags`, `ctx.msgid`, and the client tags below | no tags |
| `echo-message` | the bot's own lines in `ctx.history()`, as the server saw them | its own lines as it sent them |
| `batch`, `labeled-response` | `await ctx.whois(nick)` matches answers to questions, and netsplits are one event | WHOIS answers matched by nick |
| `multi-prefix`, `userhost-in-names` | every mode and the full hostmask of each member | the highest mode, and hostmasks from WHO |
| `away-notify`, `chghost`, `setname` | members' away state, host and real name kept current | what WHO said when the bot joined |
| `invite-notify` | `invite` events for anyone invited to the bot's channels | only invites of the bot |
| `cap-notify` | capabilities the server adds or removes while connected | the list from connecting |

## Client tags

With `message-tags`, three client tags work where the server allows them. `ctx.supports()` says which:

| Feature | Used by |
| --- | --- |
| `typing` | `async with ctx.typing():` |
| `reply` | `ctx.reply(text, thread=True)` |
| `channel-context` | `ctx.reply(text, private=True)`, so the client shows the private message with the channel |

## Log in with SASL

```yaml
sasl_password: '${SASL_PASSWORD}'
```

The bot picks the strongest mechanism the server offers: EXTERNAL with a client certificate, then SCRAM-SHA-256, which never sends the password, then PLAIN. `sasl_mechanism` sets one. [`sasl_account`](options.md#logging-in) is the account, the nickname by default.

### Log in with a certificate

SASL EXTERNAL logs in with a TLS client certificate, with no password in the config:

```yaml
ssl_required: true
port: 6697
ssl_certfile: 'gamebot.pem'
ssl_keyfile: 'gamebot.key'
```

Add the certificate's fingerprint to the bot's account first, on most networks with `/msg NickServ CERT ADD`.

## Strict transport security

A server that advertises an STS policy gets a TLS connection from then on. The bot reconnects with TLS straight away, and saves the policy in `data_dir/sts.json`, so a restart doesn't go back to plain text.

## Other features

* **Bot mode**: with [`bot_mode`](options.md#commands-and-plugins) on, the bot sets the mode the server lists for bots, so WHOIS shows it as one
* **Case mapping**: nicks and channels are compared the way the server's `CASEMAPPING` says
* **MONITOR**: when the bot's nick is taken, it watches for the nick to free up and takes it back
* **WHOX**: the bot learns members' accounts when it joins, on servers without `extended-join`
