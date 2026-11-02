# API reference

Generated from pinhook's own code and type hints. [The context](the-context.md), [Typed commands](typed-commands.md) and [TestBot](testbot.md) show them in use.

## Writing plugins

::: pinhook.api.command

::: pinhook.api.on

::: pinhook.api.every

::: pinhook.api.Plugin

## The context

::: pinhook.context.Context
    options:
      members: [reply, send, action, notice, typing, members, member, whois, history, supports]

::: pinhook.transport.base.Member
    options:
      members: [is_chanop, is_voiced]

::: pinhook.transport.base.Whois
    options:
      members: false

::: pinhook.history.Entry
    options:
      members: false

## Saved data and settings

::: pinhook.store.Store
    options:
      members: false

::: pinhook.store.PluginConfig
    options:
      members: false

## Recipes

::: pinhook.recipes.step

::: pinhook.recipes.template_filter

## Bots

::: pinhook.config.load_bot

::: pinhook.config.ConfigError
    options:
      members: false

::: pinhook.bot.Bot
    options:
      members: [start, quit, commands, run_as, store]

::: pinhook.bot.TwitchBot
    options:
      members: false

::: pinhook.bot.RunResult
    options:
      members: false

::: pinhook.commands.CommandInfo
    options:
      members: false

## Testing

::: pinhook.testing.TestBot
    options:
      members: [say, action, private, event, tick, sent_to]

::: pinhook.testing.PluginError
