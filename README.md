# pinhook

[![Supported Python versions](https://img.shields.io/pypi/pyversions/pinhook.svg)](https://pypi.org/project/pinhook) [![Package License](https://img.shields.io/pypi/l/pinhook.svg)](https://github.com/archangelic/pinhook/blob/master/LICENSE) [![PyPI package format](https://img.shields.io/pypi/format/pinhook.svg)](https://pypi.org/project/pinhook) [![Package development status](https://img.shields.io/pypi/status/pinhook.svg)](https://pypi.org/project/pinhook) [![With love from tilde.town](https://img.shields.io/badge/with%20love%20from-tilde%20town-e0b0ff.svg)](https://tilde.town)

The pluggable python framework for IRC bots and Twitch bots

* [Installation](#installation)
* [Creating an IRC Bot](#creating-an-irc-bot)
  * [From Config File](#from-config-file)
  * [From Python File](#from-python-file)
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

Optional keys:

* `port`: (default: `6667`) choose a custom port to connect to the server
* `ops`: (default: empty list) list of operators who can do things like make the bot join other channels or quit
* `plugin_dir`: (default: `"plugins"`) directory where the bot should look for plugins
* `log_level`: (default: `"info"`) string indicating logging level. Logging can be disabled by setting this to `"off"`
* `ns_pass`: this is the password to identify with nickserv
* `server_pass`: password for the server
* `ssl_required`: (default: `False`) boolean to turn ssl on or off

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
    server='irc.freenode.net'
)
bot.start()
```

This will start a basic bot and look for plugins in the 'plugins' directory to add functionality.

Optional arguments are:

* `port`: (default: `6667`) choose a custom port to connect to the server
* `ops`: (default: empty list) list of operators who can do things like make the bot join other channels or quit
* `plugin_dir`: (default: `"plugins"`) directory where the bot should look for plugins
* `log_level`: (default: `"info"`) string indicating logging level. Logging can be disabled by setting this to `"off"`
* `ns_pass`: this is the password to identify with nickserv
* `server_pass`: password for the server
* `ssl_required`: (default: `False`) boolean to turn ssl on or off

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

This function has far less options, as the server, port, and ssl are already handled by twitch.

Optional aguments are:

* `ops`
* `plugin_dir`
* `log_level`

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

The function will need to accept a single argument in order to accept a `Message` object from the bot.

The `Message` object has the following attributes:

* `cmd`: (for command plugins) the command that triggered the function
* `nick`: the user who triggered the command
* `arg`: (for command plugins) all the trailing text after the command. This is what you will use to get optional information for the command
* `text`: (for listener plugins) the entire text of the message
* `channel`: the channel where the command was initiated
* `ops`: the list of bot operators
* `botnick`: the nickname of the bot
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

The plugin function can return one of the following in order to give a response to the command:

* `pinhook.plugin.message`: basic message in channel where command was triggered
* `pinhook.plugin.action`: CTCP action in the channel where command was triggered (basically like using `/me does a thing`)

## Examples

There are some basic examples in the `examples` directory in this repository.

Here is a list of live bots using pinhook:

* [pinhook-tilde](https://github.com/archangelic/pinhook-tilde) - fun bot for tilde.town
* [adminbot](https://github.com/tildetown/adminbot) - admin helper bot for tilde.town, featuring some of the ways you can change the Bot class to suit your needs
* [lucibot](https://github.com/Lucidiot/lucibot)
