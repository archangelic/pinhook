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

bot = pinhook.bot.Bot(channels=['#foo', '#bar'], nickname='ph-bot', server='irc.freenode.net')
bot.start()
```

This will start a basic bot and look for plugins in the 'plugins' directory to add functionality.

Optionally, you can change the `port` and add a list of operators with the `ops` argument.
