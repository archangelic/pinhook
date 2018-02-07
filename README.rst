pinhook
=======

the pluggable python framework for IRC bots and Twitch bots

Tutorial
--------

Installation
~~~~~~~~~~~~

::

    $ pip install pinhook

Creating an IRC Bot
~~~~~~~~~~~~~~~~~~~

To create the bot, just create a python file with the following:

.. code:: python

    from pinhook.bot import Bot

    bot = Bot(
        channels=['#foo', '#bar'],
        nickname='ph-bot',
        server='irc.freenode.net'
    )
    bot.start()

This will start a basic bot and look for plugins in the 'plugins'
directory to add functionality.

Optional arguments are:

-  ``port``: choose a custom port to connect to the server (default:
   6667)
-  ``ops``: list of operators who can do things like make the bot join
   other channels or quit (default: empty list)
-  ``plugin_dir``: directory where the bot should look for plugins
   (default: "plugins")
-  ``log_level``: string indicating logging level. Logging can be
   disabled by setting this to "off". (default: "info")
-  ``ns_pass``: this is the password to identify with nickserv
-  ``server_pass``: password for the server
-  ``ssl_required``: boolean to turn ssl on or off

Creating a Twitch Bot
~~~~~~~~~~~~~~~~~~~~~

Pinhook has a baked in way to connect directly to a twitch channel

.. code:: python

    from pinhook.bot import TwitchBot

    bot = TwitchBot(
        nickname='ph-bot',
        channel='#channel',
        token='super-secret-oauth-token'
    )
    bot.start()

This function has far less options, as the server, port, and ssl are
already handled by twitch.

Optional aguments are:

-  ``ops``
-  ``plugin_dir``
-  ``log_level``

These options are the same for both IRC and Twitch

Creating plugins
~~~~~~~~~~~~~~~~

In your chosen plugins directory ("plugins" by default) make a python
file with a function. You can use the ``@pinhook.plugin.register``
decorator to tell the bot the command to activate the function.

The function will need to be structured as such:

.. code:: python

    import pinhook.plugin

    @pinhook.plugin.register('!test')
    def test_plugin(msg):
        message = '{}: this is a test!'.format(msg.nick)
        return pinhook.plugin.message(message)

The function will need to accept a single argument in order to accept a
``Message`` object from the bot.

The ``Message`` object has the following attributes:

-  ``cmd``: the command that triggered the function
-  ``nick``: the user who triggered the command
-  ``arg``: all the trailing text after the command. This is what you
   will use to get optional information for the command
-  ``channel``: the channel where the command was initiated
-  ``ops``: the list of bot operators
-  ``botnick``: the nickname of the bot
-  ``logger``: instance of ``Bot``'s logger

The plugin function **must** return one of the following in order to
give a response to the command:

-  ``pinhook.plugin.message``: basic message in channel where command
   was triggered
-  ``pinhook.plugin.action``: CTCP action in the channel where command
   was triggered (basically like using ``/me does a thing``)

Examples
--------

There are some basic examples in the ``examples`` directory in this
repository.

For a live and maintained bot running the current version of pinhook see
`pinhook-tilde <https://github.com/archangelic/pinhook-tilde>`__.
