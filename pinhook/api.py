"""The 2.0 plugin API: Plugin, and the command, on and every decorators.

    from pinhook import Plugin, command, on, every

    class Dice(Plugin):
        @command('roll', help='roll dice, e.g. roll 2d6')
        async def roll(self, ctx, dice: str = '1d6', times: int = 1):
            await ctx.reply(f'{ctx.nick} rolled {roll_dice(dice, times)}')

Handlers are async functions that take a ctx. Plain module-level functions work
too, for plugins with nothing to keep between messages.
"""
import inspect
import re

# what @on handles. message is every message that isn't a command, notice is notices only
EVENTS = {'message', 'notice', 'join', 'part', 'kick', 'quit', 'nick', 'topic', 'invite', 'mode',
          'connected', 'disconnected'}
# command names are written without a prefix
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]*$')


class Plugin:
    """A plugin written as a class, whose methods are its commands and event handlers.

    The bot makes one instance of each Plugin class in a plugin file. setup runs
    when it loads, with previous as None. On !reload the bot makes a new instance
    and calls its setup with the old one as previous, so it can copy across any
    state it wants to keep. Then it calls the old instance's teardown, so take
    anything you keep away from previous, like `self.conn, previous.conn = previous.conn, None`.
    teardown also runs when the plugin is removed and when the bot quits.
    """

    def setup(self, previous):
        """Called when the plugin loads. previous is the old instance on !reload, or None."""

    def teardown(self):
        """Called when this instance is replaced or removed, or the bot quits."""


def _mark(func, **spec):
    if not inspect.iscoroutinefunction(func):
        raise TypeError('{} is a 2.0 handler, so it has to be async: write async def {}(...)'
                        .format(func.__qualname__, func.__name__))
    func.__dict__.setdefault('_pinhook', []).append(spec)
    return func


def command(name, help=None, ops=False, restricted=False, denied_msg='', error_msg='',
            timeout=None, hide=False):
    """Make an async function a command. Its arguments after ctx come from the message, typed.

    Args:
        name: the command's name, without a prefix: 'roll' answers to !roll.
        help: shown in !help. Defaults to the first line of the function's docstring.
        ops: if True, only bot operators can run it.
        restricted: if True, only ops and the people they give access to can run it.
        denied_msg: what anyone who can't run it is told when they try. Empty means no reply.
        error_msg: said in chat if the command fails. Empty means the failure is only logged.
        timeout: seconds before the bot stops waiting for it, instead of the bot's default.
        hide: if True, leave it out of !help.
    """
    if not NAME.match(name):
        raise ValueError("command names are letters, digits, - and _, without a prefix: "
                         "'{}'".format(name))
    if ops and restricted:
        raise ValueError("{} can be ops=True or restricted=True, not both".format(name))

    def mark(func):
        doc = (inspect.getdoc(func) or '').strip().splitlines()
        return _mark(func, kind='command', name=name, help_text=help or (doc[0] if doc else 'N/A'),
                     ops=ops, restricted=restricted, denied_msg=denied_msg, error_msg=error_msg,
                     timeout=timeout, hide=hide)
    return mark


def every(seconds=0, minutes=0, hours=0, timeout=None):
    """Make an async function run on a timer, first one interval after its plugin loads.

    It gets a ctx with no channel or sender, so it answers with ctx.send(target, text).
    It only runs while the bot is connected, and a run still going when the next one is
    due is left to finish instead of starting another.

    Args:
        seconds, minutes, hours: how often, added together, like every(minutes=30).
        timeout: seconds before the bot stops waiting for it, instead of the bot's default.
    """
    interval = seconds + minutes * 60 + hours * 3600
    if interval <= 0:
        raise ValueError('every() needs a time, like every(minutes=30)')

    def mark(func):
        return _mark(func, kind='timer', name=func.__name__, interval=interval, timeout=timeout)
    return mark


def on(event, timeout=None):
    """Make an async function handle an event, like 'join'. It gets a ctx about the event.

    Args:
        event: one of message, notice, join, part, kick, quit, nick, topic, invite, mode,
            connected or disconnected.
        timeout: seconds before the bot stops waiting for it, instead of the bot's default.
    """
    if event not in EVENTS:
        raise ValueError("@on takes one of {}, not '{}'".format(', '.join(sorted(EVENTS)), event))

    def mark(func):
        return _mark(func, kind='event', name=func.__name__, event=event, timeout=timeout)
    return mark
