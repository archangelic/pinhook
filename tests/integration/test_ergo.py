"""pinhook against a real Ergo IRC server, started the way an owner would start it.

Each test runs the real pinhook command with a config file. See conftest.py for
how to run them.
"""
import hashlib
import json
import os
import shutil
import socket
import ssl
import time
import urllib.error
import urllib.request

from conftest import HOST, TLS_DIR, NickTaken, register

KARMA = ("import pinhook.plugin\n\n\n"
         "@pinhook.plugin.command('!karma')\n"
         "def karma(msg):\n"
         "    scores = msg.store.setdefault('scores', {})\n"
         "    scores[msg.arg] = scores.get(msg.arg, 0) + 1\n"
         "    label = msg.config.get('label', 'karma')\n"
         "    reply = '{} has {} {}'.format(msg.arg, scores[msg.arg], label)\n"
         "    return pinhook.plugin.message(reply)\n")
CONTEXT = ("import pinhook.plugin\n\n\n"
           "@pinhook.plugin.command('!ctx')\n"
           "def ctx(msg):\n"
           "    msg.reply('account={} private={}'.format(msg.account, msg.is_private))\n"
           "    msg.notice('psst')\n"
           "    msg.action('waves')\n\n\n"
           "@pinhook.plugin.command('!mods')\n"
           "def mods(msg):\n"
           "    return pinhook.plugin.message(', '.join(msg.config.shared['modteam']))\n\n\n"
           "@pinhook.plugin.command('!legacy')\n"
           "def legacy(msg):\n"
           "    return pinhook.plugin.message('old style: ' + msg.bot.bot_nick)\n")


def messages(replies):
    return [r[2] for r in replies if r[0] == 'PRIVMSG']


def test_plugins_use_store_config_and_the_new_reply_methods(names, accounts, users, start_bot):
    bot, channel = names
    mal = users('mallory', 'malacct', channel)
    start_bot(mal, plugins={'karma': KARMA, 'ctx': CONTEXT},
              plugin_config={'karma': {'label': 'points'}, 'shared': {'modteam': ['mallory']}})
    assert messages(mal.say('!karma pinhook', channel, bot)) == ['pinhook has 1 points']
    assert messages(mal.say('!karma pinhook', channel, bot)) == ['pinhook has 2 points']
    assert mal.say('!ctx', channel, bot) == [
        ('PRIVMSG', channel, 'account=malacct private=False'),
        ('NOTICE', 'mallory', 'psst'),
        ('ACTION', channel, 'waves')]
    assert ('PRIVMSG', 'mallory', 'account=malacct private=True') in mal.say('!ctx', bot, bot)
    # the replies so far used up the burst, so this one waits its turn
    assert messages(mal.say('!mods', channel, bot, seconds=6)) == ['mallory']


def test_msg_bot_still_works_and_warns_once(names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    running = start_bot(mal, plugins={'ctx': CONTEXT})
    for _ in range(2):
        assert messages(mal.say('!legacy', channel, bot)) == ['old style: ' + bot]
    assert running.log().count('msg.bot is deprecated') == 1


def test_reload_rereads_plugin_config_and_keeps_it_if_the_file_breaks(
        tmp_path, names, accounts, users, start_bot):
    bot, channel = names
    mal = users('mallory', 'malacct', channel)
    start_bot(mal, plugins={'karma': KARMA}, ops=['$a:malacct'],
              plugin_config={'karma': {'label': 'karma'}})
    assert messages(mal.say('!karma pinhook', channel, bot)) == ['pinhook has 1 karma']
    path = tmp_path / 'config.json'
    config = json.loads(path.read_text())
    config['plugin_config']['karma']['label'] = 'points'
    path.write_text(json.dumps(config))
    assert messages(mal.say('!reload', channel, bot)) == [
        'Plugins reloaded (and plugin_config and access from config.json)']
    assert messages(mal.say('!karma pinhook', channel, bot)) == ['pinhook has 2 points']
    path.write_text('{"nickname": ')
    assert messages(mal.say('!reload', channel, bot)) == [
        "Plugins reloaded, but config.json has a problem so plugin_config and access weren't "
        "changed, see the log"]
    assert messages(mal.say('!karma pinhook', channel, bot)) == ['pinhook has 3 points']


def test_account_ban_survives_a_nick_change_and_a_restart(names, accounts, users, start_bot):
    bot, channel = names
    mal = users('mallory', 'malacct', channel)
    troll = users('trolly', 'trollacct', channel)
    running = start_bot(mal, plugins={'karma': KARMA}, ops=['$a:malacct'])
    troll.say('hello', channel, bot)
    assert messages(mal.say('!ban trolly', channel, bot)) == [
        'mallory: banned trolly (account trollacct)']
    troll.send('NICK sneaky')
    troll.wait_for('NICK')
    assert troll.say('!karma me', channel, bot) == []
    running.stop()
    start_bot(mal, plugins={'karma': KARMA}, ops=['$a:malacct'])
    assert troll.say('!karma me', channel, bot) == []
    assert messages(mal.say('!karma pinhook', channel, bot)) == ['pinhook has 1 karma']


def test_store_survives_a_restart_and_files_stay_in_bot_dir(tmp_path, names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    running = start_bot(mal, plugins={'karma': KARMA})
    assert messages(mal.say('!karma pinhook', channel, bot)) == ['pinhook has 1 karma']
    running.stop()
    start_bot(mal, plugins={'karma': KARMA})
    assert messages(mal.say('!karma pinhook', channel, bot)) == ['pinhook has 2 karma']
    stored = json.loads((tmp_path / 'bot' / 'data' / 'karma.json').read_text())
    assert stored == {'scores': {'pinhook': 2}}
    assert sorted(os.listdir(tmp_path / 'bot')) == ['data', 'logs', 'plugins']
    assert os.listdir(tmp_path / 'run') == []


def test_sasl_gets_the_reserved_nick_and_logs_in(names, users, start_bot):
    bot, channel = names
    register(bot, 'botpassword')
    watcher = users('watcher', channel=channel)
    running = start_bot(watcher, sasl_password='${PH_BOT_PASSWORD}', ns_pass='${PH_BOT_PASSWORD}',
                        env={'PH_BOT_PASSWORD': 'botpassword'})
    watcher.send('WHOIS ' + bot)
    assert 'is logged in as' in watcher.wait_for(' 330 ')
    log = running.log()
    # ergo offers SCRAM-SHA-256, so the password never crossed the network
    assert 'logged in as {} with SASL SCRAM-SHA-256'.format(bot) in log
    assert 'in use' not in log and 'identifying with nickserv' not in log


def test_sasl_plain_still_works_when_chosen(names, users, start_bot):
    bot, channel = names
    register(bot, 'botpassword')
    watcher = users('watcher', channel=channel)
    running = start_bot(watcher, sasl_password='botpassword', sasl_mechanism='PLAIN')
    watcher.send('WHOIS ' + bot)
    assert 'is logged in as' in watcher.wait_for(' 330 ')
    assert 'logged in as {} with SASL PLAIN'.format(bot) in running.log()


def test_wrong_sasl_password_is_reported_and_the_bot_still_connects(names, users, start_bot):
    bot, channel = names
    register(bot, 'botpassword')
    watcher = users('watcher', channel=channel)
    running = start_bot(watcher, sasl_password='wrong-password')
    log = running.log()
    assert 'SASL login as {} failed'.format(bot) in log
    assert 'check sasl_account and sasl_password' in log


def test_nick_in_use_picks_a_new_one(names, users, start_bot):
    bot, channel = names
    users(bot)
    watcher = users('watcher', channel=channel)
    start_bot(watcher, plugins={'karma': KARMA})
    assert messages(watcher.say('!karma x', channel, bot + '_')) == ['x has 1 karma']


def test_bot_mode_is_set(names, users, start_bot):
    bot, channel = names
    watcher = users('watcher', channel=channel)
    start_bot(watcher)
    watcher.send('WHOIS ' + bot)
    # ergo puts the word Bot in bold
    assert 'is a Bot' in watcher.wait_for(' 335 ').replace('\x02', '')


def test_self_signed_certificate_is_refused_with_advice(names, users, start_bot, tmp_path):
    bot, channel = names
    watcher = users('watcher', channel=channel)
    running = start_bot(watcher, wait=False, port=6697, ssl_required=True)
    deadline = time.time() + 10
    while time.time() < deadline and 'set ssl_verify to false' not in running.log():
        time.sleep(0.2)
    assert "couldn't connect to {}:6697".format(HOST) in running.log()
    assert 'set ssl_verify to false' in running.log()


def test_ssl_verify_false_connects_to_a_self_signed_server(names, users, start_bot):
    bot, channel = names
    watcher = users('watcher', channel=channel)
    start_bot(watcher, plugins={'karma': KARMA}, port=6697, ssl_required=True, ssl_verify=False)
    assert messages(watcher.say('!karma ssl', channel, bot)) == ['ssl has 1 karma']


def test_missing_environment_variable_stops_the_bot(names, users, start_bot):
    bot, channel = names
    watcher = users('watcher', channel=channel)
    running = start_bot(watcher, wait=False, ns_pass='${PH_NOT_SET}')
    running.process.wait(timeout=10)
    assert running.process.returncode != 0
    assert "uses ${PH_NOT_SET}, but that environment variable isn't set" in \
        running.process.stderr.read().decode()


def test_sigterm_quits_cleanly(names, users, start_bot):
    bot, channel = names
    watcher = users('watcher', channel=channel)
    running = start_bot(watcher)
    running.process.terminate()
    assert running.process.wait(timeout=10) == 0
    quit_line = watcher.wait_for(' QUIT ')
    assert quit_line.startswith(':' + bot) and "See y'all later!" in quit_line


def test_quit_command_ends_the_process(names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    running = start_bot(mal, ops=['mallory'])
    mal.send('PRIVMSG {} :!quit bye'.format(channel))
    assert running.process.wait(timeout=10) == 0
    assert mal.wait_for(' QUIT ').endswith('bye')


def test_long_replies_are_paced_and_all_arrive(names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    start_bot(mal, plugins={'lines': (
        "import pinhook.plugin\n\n\n"
        "@pinhook.plugin.command('!lines')\n"
        "def lines(msg):\n"
        "    return pinhook.plugin.message([str(i) for i in range(6)])\n")})
    started = time.time()
    assert messages(mal.say('!lines', channel, bot, seconds=6)) == [str(i) for i in range(6)]
    assert time.time() - started >= 4


def test_long_replies_are_split_and_arrive_whole(names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    start_bot(mal, plugins={'long': (
        "import pinhook.plugin\n\n\n"
        "@pinhook.plugin.command('!long')\n"
        "def long(msg):\n"
        "    return pinhook.plugin.message(' '.join('word{}'.format(i) for i in range(250)))\n")})
    got = messages(mal.say('!long', channel, bot))
    assert len(got) > 1
    assert ' '.join(got) == ' '.join('word{}'.format(i) for i in range(250))


NATIVE = ("from pinhook import Plugin, command, on\n\n\n"
          "class Dice(Plugin):\n"
          "    def setup(self, previous):\n"
          "        self.rolls = previous.rolls if previous else 0\n\n"
          "    @command('roll')\n"
          "    async def roll(self, ctx, sides: int = 6):\n"
          "        self.rolls += 1\n"
          "        await ctx.reply(f'{ctx.nick} rolled a d{sides}, roll {self.rolls}')\n\n"
          "    @on('join')\n"
          "    async def hello(self, ctx):\n"
          "        await ctx.notice(ctx.nick, f'welcome to {ctx.channel}')\n")


def test_a_2_0_plugin_with_typed_commands_and_events(names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    start_bot(mal, plugins={'dice': NATIVE}, ops=['mallory'])
    assert messages(mal.say('!roll 20', channel, bot)) == ['mallory rolled a d20, roll 1']
    assert messages(mal.say('!roll twenty', channel, bot)) == [
        'usage: roll [sides=6] (sides must be a whole number)']
    assert messages(mal.say('!reload', channel, bot))[0].startswith('Plugins reloaded')
    assert messages(mal.say('!roll', channel, bot)) == ['mallory rolled a d6, roll 2']
    ana = users('anabot', channel=channel)
    assert 'welcome to ' + channel in ana.wait_for('NOTICE anabot')


MEMBERS = '''
from pinhook import command


@command('members')
async def members(ctx):
    people = sorted((m for m in ctx.members() if m.nick != ctx.bot.nick), key=lambda m: m.nick)
    await ctx.reply(' '.join('{}={}/{}'.format(m.nick, m.account or '-',
                                               ''.join(sorted(m.modes)) or '-')
                             for m in people))


@command('me')
async def me(ctx):
    await ctx.reply('chanop={} account={}'.format(ctx.is_chanop, ctx.account))
'''


def test_members_are_tracked_with_accounts_and_modes(names, accounts, users, start_bot):
    bot, channel = names
    # the first to join is made an op
    mal = users('mallory', 'malacct', channel)
    start_bot(mal, plugins={'members': MEMBERS})
    assert messages(mal.say('!members', channel, bot)) == ['mallory=malacct/o']
    assert messages(mal.say('!me', channel, bot)) == ['chanop=True account=malacct']
    troll = users('trolly', 'trollacct', channel)
    assert messages(mal.say('!members', channel, bot)) == [
        'mallory=malacct/o trolly=trollacct/-']
    troll.send('PART ' + channel)
    assert messages(mal.say('!members', channel, bot)) == ['mallory=malacct/o']


DETAILS = '''
from pinhook import command


@command('when')
async def when(ctx):
    await ctx.reply('time={} msgid={} tagged={}'.format(
        ctx.time.tzinfo is not None, ctx.msgid is not None, 'time' in ctx.tags))
'''


def test_server_time_and_message_ids_come_from_the_server(names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    start_bot(mal, plugins={'details': DETAILS})
    assert messages(mal.say('!when', channel, bot)) == ['time=True msgid=True tagged=True']


WHOIS = '''
from pinhook import command


@command('whois')
async def whois(ctx, nick: str):
    info = await ctx.whois(nick)
    if info is None:
        await ctx.reply('no ' + nick)
    else:
        await ctx.reply('{} account={} in={}'.format(info.nick, info.account,
                                                    channel_in(info, ctx.channel)))


def channel_in(info, channel):
    return channel in info.channels
'''


def test_whois_asks_the_server(names, accounts, users, start_bot):
    bot, channel = names
    mal = users('mallory', 'malacct', channel)
    start_bot(mal, plugins={'whois': WHOIS})
    assert messages(mal.say('!whois mallory', channel, bot)) == [
        'mallory account=malacct in=True']
    assert messages(mal.say('!whois nobodyhere', channel, bot)) == ['no nobodyhere']


THREAD = '''
from pinhook import command


@command('thread')
async def thread(ctx):
    await ctx.reply('threaded', thread=True)
'''


def test_threaded_replies_carry_the_reply_tag(names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    start_bot(mal, plugins={'thread': THREAD})
    mal.send('CAP REQ message-tags')
    mal.wait_for('ACK')
    mal.send('PRIVMSG {} :!thread'.format(channel))
    # the reply comes back tagged with the msgid ergo gave mallory's message
    line = mal.wait_for(':threaded')
    assert '+reply=' in line and line.split(' ', 1)[1].startswith(':' + bot + '!')


HISTORY = '''
from pinhook import command


@command('recent')
async def recent(ctx):
    await ctx.reply(' | '.join('{}{}:{}'.format('*' if e.own else '', e.nick, e.text)
                               for e in ctx.history()))


@command('say')
async def say(ctx, text: str):
    await ctx.reply(text)
'''


def test_history_keeps_both_sides_through_echo_message(names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    start_bot(mal, plugins={'history': HISTORY}, history={'channels': [channel]})
    assert messages(mal.say('!say hello', channel, bot)) == ['hello']
    assert messages(mal.say('!recent', channel, bot)) == [
        'mallory:!say hello | *{}:hello | mallory:!recent'.format(bot)]


QUOTES = '''
from pinhook import command


@command('quote')
async def quote(ctx, topic: str = 'any'):
    await ctx.reply('Blades in the Dark' if topic == 'games' else 'a quote')
'''

GAMENIGHT = '''version: 1
help: pick tonight's game
steps:
  - command: 'quote games'
    save: game
  - store: nights
    add: '{game}'
  - reply: 'Tonight: {game}, night {store.nights|count}'
'''


def test_recipes_run_as_commands(tmp_path, names, users, start_bot):
    bot, channel = names
    (tmp_path / 'bot' / 'recipes').mkdir(parents=True)
    (tmp_path / 'bot' / 'recipes' / 'gamenight.yaml').write_text(GAMENIGHT)
    mal = users('mallory', channel=channel)
    start_bot(mal, plugins={'quotes': QUOTES})
    assert messages(mal.say('!gamenight', channel, bot)) == ['Tonight: Blades in the Dark, night 1']
    assert messages(mal.say('!gamenight', channel, bot)) == ['Tonight: Blades in the Dark, night 2']


def test_ops_add_and_remove_recipes_from_chat(tmp_path, names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    start_bot(mal, ops=['mallory'])
    assert messages(mal.say('!recipe add hug {nick} hugs {arg|default:everyone}', channel,
                            bot)) == ['mallory: added !hug']
    assert messages(mal.say('!hug', channel, bot)) == ['mallory hugs everyone']
    assert (tmp_path / 'bot' / 'recipes' / 'hug.yaml').exists()
    assert messages(mal.say('!recipe del hug', channel, bot)) == ['mallory: removed !hug']
    assert messages(mal.say('!hug', channel, bot)) == []


def test_sts_moves_the_bot_to_tls_and_is_remembered(tmp_path, names, users, start_bot):
    bot, channel = names
    watcher = users('watcher', channel=channel, port=6668)
    # the bot connects without TLS, and the server's STS policy sends it to 6698
    start_bot(watcher, port=6668, env={'SSL_CERT_FILE': os.path.join(TLS_DIR, 'ca.pem')})
    watcher.send('WHOIS ' + bot)
    assert 'secure connection' in watcher.wait_for(' 671 ')
    policies = json.loads((tmp_path / 'bot' / 'data' / 'sts.json').read_text())
    assert policies[HOST]['port'] == 6698
    assert policies[HOST]['expires'] > time.time()


def test_sasl_external_logs_in_with_a_client_certificate(names, users, start_bot):
    bot, channel = names
    with open(os.path.join(TLS_DIR, 'client.pem')) as f:
        fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(f.read())).hexdigest()
    # an account with the client certificate added to it. A certificate belongs to one
    # account, and the server keeps its accounts while it runs, so every run uses this one
    try:
        owner = users('pinhookcert', port=6668)
        owner.send('PRIVMSG NickServ :REGISTER botpassword')
        owner.wait_for('NickServ')
    except NickTaken:
        # an earlier run registered it, and the account holds the nick
        owner = users(bot + 'o', port=6668)
    owner.send('PRIVMSG NickServ :IDENTIFY pinhookcert botpassword')
    owner.wait_for('NickServ')
    owner.send('PRIVMSG NickServ :CERT ADD ' + fingerprint)
    owner.wait_for('NickServ')
    owner.close()
    watcher = users('watcher', channel=channel, port=6668)
    running = start_bot(watcher, port=6698, ssl_required=True,
                        ssl_certfile=os.path.join(TLS_DIR, 'client.pem'),
                        ssl_keyfile=os.path.join(TLS_DIR, 'client.key'),
                        env={'SSL_CERT_FILE': os.path.join(TLS_DIR, 'ca.pem')})
    watcher.send('WHOIS ' + bot)
    assert 'pinhookcert :is logged in as' in watcher.wait_for(' 330 ')
    assert 'logged in as pinhookcert with SASL EXTERNAL' in running.log()


def free_port():
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_the_health_endpoint_says_when_the_bot_is_ready(names, users, start_bot):
    bot, channel = names
    port = free_port()
    watcher = users('watcher', channel=channel)
    start_bot(watcher, health_port=port)
    base = 'http://{}:{}'.format(HOST, port)
    assert get(base + '/healthz') == (200, 'ok\n')
    # the join reaches the watcher at about the moment the bot sees it
    end = time.time() + 10
    while get(base + '/readyz') != (200, 'ready\n') and time.time() < end:
        time.sleep(0.1)
    assert get(base + '/readyz') == (200, 'ready\n')
    watcher.send('KICK {} {} :out'.format(channel, bot))
    watcher.wait_for(' KICK ')
    end = time.time() + 10
    while get(base + '/readyz')[0] != 503 and time.time() < end:
        time.sleep(0.1)
    assert get(base + '/readyz') == (503, 'not in {}\n'.format(channel))


# one case for each IRCv3 capability the raw-line tests cover, against a real server

def test_monitor_wins_the_bots_nick_back(names, users, start_bot):
    bot, channel = names
    holder = users(bot)
    watcher = users('watcher', channel=channel)
    start_bot(watcher)
    holder.close()
    line = watcher.wait_for(' NICK ')
    assert line.startswith(':{}_!'.format(bot)) and line.endswith(bot)


INVITES = '''
from pinhook import on


@on('invite')
async def invited(ctx):
    await ctx.send(ctx.channel, 'invited {} by {}'.format(ctx.invited, ctx.nick))
'''


def test_invite_notify_reports_invites_to_the_bots_channels(names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    start_bot(mal, plugins={'invites': INVITES})
    # ergo tells a channel's operators who was invited
    mal.send('MODE {} +o {}'.format(channel, bot))
    mal.wait_for(' MODE ')
    users('guesty')
    mal.send('INVITE guesty {}'.format(channel))
    assert mal.wait_for('invited ').endswith('invited guesty by mallory')


MEMBER = '''
from pinhook import command


@command('who')
async def who(ctx, nick: str):
    m = ctx.member(nick)
    await ctx.reply('{} away={} realname={} modes={}'.format(
        m.nick, m.away, m.realname, ''.join(sorted(m.modes))))
'''


def test_away_setname_and_multi_prefix_keep_members_current(names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    ana = users('anaa', channel=channel)
    start_bot(mal, plugins={'member': MEMBER})
    mal.send('MODE {} +ov anaa anaa'.format(channel))
    mal.wait_for(' MODE ')
    ana.send('AWAY :brb')
    ana.send('CAP REQ setname')
    ana.wait_for('ACK')
    ana.send('SETNAME :Ana Real')
    ana.wait_for('SETNAME')
    time.sleep(0.3)
    assert messages(mal.say('!who anaa', channel, bot)) == [
        'anaa away=True realname=Ana Real modes=ov']


PRIVATE = '''
import asyncio

from pinhook import command


@command('psst')
async def psst(ctx):
    await ctx.reply('just you', private=True)


@command('slow')
async def slow(ctx):
    async with ctx.typing():
        await asyncio.sleep(0.3)
    await ctx.reply('done')


@command('broken')
async def broken(ctx):
    await ctx.reply('caf\\u00e9 \\udc80')
'''


def test_a_private_reply_carries_its_channel(names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    start_bot(mal, plugins={'private': PRIVATE})
    mal.send('CAP REQ message-tags')
    mal.wait_for('ACK')
    mal.send('PRIVMSG {} :!psst'.format(channel))
    line = mal.wait_for(':just you')
    assert '+channel-context={}'.format(channel) in line
    assert ' PRIVMSG mallory ' in line


def test_typing_is_shown_while_a_command_works(names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    start_bot(mal, plugins={'private': PRIVATE})
    mal.send('CAP REQ message-tags')
    mal.wait_for('ACK')
    mal.send('PRIVMSG {} :!slow'.format(channel))
    mal.read(1.5)
    typing = [line.split(';+typing=')[1].split(' ')[0] for line in mal.lines
              if ' TAGMSG ' in line and '+typing=' in line]
    assert typing == ['active', 'done']
    assert any(line.endswith(':done') for line in mal.lines)


def test_text_the_server_would_refuse_arrives_as_valid_utf8(names, users, start_bot):
    bot, channel = names
    mal = users('mallory', channel=channel)
    start_bot(mal, plugins={'private': PRIVATE})
    assert messages(mal.say('!broken', channel, bot)) == ['café ?']


def test_a_1_12_bot_folder_runs_on_2_0(tmp_path, names, users, start_bot):
    # data written by 1.12's own code: a karma store and a ban file
    fixture = os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'bot-1.12')
    shutil.copytree(os.path.join(fixture, 'data'), tmp_path / 'bot' / 'data')
    (tmp_path / 'bot' / 'plugins').mkdir(parents=True)
    shutil.copy(os.path.join(fixture, 'plugins', 'karma.py'), tmp_path / 'bot' / 'plugins')
    bot, channel = names
    mal = users('mallory', channel=channel)
    start_bot(mal, ban_file='data/oldbot.bans.json',
              plugin_config={'karma': {'label': 'points'}})
    assert messages(mal.say('!karma ana', channel, bot)) == ['ana has 4 points']
    saved = json.loads((tmp_path / 'bot' / 'data' / 'karma.json').read_text())
    assert saved == {'scores': {'ana': 4, 'bob': 1}}


def test_the_showcase_bot_runs_on_a_real_server(tmp_path, names, users, start_bot):
    # tests/fixtures/showcase: every plugin feature, 1.x and 2.0, and recipes
    showcase = os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'showcase')
    for folder in ('plugins', 'recipes'):
        shutil.copytree(os.path.join(showcase, folder), tmp_path / 'bot' / folder)
    bot, channel = names
    mal = users('mallory', channel=channel)
    start_bot(mal, ops=['mallory'],
              plugin_config={'legacy_tour': {'word': 'legacy'}, 'modern_tour': {'word': 'modern'}})
    assert messages(mal.say('!legacy', channel, bot)) == ['hello mallory from 1.x']
    assert messages(mal.say('ping legacy', channel, bot)) == ['pong from a 1.x listener']
    assert messages(mal.say('!r 2 20', channel, bot)) == ['mallory rolled 2d20']
    assert messages(mal.say('!types hi 3 1.5 yes b 7 the rest', channel, bot)) == [
        'hi 3 1.5 True b 7 the rest']
    assert messages(mal.say('!count', channel, bot)) == ['counted 1 with modern']
    assert messages(mal.say('!gamenight', channel, bot))[0].startswith(
        'Tonight: mallory rolled 2d6. ')
    assert messages(mal.say('!reload', channel, bot))[0].startswith('Plugins reloaded')
    assert messages(mal.say('!reloads', channel, bot)) == ['reloaded 1 times']
