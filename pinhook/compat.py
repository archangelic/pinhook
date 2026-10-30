"""1.x plugins on top of the context: the msg they get, and running them."""
from . import plugin


class LegacyBot:
    """What msg.bot gives 1.x plugins in 2.0: the bot's nick and channels, read only."""

    def __init__(self, ctx):
        self._info = ctx.bot

    @property
    def nick(self):
        return self._info.nick

    @property
    def bot_nick(self):
        return self._info.nick

    @property
    def channels(self):
        return self._info.channels

    def __getattr__(self, name):
        raise AttributeError(
            "msg.bot.{} is gone in pinhook 2.0, msg.bot only has the bot's nick and channels. "
            "Use msg.reply(), msg.send() and msg.botnick, and plugin_config for settings".format(
                name))


class Message:
    """A message sent to the bot, as a 1.x plugin gets it.

    Attributes:
        nick: who sent it.
        user: the username part of their hostmask (nick!user@host).
        account: the services account they're logged in to, or None.
        channel: where it was sent. For a private message, the sender's nick.
        is_private: True if it was a private message to the bot.
        cmd: (commands) the command word that triggered it.
        arg: (commands) everything after the command word.
        text: the whole message.
        msg_type: 'message', or 'action' for a /me.
        nick_list: nicks in the channel. Just the sender for private messages.
        is_op: True if the sender is a bot operator.
        ops: the list of bot operators, as written in the config.
        botnick: the bot's current nick.
        store: the plugin's saved data, a dict kept between restarts.
        config: the plugin's settings from plugin_config, read only.
        logger: the bot's logger.
        datetime: when the message was sent, a timezone-aware datetime.
        timestamp: the same as a unix timestamp.
    """

    def __init__(self, ctx, cmd=None, nick_list=None, ops=()):
        self._ctx = ctx
        self.datetime = ctx.time
        self.timestamp = ctx.time.timestamp()
        self.channel = ctx.channel
        self.nick = ctx.nick
        self.user = ctx.user
        self.account = ctx.account
        self.is_private = ctx.is_private
        self.is_op = ctx.is_op
        self.ops = ops
        self.nick_list = nick_list if nick_list is not None else [ctx.nick]
        self.botnick = ctx.bot.nick
        self.store = ctx.store
        self.config = ctx.config
        self.logger = ctx.logger
        self.msg_type = 'action' if ctx.kind == 'action' else 'message'
        self.text = ctx.text
        if cmd:
            self.cmd = cmd
            self.arg = ctx.arg

    @property
    def bot(self):
        """The bot's nick and channels. Deprecated, use msg.botnick."""
        self._ctx._bot.warn_deprecated(
            'msg.bot', "msg.bot is deprecated and only has the bot's nick and channels in 2.0, "
            'use msg.reply(), msg.send() and msg.botnick instead')
        return LegacyBot(self._ctx)

    def reply(self, text):
        """Send text where the message came from: the channel, or the sender if private."""
        self._ctx._bot.send_text('privmsg', self.channel, text)

    def send(self, target, text):
        """Send text to another channel or nick."""
        self._ctx._bot.send_text('privmsg', target, text)

    def privmsg(self, target, text):
        """Send text to a channel or nick, like send."""
        self._ctx._bot.send_text('privmsg', target, text)

    def action(self, *args):
        """action(text) replies with a /me, action(target, text) sends one somewhere else."""
        target, text = self._target_and_text(args, self.channel)
        self._ctx._bot.send_text('action', target, text)

    def notice(self, *args):
        """notice(text) sends the sender a notice, notice(target, text) sends one to anyone."""
        target, text = self._target_and_text(args, self.nick)
        self._ctx._bot.send_text('notice', target, text)

    @staticmethod
    def _target_and_text(args, default_target):
        if len(args) == 1:
            return default_target, args[0]
        if len(args) == 2:
            return args
        raise TypeError('expected (text) or (target, text), got {} arguments'.format(len(args)))


def run(handler, ctx, trigger=None, nick_list=None, ops=()):
    """Run a 1.x command or listener with its msg, and return what it returned.

    Runs in a worker thread, since 1.x plugins are plain functions.
    """
    msg = Message(ctx, cmd=trigger if handler.kind == 'command' else None, nick_list=nick_list,
                  ops=ops)
    output = handler.func(msg)
    if output and not isinstance(output, plugin.Output):
        raise TypeError('plugins must return message() or action(), got {}'.format(
            type(output).__name__))
    ctx.store.save_if_changed()
    return output
