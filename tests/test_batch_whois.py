"""Batches (netsplits and netjoins, labeled responses) and await ctx.whois(nick)."""
from pinhook.testing import Sent, TestBot

from wire import Wire, lines

PLUGIN = '''
from pinhook import command, on

@command('whois')
async def whois(ctx, nick: str):
    info = await ctx.whois(nick)
    if info is None:
        await ctx.reply('no ' + nick)
        return
    await ctx.reply('{0.nick} {0.user}@{0.host} account={0.account} channels={1} away={0.away} '
                    'bot={0.is_bot} secure={0.secure}'.format(info, ','.join(info.channels)))

@on('netsplit')
async def split(ctx):
    await ctx.send('#log', 'split {} {}'.format(ctx.text, ' '.join(ctx.nicks)))

@on('netjoin')
async def back(ctx):
    await ctx.send('#log', 'back {} {}'.format(ctx.text, ' '.join(ctx.nicks)))

@on('quit')
async def quit(ctx):
    await ctx.send('#log', 'quit ' + ctx.nick)

@on('join')
async def join(ctx):
    await ctx.send('#log', 'join ' + ctx.nick)
'''

ANA = [':irc.example.net 311 pinbot ana a a.host * :Ana',
       ':irc.example.net 319 pinbot ana :@#test +#games',
       ':irc.example.net 330 pinbot ana anaacct :is logged in as',
       ':irc.example.net 301 pinbot ana :lunch',
       ':irc.example.net 335 pinbot ana :is a bot',
       ':irc.example.net 671 pinbot ana :is using a secure connection',
       ':irc.example.net 318 pinbot ana :End of /WHOIS list']
ANA_REPLY = ('ana a@a.host account=anaacct channels=#test,#games away=lunch bot=True '
             'secure=True')


def ready(tmp_path, caps=''):
    w = Wire(tmp_path, plugins={'plugin': PLUGIN})
    w.connect()
    if caps:
        w.receive(':irc.example.net CAP * LS :' + caps, ':irc.example.net CAP * ACK :' + caps)
    w.welcome()
    w.sent()
    return w


def texts_to(w, target):
    return [s.text for s in w.sent() if s.target == target]


# whois

def test_whois_without_labeled_response_matches_replies_by_nick(tmp_path):
    w = ready(tmp_path)
    w.join('mal')
    w.sent()
    assert 'WHOIS ana' in lines(w.message('mal', '!whois ana'))
    w.receive(*ANA)
    assert texts_to(w, '#test') == [ANA_REPLY]


def test_whois_with_labeled_response_takes_the_labeled_batch(tmp_path):
    w = ready(tmp_path, 'batch labeled-response')
    w.join('mal')
    w.sent()
    [request] = [s for s in w.message('mal', '!whois ana') if 'WHOIS' in s.line]
    assert request.line == '@label=ph1 WHOIS ana'
    # someone else's whois of ana, which isn't the bot's answer
    w.receive(':irc.example.net 311 pinbot ana x x.host * :Not this one')
    w.receive('@label=ph1 :irc.example.net BATCH +b1 labeled-response',
              *['@batch=b1 ' + line for line in ANA], ':irc.example.net BATCH -b1')
    assert texts_to(w, '#test') == [ANA_REPLY]


def test_whois_of_no_one_is_none(tmp_path):
    w = ready(tmp_path, 'batch labeled-response')
    w.join('mal')
    w.message('mal', '!whois ghost')
    w.receive('@label=ph1 :irc.example.net 401 pinbot ghost :No such nick')
    assert texts_to(w, '#test') == ['no ghost']


def test_whois_without_labels_of_no_one_is_none(tmp_path):
    w = ready(tmp_path)
    w.join('mal')
    w.message('mal', '!whois ghost')
    w.receive(':irc.example.net 401 pinbot ghost :No such nick',
              ':irc.example.net 318 pinbot ghost :End of /WHOIS list')
    assert texts_to(w, '#test') == ['no ghost']


def test_two_whois_of_one_nick_share_one_request(tmp_path):
    w = ready(tmp_path)
    w.join('mal')
    w.join('bob')
    sent = w.message('mal', '!whois ana') + w.message('bob', '!whois ana')
    assert [s.line for s in sent if s.command == 'WHOIS'] == ['WHOIS ana']
    w.receive(*ANA)
    assert texts_to(w, '#test') == [ANA_REPLY, ANA_REPLY]


def test_testbot_whois_knows_the_fake_channels(tmp_path):
    (tmp_path / 'plugin.py').write_text(PLUGIN)
    bot = TestBot(plugin_dir=str(tmp_path))
    bot.say('hi', nick='ana', account='anaacct')
    assert bot.say('!whois ana') == [
        'ana ana@example.com account=anaacct channels=#test away=None bot=False secure=False']
    assert bot.say('!whois ghost') == ['no ghost']


# netsplits and netjoins

def test_a_netsplit_is_one_event_and_forgets_who_left(tmp_path):
    w = ready(tmp_path, 'batch')
    w.receive(':ana!a@h JOIN #test', ':bob!b@h JOIN #test', ':cy!c@h JOIN #test')
    w.sent()
    w.receive(':irc.example.net BATCH +s1 netsplit hub.example.net leaf.example.net',
              '@batch=s1 :ana!a@h QUIT :hub.example.net leaf.example.net',
              '@batch=s1 :bob!b@h QUIT :hub.example.net leaf.example.net',
              ':irc.example.net BATCH -s1')
    assert texts_to(w, '#log') == ['split hub.example.net leaf.example.net ana bob']
    assert [m.nick for m in w.bot.transport.members('#test')] == ['pinbot', 'cy']


def test_a_netjoin_is_one_event_and_tracks_who_came_back(tmp_path):
    w = ready(tmp_path, 'batch')
    w.receive(':irc.example.net BATCH +j1 netjoin hub.example.net leaf.example.net',
              '@batch=j1 :ana!a@h JOIN #test', '@batch=j1 :bob!b@h JOIN #test',
              '@batch=j1 :bob!b@h JOIN #games',
              ':irc.example.net BATCH -j1')
    assert texts_to(w, '#log') == ['back hub.example.net leaf.example.net ana bob']
    assert [m.nick for m in w.bot.transport.members('#test')] == ['pinbot', 'ana', 'bob']


def test_other_batches_are_handled_line_by_line_when_they_end(tmp_path):
    w = ready(tmp_path, 'batch')
    w.receive(':irc.example.net BATCH +x1 example.org/other',
              '@batch=x1 :ana!a@h JOIN #test')
    assert texts_to(w, '#log') == []
    w.receive(':irc.example.net BATCH -x1')
    assert texts_to(w, '#log') == ['join ana']


def test_testbot_can_send_a_netsplit(tmp_path):
    (tmp_path / 'plugin.py').write_text(PLUGIN)
    bot = TestBot(plugin_dir=str(tmp_path))
    assert bot.event('netsplit', text='hub leaf', nicks=['ana', 'bob']) == [
        Sent('message', '#log', 'split hub leaf ana bob')]
