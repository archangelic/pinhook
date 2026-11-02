"""Every 1.x plugin feature that 2.0 runs, through its compatibility layer."""
import pinhook.plugin as p


@p.command('!legacy', help_text='say hello the 1.x way')
def legacy(msg):
    return p.message('hello {} from 1.x'.format(msg.nick))


@p.command('!legacyaction')
def legacy_action(msg):
    return p.action('waves the 1.x way')


@p.command('!legacylines')
def legacy_lines(msg):
    return p.message(['first line', 'second line'])


@p.command('!legacysend')
def legacy_send(msg):
    msg.reply('replied as I go')
    channel = msg.config.shared['channel']
    msg.send(channel, 'sent to {}'.format(channel))
    msg.privmsg(msg.nick, 'a private message')
    msg.notice('a notice')
    msg.action('acts as I go')


@p.command('!legacycount')
def legacy_count(msg):
    msg.store['count'] = msg.store.get('count', 0) + 1
    return p.message('counted {} with {}'.format(msg.store['count'], msg.config.get('word')))


@p.command('!legacyops', ops=True, ops_msg='ops only, sorry')
def legacy_ops(msg):
    return p.message('hello op')


@p.command('!legacyhidden', hide=True)
def legacy_hidden(msg):
    return p.message('found the hidden one')


@p.command('!legacywho')
def legacy_who(msg):
    return p.message('nick={} op={} private={} botnick={} people={} cmd={} arg={}'.format(
        msg.nick, msg.is_op, msg.is_private, msg.botnick, len(msg.nick_list), msg.cmd,
        msg.arg))


@p.command('!legacybot')
def legacy_bot(msg):
    # msg.bot is deprecated: only the bot's nick and channels are left on it
    return p.message('bot is {}'.format(msg.bot.nick))


@p.listener('legacy_listener')
def legacy_listener(msg):
    if msg.text == 'ping legacy':
        return p.message('pong from a 1.x listener')
