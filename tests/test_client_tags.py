"""Client tags: threaded replies, private replies tied to a channel, and typing notices."""
from pinhook.testing import TestBot

from wire import Wire

PLUGIN = '''
from pinhook import command

@command('thread')
async def thread(ctx, text: str = 'hi'):
    await ctx.reply(text, thread=True)

@command('quietly')
async def quietly(ctx):
    await ctx.reply('just for you', private=True)

@command('slow')
async def slow(ctx):
    async with ctx.typing():
        pass
    await ctx.reply('done')

@command('can')
async def can(ctx):
    await ctx.reply(' '.join(f for f in ('typing', 'reply', 'channel-context')
                             if ctx.supports(f)) or 'nothing')
'''


def ready(tmp_path, caps='message-tags', isupport='CHANTYPES=#'):
    w = Wire(tmp_path, plugins={'plugin': PLUGIN})
    w.connect()
    w.receive(':irc.example.net CAP * LS :' + caps, ':irc.example.net CAP * ACK :' + caps)
    w.welcome(isupport=isupport)
    w.join('ana')
    w.sent()
    return w


def said(w, text, msgid='m1', nick='ana', target='#test'):
    w.receive('@msgid={} :{}!a@host PRIVMSG {} :{}'.format(msgid, nick, target, text))
    return [s.line for s in w.sent()]


def test_a_threaded_reply_is_tagged_with_the_message_it_answers(tmp_path):
    w = ready(tmp_path)
    assert said(w, '!thread') == ['@+reply=m1 PRIVMSG #test hi']


def test_every_line_of_a_threaded_reply_is_tagged(tmp_path):
    w = ready(tmp_path)
    sent = said(w, '!thread ' + 'word ' * 120)
    assert len(sent) == 2
    assert all(line.startswith('@+reply=m1 PRIVMSG #test :word') for line in sent)


def test_without_client_tags_a_threaded_reply_starts_with_the_nick(tmp_path):
    w = ready(tmp_path, caps='account-tag')
    assert said(w, '!thread') == ['PRIVMSG #test :ana: hi']


def test_without_a_message_id_a_threaded_reply_starts_with_the_nick(tmp_path):
    w = ready(tmp_path)
    w.receive(':ana!a@host PRIVMSG #test :!thread')
    assert [s.line for s in w.sent()] == ['PRIVMSG #test :ana: hi']


def test_a_threaded_reply_in_private_is_just_a_reply(tmp_path):
    w = ready(tmp_path, caps='account-tag')
    assert said(w, '!thread', target='pinbot') == ['PRIVMSG ana hi']


def test_clienttagdeny_is_respected(tmp_path):
    w = ready(tmp_path, isupport='CHANTYPES=# CLIENTTAGDENY=*,-reply')
    assert said(w, '!can') == ['PRIVMSG #test reply']
    assert said(w, '!thread', msgid='m2') == ['@+reply=m2 PRIVMSG #test hi']
    w = ready(tmp_path, isupport='CHANTYPES=# CLIENTTAGDENY=*')
    assert said(w, '!thread') == ['PRIVMSG #test :ana: hi']


def test_supports_names_the_client_tag_features(tmp_path):
    assert said(ready(tmp_path), '!can') == ['PRIVMSG #test :typing reply channel-context']
    assert said(ready(tmp_path, caps='account-tag'), '!can') == ['PRIVMSG #test nothing']


def test_a_private_reply_carries_the_channel_it_is_about(tmp_path):
    w = ready(tmp_path)
    assert said(w, '!quietly') == ['@+channel-context=#test PRIVMSG ana :just for you']


def test_without_client_tags_a_private_reply_is_a_plain_private_message(tmp_path):
    w = ready(tmp_path, caps='account-tag')
    assert said(w, '!quietly') == ['PRIVMSG ana :just for you']


def test_typing_is_shown_while_a_slow_command_works(tmp_path):
    w = ready(tmp_path)
    assert said(w, '!slow') == ['@+typing=active TAGMSG #test', '@+typing=done TAGMSG #test',
                                'PRIVMSG #test done']


def test_typing_does_nothing_without_client_tags(tmp_path):
    w = ready(tmp_path, caps='account-tag')
    assert said(w, '!slow') == ['PRIVMSG #test done']


def test_testbot_shows_the_fallbacks(tmp_path):
    (tmp_path / 'plugin.py').write_text(PLUGIN)
    bot = TestBot(plugin_dir=str(tmp_path))
    assert bot.say('!thread', nick='ana') == ['ana: hi']
    assert bot.say('!slow') == ['done']
    bot.say('!quietly', nick='ana')
    assert bot.sent_to('ana') == ['just for you']
