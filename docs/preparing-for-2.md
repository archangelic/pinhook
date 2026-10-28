# Preparing for 2.0

pinhook 2.0 will change how plugins talk to the bot. 1.12 adds the new ways alongside the old ones, so you can update your plugins now, one at a time, and they'll keep working in both.

Nothing here is urgent. Plugins written for 1.11 work in 1.12 unchanged, and the old ways log a warning saying what to use instead.

## What to change

| If your plugin... | Change it to |
| --- | --- |
| uses `@register('!x')` | `@command('!x')` |
| uses `@ops('!x', 'only ops')` | `@command('!x', ops=True, ops_msg='only ops')` |
| checks `msg.nick in msg.ops` | `msg.is_op`, which also understands accounts and hostmasks |
| sends through `msg.bot.connection` | `msg.reply(text)`, `msg.send(target, text)`, `msg.action(text)` or `msg.notice(text)` |
| reads `msg.bot.bot_nick` | `msg.botnick` |

For example:

=== "1.11"

    ```python
    @pinhook.plugin.register('!launch')
    def launch(msg):
        if msg.nick not in msg.ops:
            return pinhook.plugin.message('only ops can launch')
        msg.bot.connection.privmsg('#announcements', 'liftoff!')
        return pinhook.plugin.message('launched')
    ```

=== "1.12 and 2.0"

    ```python
    @pinhook.plugin.command('!launch')
    def launch(msg):
        if not msg.is_op:
            return pinhook.plugin.message('only ops can launch')
        msg.send('#announcements', 'liftoff!')
        return pinhook.plugin.message('launched')
    ```

## Finding what needs changing

Run your plugin tests with deprecation warnings turned into errors. Each warning points at the line in your plugin that needs changing:

```bash
pytest -W error::DeprecationWarning
```

No tests yet? [Testing plugins](testing.md) shows how to write them with `TestBot`.

On a running bot, each deprecation is logged once, as a warning:

```
WARNING - bot.ph-bot - bot - msg.bot is deprecated and will be read only in 2.0, use msg.reply(), msg.send() and msg.botnick instead
```

## What's planned for 2.0

These are plans, not promises yet. They might change before 2.0 is released.

* `msg.bot` becomes read only: plugins can look at the bot's nick and channels, but not reach into it
* `@register` and `@ops` are removed
* plugins can keep their own data between restarts, and have their own section in the config file. Until then, a plugin that reads its own settings off a Bot subclass (like `msg.bot.modteam`) should keep doing so
* replies don't block: the bot can answer other people while a plugin sends a long reply
* commands are written without their prefix, and the bot's config chooses the prefix
* 1.x plugins still run in 2.0 through a compatibility layer, with warnings
