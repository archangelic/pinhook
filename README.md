# pinhook

[![Supported Python versions](https://img.shields.io/pypi/pyversions/pinhook.svg)](https://pypi.org/project/pinhook) [![Package License](https://img.shields.io/pypi/l/pinhook.svg)](https://github.com/archangelic/pinhook/blob/master/LICENSE) [![PyPI package format](https://img.shields.io/pypi/format/pinhook.svg)](https://pypi.org/project/pinhook) [![Package development status](https://img.shields.io/pypi/status/pinhook.svg)](https://pypi.org/project/pinhook) [![With love from tilde.town](https://img.shields.io/badge/with%20love%20from-tilde%20town-e0b0ff.svg)](https://tilde.town)

The pluggable python framework for IRC bots and Twitch bots

**Documentation: https://archangelic.github.io/pinhook/**

## Installation

``` bash
pip install pinhook
```

## Quick start

Make a `plugins` folder with this in `plugins/hello.py`:

```python
import pinhook.plugin

@pinhook.plugin.command('!hello', help_text='says hello back')
def hello(msg):
    return pinhook.plugin.message('hi {}!'.format(msg.nick))
```

Then start a bot, from a python file:

```python
from pinhook.bot import Bot

bot = Bot(
    channels=['#foo'],
    nickname='ph-bot',
    server='irc.libera.chat',
    port=6697,
    ssl_required=True,
)
bot.start()
```

or from a config file, with `pinhook config.yaml`:

```yaml
nickname: "ph-bot"
server: "irc.libera.chat"
port: 6697
ssl_required: true
channels:
    - "#foo"
```

Say `!hello` in `#foo` and the bot answers.

## Learn more

* [Getting started](https://archangelic.github.io/pinhook/latest/getting-started/)
* [Options](https://archangelic.github.io/pinhook/latest/options/)
* [Built-in commands](https://archangelic.github.io/pinhook/latest/commands/)
* [Writing plugins](https://archangelic.github.io/pinhook/latest/plugins/)
* [Bans and ops](https://archangelic.github.io/pinhook/latest/bans-and-ops/)
* [Twitch bots](https://archangelic.github.io/pinhook/latest/twitch/)
* [Troubleshooting](https://archangelic.github.io/pinhook/latest/troubleshooting/)
* [Upgrading to 1.11](https://archangelic.github.io/pinhook/latest/upgrading/)

## Examples

There are some basic examples in the `examples` directory in this repository.

Here is a list of live bots using pinhook:

* [pinhook-tilde](https://github.com/archangelic/pinhook-tilde) - fun bot for tilde.town
* [adminbot](https://github.com/tildetown/adminbot) - admin helper bot for tilde.town, featuring some of the ways you can change the Bot class to suit your needs
