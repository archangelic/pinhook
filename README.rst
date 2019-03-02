pinhook
=======

|Supported Python versions| |Package License| |PyPI package format|
|Package development status| |With love from tilde.town|

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

There are two types of plugins, commands and listeners. Commands only
activate if a message starts with the command word, while listeners
receive all messages and are parsed by the plugin for maximum
flexibility.

In your chosen plugins directory ("plugins" by default) make a python
file with a function. You use the ``@pinhook.plugin.register`` decorator
to create command plugins, or ``@pinhook.plugin.listener`` to create
listeners.

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

-  ``cmd``: (for command plugins) the command that triggered the
   function
-  ``nick``: the user who triggered the command
-  ``arg``: (for command plugins) all the trailing text after the
   command. This is what you will use to get optional information for
   the command
-  ``text``: (for listener plugins) the entire text of the message
-  ``channel``: the channel where the command was initiated
-  ``ops``: the list of bot operators
-  ``botnick``: the nickname of the bot
-  ``logger``: instance of ``Bot``'s logger
-  ``datetime``: aware ``datetime.datetime`` object when the ``Message``
   object was created
-  ``timestamp``: float for the unix timestamp when the ``Message``
   object was created

It also contains the following IRC functions:

-  ``privmsg``: send a message to an arbitrary channel or user
-  ``action``: same as privmsg, but does a CTCP action. (i.e.,
   ``/me does a thing``)
-  ``notice``: send a notice

You can optionally use the ``@pinhook.plugin.ops`` decorator to denote
that a command should only be executable by a bot op.

-  If you specify the optional second argument, it will be displayed
   when a non-op attempts to execute the command

The function will need to be structured as such:

.. code:: python

    @pinhook.plugin.register('!test')
    @pinhook.plugin.ops('!test', 'Only ops can run this command!')
    def test_plugin(msg):
        return pinhook.plugin.message('This was run by an op!')

**OR**

The plugin function can return one of the following in order to give a
response to the command:

-  ``pinhook.plugin.message``: basic message in channel where command
   was triggered
-  ``pinhook.plugin.action``: CTCP action in the channel where command
   was triggered (basically like using ``/me does a thing``)

Examples
--------

There are some basic examples in the ``examples`` directory in this
repository.

Here is a list of live bots using pinhook:

-  `pinhook-tilde <https://github.com/archangelic/pinhook-tilde>`__ -
   fun bot for tilde.town
-  `adminbot <https://github.com/tildetown/adminbot>`__ - admin helper
   bot for tilde.town, featuring some of the ways you can change the Bot
   class to suit your needs

.. |Supported Python versions| image:: https://img.shields.io/pypi/pyversions/pinhook.svg
   :target: https://pypi.org/project/pinhook
.. |Package License| image:: https://img.shields.io/pypi/l/pinhook.svg
   :target: https://github.com/archangelic/pinhook/blob/master/LICENSE
.. |PyPI package format| image:: https://img.shields.io/pypi/format/pinhook.svg
   :target: https://pypi.org/project/pinhook
.. |Package development status| image:: https://img.shields.io/pypi/status/pinhook.svg
   :target: https://pypi.org/project/pinhook
.. |With love from tilde.town| image:: https://img.shields.io/badge/with%20love%20from-tilde%20town-e0b0ff.svg
   :target: https://tilde.town
