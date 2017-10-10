# pinhook
a pluggable irc bot framework in python

# Currently in very early stages and may change wildly until final release

## Tutorial
### Installation
```
$ pip install git+git://github.com/archangelic/pinhook.git
```

### Creating the Bot
To create the bot, just create a python file with the following:

```python
import pinhook.bot

bot = pinhook.bot.Bot(
    channels=['#foo', '#bar'],
    nickname='ph-bot',
    server='irc.freenode.net'
)
bot.start()
```

This will start a basic bot and look for plugins in the 'plugins' directory to add functionality.

Optional arguments are:
* `port`: choose a custom port to connect to the server (default: 6667)
* `ops`: list of operators who can do things like make the bot join other channels or quit (default: empty list)
* `plugin_dir`: directory where the bot should look for plugins (default: "plugins")

### Creating plugins
In your chosen plugins directory ("plugins" by default) make a python file with a function. You can use the `@pinhook.plugin.register` decorator to tell the bot the command to activate the function.

The function will need to be structured as such:
```python
import pinhook.plugin

@pinhook.plugin.register('!test')
def test_plugin(msg):
    message = '{}: this is a test!'.format(msg.nick)
    return pinhook.plugin.message(message)
```

The function will need to accept a single argument in order to accept a `Message` object from the bot.

The `Message` object has the following attributes:
* `cmd`: the command that triggered the function
* `nick`: the user who triggered the command
* `arg`: all the trailing text after the command. This is what you will use to get optional information for the command
* `channel`: the channel where the command was initiated
* `ops`: the list of bot operators
* `botnick`: the nickname of the bot

The plugin function **must** return one of the following in order to give a response to the command:
* `pinhook.plugin.message`: basic message in channel where command was triggered
* `pinhook.plugin.action`: CTCP action in the channel where command was triggered (basically like using `/me does a thing`)

## Examples
There are some basic examples in the `examples` directory in this repository.

For a live and maintained bot running the current version of pinhook see [pinhook-tilde](https://github.com/archangelic/pinhook-tilde).
