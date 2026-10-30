# Getting started

pinhook needs Python 3.11 or newer.

```bash
pip install pinhook
```

A bot can be started two ways: from a config file with the `pinhook` command, or from your own python file. Both take the same [options](options.md).

## From a config file

Config files can be YAML, TOML or JSON.

=== "YAML"

    ```yaml
    nickname: "ph-bot"
    server: "irc.libera.chat"
    port: 6697
    ssl_required: true
    channels:
        - "#foo"
        - "#bar"
    ```

=== "TOML"

    ```toml
    nickname = "ph-bot"
    server = "irc.libera.chat"
    port = 6697
    ssl_required = true
    channels = ["#foo", "#bar"]
    ```

=== "JSON"

    ```json
    {
        "nickname": "ph-bot",
        "server": "irc.libera.chat",
        "port": 6697,
        "ssl_required": true,
        "channels": ["#foo", "#bar"]
    }
    ```

`nickname`, `server` and `channels` are required, everything else is optional.

YAML and TOML configs work out of the box.

Start the bot with:

```bash
pinhook config.yaml
```

pinhook works out the format from the file extension. If it can't, tell it with `--format`:

```bash
pinhook --format yaml my-bot.conf
```

### Passwords and other secrets

Keep secrets out of the config file by writing `${NAME}`. pinhook fills it in from the environment variable called `NAME` when the bot starts:

```yaml
ns_pass: "${PH_NICKSERV_PASSWORD}"
```

```bash
PH_NICKSERV_PASSWORD=hunter2 pinhook config.yaml
```

It works in any value, including inside lists and plugin settings. If the variable isn't set, the bot doesn't start, and says which one is missing. To write a literal `${` in a value, write `$${`. New in 1.12.

### Mistakes in the config

If the config has a mistake pinhook stops and says which key is wrong. A key it doesn't recognise, like a typo, is logged as a warning with a suggestion instead.

## From a python file

```python
from pinhook.bot import Bot

bot = Bot(
    channels=['#foo', '#bar'],
    nickname='ph-bot',
    server='irc.libera.chat',
    port=6697,
    ssl_required=True,
)
bot.start()
```

`Bot` can also be subclassed to add your own behaviour. [adminbot](https://github.com/tildetown/adminbot) is a good example.

## Your first plugin

When it starts, the bot loads every `.py` file in its plugin folder (`plugins` by default, see [`plugin_dir`](options.md#plugin_dir)).

Save this as `plugins/hello.py`:

```python
import pinhook.plugin

@pinhook.plugin.command('!hello', help_text='says hello back')
def hello(msg):
    return pinhook.plugin.message('hi {}!'.format(msg.nick))
```

Now `!hello` in a channel gets a reply, and the command shows up in `!help`. Change the file and an op can run `!reload` to pick it up without restarting the bot.

[Writing plugins](plugins.md) covers the rest: listeners, op-only commands, and everything a plugin can see about a message.

## Logs

The bot logs to the console and to `<nickname>.log` in the folder it runs from. See [`log_level`](options.md#log_level) and [`log_file`](options.md#log_file) to change that, and [Troubleshooting](troubleshooting.md) for what the messages mean.
