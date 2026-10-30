"""Channel member tracking: accounts, modes, hostmasks, away and bots, and ctx.members."""
from pinhook.testing import Sent, TestBot

from wire import Wire, lines

ISUPPORT = 'CHANTYPES=# PREFIX=(qaohv)~&@%+ WHOX BOT=B'

# lists everyone in the channel the way member tracking sees them
MEMBERS = '''
from pinhook import command, on

def show(m):
    flags = ''.join(sorted(m.modes)) or '-'
    extra = (':bot' if m.is_bot else '') + (':away' if m.away else '')
    return '{}={}/{}{}'.format(m.nick, m.account or '-', flags, extra)

@command('members')
async def members(ctx):
    await ctx.reply(' '.join(show(m) for m in sorted(ctx.members(), key=lambda m: m.nick)))

@command('me')
async def me(ctx):
    await ctx.reply('chanop={} bot={} account={}'.format(ctx.is_chanop, ctx.is_bot, ctx.account))

@on('join')
async def joined(ctx):
    await ctx.send('#log', '{} joined as {}'.format(ctx.nick, ctx.account))
'''


def wire(tmp_path, **options):
    w = Wire(tmp_path, plugins={'members': MEMBERS}, **options)
    w.connect()
    w.welcome(isupport=ISUPPORT)
    return w


def tracked(w, nick):
    return w.bot.transport.tracker.lookup(nick)


def test_joining_a_channel_asks_whox_for_everyone(tmp_path):
    w = Wire(tmp_path, plugins={'members': MEMBERS})
    w.connect()
    sent = w.welcome(isupport=ISUPPORT)
    assert 'WHO #test %tcuhnfar,152' in lines(sent)


def test_without_whox_it_asks_plain_who(tmp_path):
    w = Wire(tmp_path)
    w.connect()
    sent = w.welcome(isupport='CHANTYPES=#')
    assert 'WHO #test' in lines(sent)


def test_names_with_multi_prefix_and_userhost_in_names(tmp_path):
    w = wire(tmp_path)
    w.receive(':irc.example.net 353 pinbot = #test :pinbot @+mal!m@mal.host ~owner!o@o.host ana',
              ':irc.example.net 366 pinbot #test :End of /NAMES list.')
    assert w.say('!members') == ['ana=-/- mal=-/ov owner=-/q pinbot=-/- tester=-/-']
    assert (tracked(w, 'mal')['user'], tracked(w, 'mal')['host']) == ('m', 'mal.host')


def test_whox_replies_give_accounts_away_and_bots(tmp_path):
    w = wire(tmp_path)
    w.receive(':irc.example.net 354 pinbot 152 #test m mal.host mal H@ mal :Mal',
              ':irc.example.net 354 pinbot 152 #test a a.host ana G 0 :Ana',
              ':irc.example.net 354 pinbot 152 #test d d.host dicebot HB+ dicebot :dice',
              ':irc.example.net 354 pinbot 999 #test x x.host other H other :not ours',
              ':irc.example.net 315 pinbot #test :End of WHO list')
    assert w.say('!members', nick='mal', account='mal') == [
        'ana=-/-:away dicebot=dicebot/v:bot mal=mal/o pinbot=-/-']
    assert tracked(w, 'other') is None


def test_plain_who_replies_give_hosts_and_modes(tmp_path):
    w = Wire(tmp_path, plugins={'members': MEMBERS})
    w.connect()
    w.welcome(isupport='CHANTYPES=#')
    w.receive(':irc.example.net 352 pinbot #test m mal.host irc.example.net mal G@ :0 Mal')
    assert w.say('!members') == ['mal=-/o:away pinbot=-/- tester=-/-']
    assert tracked(w, 'mal')['realname'] == 'Mal'


def test_extended_join_and_account_notify_keep_accounts_current(tmp_path):
    w = wire(tmp_path)
    w.receive(':ana!a@a.host JOIN #test ana :Ana')
    assert tracked(w, 'ana')['account'] == 'ana'
    w.receive(':ana!a@a.host ACCOUNT *')
    assert tracked(w, 'ana')['account'] is None
    w.receive(':ana!a@a.host ACCOUNT ana2')
    assert tracked(w, 'ana')['account'] == 'ana2'


def test_join_events_know_the_account(tmp_path):
    w = wire(tmp_path)
    w.receive(':ana!a@a.host JOIN #test ana :Ana')
    assert [s.text for s in w.sent() if s.target == '#log'] == ['ana joined as ana']


def test_account_bans_apply_the_moment_someone_joins(tmp_path):
    w = wire(tmp_path, banned_users=['$a:troll'])
    w.receive(':newnick!t@t.host JOIN #test troll :Troll')
    assert [s for s in w.sent() if s.target == '#log'] == []
    # and with no account tag on their messages, tracking still knows who they are
    assert w.say('!me', nick='newnick') == []


def test_messages_without_an_account_tag_use_the_tracked_account(tmp_path):
    w = wire(tmp_path)
    w.receive(':ana!a@a.host JOIN #test ana :Ana')
    w.sent()
    assert w.say('!me', nick='ana') == ['chanop=False bot=False account=ana']


def test_away_chghost_and_setname(tmp_path):
    w = wire(tmp_path)
    w.receive(':ana!a@a.host JOIN #test ana :Ana',
              ':ana!a@a.host AWAY :lunch',
              ':ana!a@a.host CHGHOST ana new.host',
              ':ana!ana@new.host SETNAME :Ana B')
    assert {k: tracked(w, 'ana')[k] for k in ('away', 'user', 'host', 'realname')} == {
        'away': True, 'user': 'ana', 'host': 'new.host', 'realname': 'Ana B'}
    w.receive(':ana!ana@new.host AWAY')
    assert tracked(w, 'ana')['away'] is False


def test_people_are_forgotten_once_they_share_no_channel(tmp_path):
    w = wire(tmp_path, channels=('#test', '#games'))
    w.receive(':ana!a@a.host JOIN #test ana :Ana', ':ana!a@a.host JOIN #games ana :Ana')
    w.receive(':ana!a@a.host PART #test')
    assert tracked(w, 'ana')['account'] == 'ana'
    w.receive(':op!o@o.host KICK #games ana :bye')
    assert tracked(w, 'ana') is None
    w.receive(':bob!b@b.host JOIN #test bob :Bob', ':bob!b@b.host QUIT :gone')
    assert tracked(w, 'bob') is None


def test_nick_changes_keep_modes_and_account(tmp_path):
    w = wire(tmp_path)
    w.receive(':ana!a@a.host JOIN #test ana :Ana', ':op!o@o.host MODE #test +o ana',
              ':ana!a@a.host NICK ana_')
    assert w.say('!members', nick='ana_') == ['ana_=ana/o pinbot=-/-']


def test_the_bot_leaving_forgets_the_channel(tmp_path):
    w = wire(tmp_path)
    w.receive(':ana!a@a.host JOIN #test ana :Ana', ':pinbot!p@p.host PART #test')
    assert w.bot.transport.members('#test') == []
    assert tracked(w, 'ana') is None


def test_is_chanop_and_is_bot_for_the_sender(tmp_path):
    w = wire(tmp_path)
    w.receive(':ana!a@a.host JOIN #test ana :Ana', ':op!o@o.host MODE #test +o ana')
    assert w.say('!me', nick='ana') == ['chanop=True bot=False account=ana']
    # bot mode: the server tags messages from bots
    w.receive('@bot :dicebot!d@d.host PRIVMSG #test :!me')
    assert [s.text for s in w.sent() if s.target == '#test'] == [
        'chanop=False bot=True account=None']


# TestBot

def test_testbot_members_have_accounts_and_modes(tmp_path):
    (tmp_path / 'members.py').write_text(MEMBERS)
    bot = TestBot(plugin_dir=str(tmp_path))
    bot.say('hi', nick='ana', account='ana')
    bot.event('mode', nick='chanserv', modes=['+v', 'ana'])
    assert bot.say('!members', nick='mal') == ['ana=ana/v mal=-/- testbot=-/-']
    assert bot.event('join', nick='bob', account='bob') == [
        Sent('message', '#log', 'bob joined as bob')]


def test_members_of_a_private_message_is_empty(tmp_path):
    (tmp_path / 'members.py').write_text(MEMBERS)
    bot = TestBot(plugin_dir=str(tmp_path))
    # an empty reply sends nothing
    assert bot.private('!members', nick='ana') == []
