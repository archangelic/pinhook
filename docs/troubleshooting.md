# Troubleshooting

Most problems show up in the bot's log. `pinhook check config.yaml` finds config, plugin and recipe problems without connecting, and `log_level: debug` logs every line the bot sends and receives.

## Starting up

| Message | What to do |
| --- | --- |
| `config.yaml has problems:` and a list | fix each setting it names |
| `a channel name isn't quoted, so YAML read it as a comment` | quote channel names: `channels: ['#games']` |
| `YAML read off as false, not a name` | quote the nick: `nickname: 'off'` |
| `config.yaml uses ${NAME}, but that environment variable isn't set` | set it, or add it to `secrets.env` beside the config |
| `other users can read secrets.env` | `chmod 600 secrets.env` |
| `unknown option 'x' ignored, did you mean 'y'?` | a typo. The bot starts without the option |
| `ops: *!*@host is a hostmask, which twitch doesn't use` | use nicks or `$a:` user IDs on Twitch |
| `could not load plugin x` | the traceback under it shows the error. The other plugins still load |
| `couldn't load a recipe: ...` | the message names the file, the step and the mistake. The other recipes still load |
| `!x is already a command of plugin y` | two plugins, or a plugin and a recipe, have the same command. Rename one |

## Connecting

The bot retries a failed connection, waiting 10 seconds at first and up to 5 minutes between tries. Each failure is logged with its reason:

| Message says | What to do |
| --- | --- |
| `the server's ssl certificate failed verification (...). If this server uses a self-signed certificate, set ssl_verify to false` | the certificate isn't signed by anyone the system trusts. Point `SSL_CERT_FILE` at it, or set `ssl_verify: false` |
| `Set server to the name the certificate was issued for` | use the server's real name in `server`, not an IP address or alias |
| `This needs fixing on the server` | the server's certificate has expired. Tell its admins |
| `ssl handshake failed (...). Check 6667 is the server's ssl port` | `ssl_required` is on, but `port` is the plain-text port. Use `6697` |
| `server name not found` | a typo in `server`, or no network |
| `connection refused` | nothing is listening on that port |
| `the server took too long to answer` | the server is down, or a firewall drops the connection |

## Logging in

| Message | What it means |
| --- | --- |
| `logged in as x with SASL ...` | the bot is logged in to its account |
| `SASL login as x failed (...), check sasl_account and sasl_password` | the server turned the login down, and says why in brackets. The bot connects without its account |
| `... check the client certificate is added to the account` | SASL EXTERNAL failed: add the certificate's fingerprint to the account |
| `the bot can't log in with SASL here` | the server offers no mechanism the bot has details for. Use `ns_pass` on this server |
| `sasl_password will be sent without ssl` | turn on `ssl_required`, and set `port` to the TLS port |
| `nickname x in use, trying x_` | someone has the nick. Log in with SASL, so a network that keeps registered nicks for their account gives it to the bot |
| `require_account is on but this server doesn't tell the bot who is logged in` | turn off `require_account` on this server |

## The bot doesn't answer

1. **Is it a command?** A command starts with the prefix, or the bot's nick: `!roll` or `gamebot: roll`. Check `!help`
2. **Can they run it?** `!access <command>` shows its level and who's allowed
3. **Is it turned off here?** An op turns it back on with `!enable <name>`
4. **Are they banned?** `!banlist` lists bans, which match accounts and hostmasks, not just nicks
5. **Did it fail?** Look for `issue with command !x` in the log, with a traceback under it

## While it runs

| Message | What it means |
| --- | --- |
| `issue with command !x` | the command raised. The traceback shows where. `error_msg=` on the command says something in chat too |
| `!x took longer than 30 seconds, giving up waiting for it` | the command didn't finish in time. `timeout=` on the command gives it longer |
| `x returned something, 2.0 handlers answer with ctx.reply()` | a 2.0 handler returned a value instead of calling `ctx.reply()` |
| `N lines are already waiting to go to x, dropping new ones` | a plugin sent faster than the rate limit allows for too long. Send less, or send it in fewer lines |
| `plugin x sent a notice to y, but this network has no notices from bots` | on Twitch: check `ctx.supports('notice')` first |
| `x reads store.y, which no recipe sets` | a recipe reads a store key nothing writes, most often a typo |
