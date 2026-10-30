"""pinhook against a real Ergo IRC server, started the way an owner would start it.

Each test runs the real pinhook command with a config file. See conftest.py for
how to run them.
"""
import json
import os
import time

from conftest import HOST, register

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
        'Plugins reloaded (and plugin_config from config.json)']
    assert messages(mal.say('!karma pinhook', channel, bot)) == ['pinhook has 2 points']
    path.write_text('{"nickname": ')
    assert messages(mal.say('!reload', channel, bot)) == [
        "Plugins reloaded, but config.json has a problem so plugin_config wasn't changed, "
        "see the log"]
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
    assert 'logged in as {} with SASL'.format(bot) in log
    assert 'in use' not in log and 'identifying with nickserv' not in log


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
