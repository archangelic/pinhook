# Twitch bots

pinhook has a bot class made for Twitch chat:

```python
from pinhook.bot import TwitchBot

bot = TwitchBot(
    nickname='ph-bot',
    channel='#channel',
    token='super-secret-oauth-token'
)
bot.start()
```

`token` is the bot account's oauth token, without the `oauth:` part. TwitchBot always connects to `irc.chat.twitch.tv` over ssl, so the token isn't sent in plain text.

Plugins work exactly the same as on IRC.

## Options

TwitchBot takes fewer [options](options.md), since Twitch handles the server and ssl:

* [`port`](options.md#port) (default: `6697`)
* [`ops`](options.md#ops)
* [`banned_users`](options.md#banned_users)
* [`ban_file`](options.md#ban_file)
* [`plugin_dir`](options.md#plugin_dir)
* [`cmd_prefix`](options.md#cmd_prefix)
* [`use_prefix_for_plugins`](options.md#use_prefix_for_plugins)
* [`disable_help`](options.md#disable_help)
* [`bot_mode`](options.md#bot_mode)
* [`log_level`](options.md#log_level)
* [`log_file`](options.md#log_file)

Twitch doesn't have services accounts, so use nicks in `ops` and `banned_users`. Twitch usernames can't be changed freely like IRC nicks can.
