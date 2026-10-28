# API reference

Everything a plugin or bot script uses, generated from pinhook's own code. For how to use it, with examples, see [Writing plugins](plugins.md), [Testing plugins](testing.md) and [Options](options.md).

## Writing plugins

::: pinhook.plugin.command

::: pinhook.plugin.listener

::: pinhook.plugin.message

::: pinhook.plugin.action

## The message

::: pinhook.bot.Bot.Message
    options:
      members: [reply, send, action, notice, bot]

## Bots

::: pinhook.bot.Bot
    options:
      members: [store, config_for, path]

::: pinhook.bot.TwitchBot
    options:
      members: false

## Saved data and settings

::: pinhook.store.Store
    options:
      members: [save_if_changed]

::: pinhook.store.PluginConfig
    options:
      members: false

## Testing

::: pinhook.testing.TestBot
    options:
      members: [say, action, private, sent_to, store]
      inherited_members: [store]

::: pinhook.testing.Sent

::: pinhook.testing.PluginError

## Deprecated

::: pinhook.plugin.register

::: pinhook.plugin.ops
