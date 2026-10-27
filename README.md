# pinhook

[![Supported Python versions](https://img.shields.io/pypi/pyversions/pinhook.svg)](https://pypi.org/project/pinhook) [![Package License](https://img.shields.io/pypi/l/pinhook.svg)](https://github.com/archangelic/pinhook/blob/master/LICENSE) [![PyPI package format](https://img.shields.io/pypi/format/pinhook.svg)](https://pypi.org/project/pinhook) [![Package development status](https://img.shields.io/pypi/status/pinhook.svg)](https://pypi.org/project/pinhook) [![With love from tilde.town](https://img.shields.io/badge/with%20love%20from-tilde%20town-e0b0ff.svg)](https://tilde.town)

The pluggable python framework for IRC bots and Twitch bots

* [Installation](#installation)
* [Creating an IRC Bot](#creating-an-irc-bot)
  * [From Config File](#from-config-file)
  * [From Python File](#from-python-file)
* [Options](#options)
* [Built-in commands](#built-in-commands)
* [Creating a Twitch Bot](#creating-a-twitch-bot)
* [Creating plugins](#creating-plugins)
* [Examples](#examples)

## Installation

Pinhook can be installed from PyPI:

``` bash
pip install pinhook
```

## Creating an IRC Bot

A pinhook bot can be initialized using the command line tool `pinhook` with a config file, or by importing it into a python file to extend the base class.

### From Config File

Pinhook supports configuration files in YAML, TOML, and JSON formats.

Example YAML config:

```YAML
nickname: "ph-bot"
server: "irc.somewhere.net"
channels:
    - "#foo"
    - "#bar"
```

Required configuration keys:

* `nickname`: (string) nickname for your bot
* `server`: (string) server for the bot to connect
* `channels`: (array of strings) list of channels to connect to once connected

Any of the [options](#options) below can also be added to the config file.

YAML configs need `pip install pinhook[yaml]`. TOML configs work out of the box on Python 3.11 and newer, older versions need `pip install pinhook[toml]`.

Once you have your configuration file ready and your plugins in place, you can start your bot from the command line:

```bash
pinhook config.yaml
```

Pinhook will try to detect the config format from the file extension, but the format can also be supplied using the `--format` option.

```bash
$ pinhook --help
Usage: pinhook [OPTIONS] CONFIG

Options:
  -f, --format [json|yaml|toml]
  --help                         Show this message and exit.
```

### From Python File

To create the bot, just create a python file with the following:

```python
from pinhook.bot import Bot

bot = Bot(
    channels=['#foo', '#bar'],
    nickname='ph-bot',
    server='irc.libera.chat'
)
bot.start()
```

This will start a basic bot and look for plugins in the 'plugins' directory to add functionality. Any of the [options](#options) below can be passed as keyword arguments.

## Options

These work the same in a config file or as keyword arguments to `Bot`. If pinhook doesn't recognise an option (say, a typo like `ssl_requred`) it logs a warning and suggests the closest match.

* `port`: (default: `6667`) choose a custom port to connect to the server
* `ssl_required`: (default: `False`) connect using ssl, usually on port `6697`
* `ssl_verify`: (default: `True`) check the server's ssl certificate. Only turn this off for servers with self-signed certificates
* `server_pass`: password for the server
* `ns_pass`: password to identify with nickserv
* `nickserv`: (default: `"NickServ"`) nick of the nickserv service, if your network calls it something else
* `ops`: (default: empty list) list of operators who can do things like make the bot join other channels or quit
* `banned_users`: (default: empty list) nicks the bot will ignore completely
* `plugin_dir`: (default: `"plugins"`) directory where the bot should look for plugins
* `cmd_prefix`: (default: `"!"`) prefix for the [built-in commands](#built-in-commands)
* `use_prefix_for_plugins`: (default: `False`) add `cmd_prefix` to plugin commands too, so `@command('roll')` answers to `!roll`
* `disable_help`: (default: `False`) turn off the built-in help command
* `bot_mode`: (default: `True`) mark the bot as a bot on servers that support it (sets the user mode the server advertises as `BOT`)
* `log_level`: (default: `"info"`) one of `"debug"`, `"info"`, `"warning"`, `"error"` or `"critical"`. Logging can be disabled by setting this to `"off"`
* `log_file`: (default: `"<nickname>.log"`) file to write logs to. Each bot gets its own log file and log level

## Built-in commands

Every bot comes with these commands (shown with the default `!` prefix):

* `!help`: private messages the list of commands. Anyone can use this, ops also see the op-only commands
* `!banlist`: list banned nicks. Anyone can use this

Ops only:

* `!join #channel [key]`: join a channel
* `!quit [message]`: disconnect and stop the bot
* `!reload`: reload all plugins from the plugin directory
* `!enable <plugin>` / `!disable <plugin>`: turn a plugin on or off without removing it
* `!op <nick>` / `!deop <nick>`: add or remove a bot operator
* `!ops`: list bot operators
* `!ban <nick>` / `!unban <nick>`: make the bot ignore a nick, or stop ignoring it

## Creating a Twitch Bot

Pinhook has a baked in way to connect directly to a twitch channel

```python
from pinhook.bot import TwitchBot

bot = TwitchBot(
    nickname='ph-bot',
    channel='#channel',
    token='super-secret-oauth-token'
)
bot.start()
```

This function has far less options, as the server and ssl are already handled for you. TwitchBot always connects to `irc.chat.twitch.tv` over ssl so your token isn't sent in plain text.

Optional arguments are:

* `port` (default: `6697`)
* `ops`
* `banned_users`
* `plugin_dir`
* `cmd_prefix`
* `use_prefix_for_plugins`
* `disable_help`
* `bot_mode`
* `log_level`
* `log_file`

These options are the same for both IRC and Twitch

## Creating plugins

There are two types of plugins, commands and listeners. Commands only activate if a message starts with the command word, while listeners receive all messages and are parsed by the plugin for maximum flexibility.

In your chosen plugins directory ("plugins" by default) make a python file with a function. You use the `@pinhook.plugin.command` decorator to create command plugins, or `@pinhook.plugin.listener` to create listeners.

The function will need to be structured as such:

```python
import pinhook.plugin

@pinhook.plugin.command('!test')
def test_plugin(msg):
    message = '{}: this is a test!'.format(msg.nick)
    return pinhook.plugin.message(message)
```

A listener gets every message that isn't a command, and is given a name instead of a command word:

```python
import pinhook.plugin

@pinhook.plugin.listener('hello')
def say_hi(msg):
    if 'hello' in msg.text.lower():
        return pinhook.plugin.message('hi {}!'.format(msg.nick))
```

The function will need to accept a single argument in order to accept a `Message` object from the bot.

The `Message` object has the following attributes:

* `cmd`: (for command plugins) the command that triggered the function
* `nick`: the user who triggered the command
* `user`: the username part of the user's hostmask (`nick!user@host`)
* `arg`: (for command plugins) all the trailing text after the command. This is what you will use to get optional information for the command
* `text`: (for listener plugins) the entire text of the message
* `channel`: the channel where the command was initiated
* `nick_list`: list of nicks in the channel (just the sender for private messages)
* `msg_type`: `"message"` for normal messages, `"action"` for `/me` messages
* `ops`: the list of bot operators
* `botnick`: the current nickname of the bot
* `logger`: instance of `Bot`'s logger
* `datetime`: aware `datetime.datetime` object when the `Message` object was created
* `timestamp`: float for the unix timestamp when the `Message` object was created
* `bot`: the initialized Bot class

It also contains the following IRC functions:

* `privmsg`: send a message to an arbitrary channel or user
* `action`: same as privmsg, but does a CTCP action. (i.e., `/me does a thing`)
* `notice`: send a notice

You can optionally set a command to be used only by ops

The function will need to be structured as such:

```python
@pinhook.plugin.command('!test', ops=True, ops_msg='This command can only be run by an op')
def test_plugin(msg):
    return pinhook.plugin.message('This was run by an op!')
```

Commands can also be left out of `!help` with `hide=True`:

```python
@pinhook.plugin.command('!secret', hide=True)
def secret_plugin(msg):
    return pinhook.plugin.message('you found it!')
```

The plugin function can return one of the following in order to give a response to the command:

* `pinhook.plugin.message`: basic message in channel where command was triggered
* `pinhook.plugin.action`: CTCP action in the channel where command was triggered (basically like using `/me does a thing`)

Both take a string (multiple lines are sent as separate messages) or a list of strings. Returning anything else is logged as an error and nothing is sent.

## Examples

There are some basic examples in the `examples` directory in this repository.

Here is a list of live bots using pinhook:

* [pinhook-tilde](https://github.com/archangelic/pinhook-tilde) - fun bot for tilde.town
* [adminbot](https://github.com/tildetown/adminbot) - admin helper bot for tilde.town, featuring some of the ways you can change the Bot class to suit your needs
