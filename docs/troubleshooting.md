# Troubleshooting

Most problems show up in the bot's log, on the console and in [`log_file`](options.md#log_file). Set [`log_level`](options.md#log_level) to `"debug"` to see every message the bot receives and what it does with it.

## Starting up

| Message | What to do |
| --- | --- |
| `config.yaml has problems:` followed by a list | Fix each key it lists. It names the key and what's wrong with its value |
| `unknown option 'x' ignored, did you mean 'y'?` | A typo, or an option that doesn't exist. The bot still starts, without it |
| `log_level must be one of: ...` | Use one of the listed levels |
| `couldn't read ban file ...` | The [ban file](options.md#ban_file) isn't valid JSON. Fix or remove it. The bot won't start rather than lose the bans in it |
| `ban file ... should be a list of ban entries` | The ban file should look like `["troll", "$a:troll"]` |
| `could not load plugin` | That plugin has an error. The traceback under it says where. The other plugins still load |

## Connecting

pinhook keeps retrying every 1 to 5 minutes when it can't connect, and logs why each time:

| Message says | What to do |
| --- | --- |
| `the server's ssl certificate failed verification (...). If this server uses a self-signed certificate, set ssl_verify to false` | The certificate isn't signed by anyone your system trusts. If it's self-signed on purpose, set [`ssl_verify`](options.md#ssl_verify) to `false` |
| `... Set server to the name the certificate was issued for, not an IP address or alias` | The certificate is fine, but for a different name. Use the server's real name in `server` |
| `... This needs fixing on the server` | The server's certificate has expired. Tell its admins |
| `ssl handshake failed (...). Check 6667 is the server's ssl port, usually 6697` | [`ssl_required`](options.md#ssl_required) is on but `port` is the plain-text port |
| `server name not found, check the server setting` | A typo in `server`, or no network |
| `connection refused, check the server and port settings` | Nothing is listening on that port |

Once connected:

| Message | What it means |
| --- | --- |
| `nickname x in use, trying x_` | Someone else has the nick, so the bot picked a new one. Nothing to fix, unless you'd rather use a different nickname |
| `require_account is on but this server doesn't tell the bot who is logged in (account-tag), so the bot will ignore everyone` | Turn off [`require_account`](options.md#require_account) on this server |

## The bot doesn't answer

Work through these in order:

1. **Is it a command?** Commands only run when the message starts with the command word exactly. Check `!help`
2. **Is the plugin loaded and enabled?** `!help` lists commands and listeners. An op can `!enable` a disabled one
3. **Are you banned?** An op can check `!banlist`. Bans can match accounts and hostmasks, not just nicks
4. **Is `require_account` on?** Then you need to be logged in to a services account
5. **Did the plugin fail?** Look for `issue with command !x` or `issue with listener x` in the log, with a traceback under it

## Plugin messages

| Message | What it means |
| --- | --- |
| `issue with command !x` / `issue with listener x` | The plugin raised an exception. The traceback under it says where |
| `plugins must return message() or action(), got str` | The plugin returned a plain string. Wrap it: `return pinhook.plugin.message(text)` |
| `output message too long: ...` | One line was over IRC's 512-byte limit, so it and the lines after it weren't sent. Split long output into a list of lines |
| `@register is deprecated and will be removed in 2.0 ...` | Swap `@register('!x')` for `@command('!x')` |
| `@ops is deprecated and will be removed in 2.0 ...` | Swap `@ops('!x', 'msg')` for `@command('!x', ops=True, ops_msg='msg')` |
| `msg.bot is deprecated and will be read only in 2.0 ...` | See [Preparing for 2.0](preparing-for-2.md) for what to use instead |
