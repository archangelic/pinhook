"""The bot's side of the IRC protocol, checked with raw lines in and out.

These only look at IRC lines, so they check the bot however its transport is
written underneath, see wire.py.
"""
import socket
import ssl

import pytest

from pinhook import bot as pinhook_bot

from wire import Wire, b64_login, lines

PING = ("import pinhook.plugin as p\n"
        "@p.command('!ping')\n"
        "def ping(msg): return p.message('pong')\n")
WHOAMI = ("import pinhook.plugin as p\n"
          "@p.command('!whoami')\n"
          "def whoami(msg): return p.message(msg.botnick)\n")
ECHO = ("import pinhook.plugin as p\n"
        "@p.listener('echo')\n"
        "def echo(msg): return p.message(msg.text)\n")


# connecting and capabilities

def test_capabilities_are_asked_for_before_nick_and_user(tmp_path):
    w = Wire(tmp_path)
    assert lines(w.connect()) == ['CAP LS 302', 'NICK pinbot', 'USER pinbot 0 * pinbot']


def test_account_tags_are_requested_and_negotiation_ends(tmp_path):
    w = Wire(tmp_path)
    w.connect()
    # a * means the list carries on in another line
    w.receive(':irc.example.net CAP * LS * :multi-prefix away-notify')
    assert lines(w.sent()) == []
    w.receive(':irc.example.net CAP * LS :account-tag chghost')
    assert lines(w.sent()) == ['CAP REQ account-tag']
    w.receive(':irc.example.net CAP * ACK :account-tag')
    assert lines(w.sent()) == ['CAP END']
    assert w.bot.account_tag


def test_negotiation_ends_when_server_lacks_account_tags(tmp_path):
    w = Wire(tmp_path)
    w.connect()
    w.receive(':irc.example.net CAP * LS :multi-prefix')
    assert lines(w.sent()) == ['CAP END']
    assert not w.bot.account_tag


def test_a_refused_request_still_ends_negotiation(tmp_path):
    w = Wire(tmp_path)
    w.connect()
    w.receive(':irc.example.net CAP * LS :account-tag')
    w.receive(':irc.example.net CAP * NAK :account-tag')
    assert lines(w.sent()) == ['CAP REQ account-tag', 'CAP END']
    assert not w.bot.account_tag


def test_cap_replies_after_registering_are_left_alone(tmp_path):
    # e.g. TwitchBot asking for its own capabilities after connecting
    w = Wire(tmp_path).ready()
    w.receive(':irc.example.net CAP pinbot ACK :twitch.tv/tags')
    assert lines(w.sent()) == []


def test_account_tags_reach_plugins(tmp_path):
    w = Wire(tmp_path, plugins={'who': (
        "import pinhook.plugin as p\n"
        "@p.command('!who')\n"
        "def who(msg): return p.message(str(msg.account))\n")}).ready()
    assert w.say('!who', nick='mal', account='malacct') == ['malacct']
    assert w.say('!who', nick='guest') == ['None']


# sasl

def sasl_bot(tmp_path, **options):
    w = Wire(tmp_path, **options)
    w.connect()
    return w


def test_sasl_logs_in_before_registering(tmp_path):
    w = sasl_bot(tmp_path, sasl_password='hunter2', sasl_account='pinbotacct')
    w.receive(':irc.example.net CAP * LS :account-tag sasl=PLAIN,EXTERNAL')
    assert lines(w.sent()) == ['CAP REQ account-tag sasl']
    w.receive(':irc.example.net CAP * ACK :account-tag sasl')
    assert lines(w.sent()) == ['AUTHENTICATE PLAIN']
    w.receive('AUTHENTICATE +')
    assert b64_login(w.sent()) == '\0pinbotacct\0hunter2'
    w.receive(':irc.example.net 900 pinbot pinbot!pinbot@host pinbotacct :You are now logged in',
              ':irc.example.net 903 pinbot :SASL authentication successful')
    # registration only carries on once the login is done
    assert lines(w.sent()) == ['CAP END']
    assert w.bot.sasl_logged_in
    assert w.bot.account_tag


def test_sasl_account_defaults_to_the_nickname(tmp_path):
    w = sasl_bot(tmp_path, sasl_password='hunter2')
    w.receive(':irc.example.net CAP * LS :sasl', ':irc.example.net CAP * ACK :sasl',
              'AUTHENTICATE +')
    assert b64_login(w.sent()) == '\0pinbot\0hunter2'


def test_long_logins_are_sent_in_400_byte_pieces(tmp_path):
    # this password makes the encoded login exactly 800 bytes, so it ends with a +
    password = 'x' * (600 - len('\0pinbot\0'))
    w = sasl_bot(tmp_path, sasl_password=password)
    w.receive(':irc.example.net CAP * LS :sasl', ':irc.example.net CAP * ACK :sasl')
    w.sent()
    w.receive('AUTHENTICATE +')
    sent = w.sent()
    assert [len(s.params[0]) for s in sent] == [400, 400, 1]
    assert sent[-1].line == 'AUTHENTICATE +'
    assert b64_login(sent) == '\0pinbot\0' + password


def test_failed_sasl_login_carries_on_and_says_why(tmp_path, caplog):
    w = sasl_bot(tmp_path, sasl_password='wrong')
    w.receive(':irc.example.net CAP * LS :sasl', ':irc.example.net CAP * ACK :sasl',
              'AUTHENTICATE +')
    w.sent()
    w.receive(':irc.example.net 904 pinbot :SASL authentication failed')
    assert lines(w.sent()) == ['CAP END']
    assert not w.bot.sasl_logged_in
    assert ('SASL login as pinbot failed (SASL authentication failed), '
            'check sasl_account and sasl_password') in caplog.text


@pytest.mark.parametrize('ls', ['account-tag', 'sasl=EXTERNAL'])
def test_server_without_sasl_plain_is_reported(tmp_path, caplog, ls):
    w = sasl_bot(tmp_path, sasl_password='hunter2')
    w.receive(':irc.example.net CAP * LS :' + ls)
    assert 'AUTHENTICATE PLAIN' not in lines(w.sent())
    assert "this server doesn't offer SASL PLAIN logins" in caplog.text


def test_no_sasl_password_means_no_sasl(tmp_path):
    w = sasl_bot(tmp_path)
    w.receive(':irc.example.net CAP * LS :account-tag sasl')
    assert lines(w.sent()) == ['CAP REQ account-tag']


def sasl_then_welcome(tmp_path, result):
    w = sasl_bot(tmp_path, sasl_password='hunter2', ns_pass='hunter2')
    w.receive(':irc.example.net CAP * LS :sasl', ':irc.example.net CAP * ACK :sasl',
              'AUTHENTICATE +', ':irc.example.net {} pinbot :SASL'.format(result))
    return w.welcome()


def test_nickserv_is_skipped_after_a_sasl_login(tmp_path):
    assert 'PRIVMSG NickServ identify hunter2' not in lines(sasl_then_welcome(tmp_path, 903))


def test_nickserv_is_the_fallback_when_sasl_fails(tmp_path):
    assert 'PRIVMSG NickServ identify hunter2' in lines(sasl_then_welcome(tmp_path, 904))


# registering

def test_nickserv_and_channels_after_welcome(tmp_path):
    w = Wire(tmp_path, channels=['#test', '#keyed secret'], ns_pass='hunter2')
    w.connect()
    w.receive(':irc.example.net 001 pinbot :Welcome')
    assert lines(w.sent()) == ['PRIVMSG NickServ identify hunter2', 'JOIN #test',
                               'JOIN #keyed secret']


def test_require_account_warns_when_server_has_no_account_tags(tmp_path, caplog):
    w = Wire(tmp_path, require_account=True)
    w.connect()
    w.receive(':irc.example.net CAP * LS :multi-prefix')
    w.welcome()
    assert 'require_account is on but this server' in caplog.text


@pytest.mark.parametrize('isupport, mode', [('BOT=B', '+B'), ('BOT=b', '+b')])
def test_bot_mode_uses_the_servers_letter(tmp_path, isupport, mode):
    w = Wire(tmp_path)
    w.connect()
    assert 'MODE pinbot ' + mode in lines(w.welcome(isupport='CHANTYPES=# ' + isupport))


def test_no_bot_mode_when_server_has_none(tmp_path):
    w = Wire(tmp_path)
    w.connect()
    assert not [s for s in w.welcome(isupport='CHANTYPES=# NETWORK=Libera.Chat')
                if s.command == 'MODE']


def test_bot_mode_can_be_turned_off(tmp_path):
    w = Wire(tmp_path, bot_mode=False)
    w.connect()
    assert not [s for s in w.welcome(isupport='BOT=B') if s.command == 'MODE']


# nicknames

def test_taken_nick_is_retried_with_underscores(tmp_path, caplog):
    w = Wire(tmp_path)
    w.connect()
    w.receive(':irc.example.net 433 * pinbot :Nickname is already in use')
    assert lines(w.sent()) == ['NICK pinbot_']
    # the bot's nick isn't changed until the server accepts one
    w.receive(':irc.example.net 433 * pinbot_ :Nickname is already in use')
    assert lines(w.sent()) == ['NICK pinbot__']
    assert 'nickname pinbot in use, trying pinbot_' in caplog.text


def test_failed_nick_change_after_registering_keeps_the_nick(tmp_path):
    w = Wire(tmp_path).ready()
    w.receive(':irc.example.net 433 pinbot othernick :Nickname is already in use')
    assert lines(w.sent()) == []


@pytest.mark.parametrize('nick', ['pinbot', 'PinBot'])
def test_bot_ignores_its_own_nick(tmp_path, nick):
    w = Wire(tmp_path, plugins={'echo': ECHO}).ready()
    assert w.say('hello', nick=nick) == []


def test_bot_ignores_its_own_nick_after_a_nick_change(tmp_path):
    w = Wire(tmp_path, plugins={'echo': ECHO, 'whoami': WHOAMI}).ready()
    w.receive(':pinbot!pinbot@example.com NICK pinbot_')
    assert w.say('hello', nick='pinbot_') == []
    # and plugins see the new nick
    assert w.say('!whoami') == ['pinbot_']


def test_private_messages_reply_to_the_sender(tmp_path):
    w = Wire(tmp_path, plugins={'ping': PING}).ready()
    assert lines(w.message('mal', '!ping', target='pinbot')) == ['PRIVMSG mal pong']


def test_private_messages_after_a_nick_change(tmp_path):
    w = Wire(tmp_path, plugins={'ping': PING}).ready()
    w.receive(':pinbot!pinbot@example.com NICK pinbot_')
    assert lines(w.message('mal', '!ping', target='pinbot_')) == ['PRIVMSG mal pong']


def test_actions_reach_listeners(tmp_path):
    w = Wire(tmp_path, plugins={'echo': ECHO}).ready()
    assert lines(w.message('mal', 'dances', action=True)) == ['PRIVMSG #test dances']


def test_quit_sends_quit_and_stops(tmp_path):
    w = Wire(tmp_path, plugins={'ping': PING}, ops=['mal']).ready()
    with pytest.raises(SystemExit):
        w.message('mal', '!quit bye')
    assert 'QUIT bye' in lines(w.sent())


# connection failures

def cert_error(code, message):
    e = ssl.SSLCertVerificationError(message)
    e.verify_code, e.verify_message = code, message
    return e


@pytest.mark.parametrize('error, advice', [
    (cert_error(20, 'unable to get local issuer certificate'), 'set ssl_verify to false'),
    (cert_error(62, 'Hostname mismatch'), 'name the certificate was issued for'),
    (cert_error(10, 'certificate has expired'), 'needs fixing on the server'),
    (ssl.SSLError('wrong version number'), "Check 6667 is the server's ssl port"),
    (socket.gaierror(8, 'nodename nor servname provided'), 'server name not found'),
    (ConnectionRefusedError(61, 'Connection refused'),
     'connection refused, check the server and port'),
])
def test_connection_failures_are_explained(tmp_path, caplog, error, advice):
    Wire(tmp_path).connect_fails(error)
    assert "couldn't connect to irc.example.net:6667" in caplog.text
    assert advice in caplog.text
    assert 'will keep retrying' in caplog.text


def test_name_mismatch_does_not_suggest_turning_checks_off(tmp_path, caplog):
    Wire(tmp_path).connect_fails(cert_error(62, 'Hostname mismatch'))
    assert 'ssl_verify' not in caplog.text


# ssl settings

def test_ssl_checks_certificates_by_default(tmp_path):
    context = Wire(tmp_path, ssl_required=True).bot.ssl_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname


def test_ssl_verify_can_be_turned_off(tmp_path):
    context = Wire(tmp_path, ssl_required=True, ssl_verify=False).bot.ssl_context()
    assert context.verify_mode == ssl.CERT_NONE
    assert not context.check_hostname


def test_twitch_bot_always_uses_checked_tls(tmp_path):
    b = pinhook_bot.TwitchBot('pinbot', '#chan', 'secret', plugin_dir=str(tmp_path / 'p'),
                              log_file=str(tmp_path / 't.log'))
    assert (b.server, b.port) == ('irc.chat.twitch.tv', 6697)
    assert b.ssl_context().verify_mode == ssl.CERT_REQUIRED


def test_sasl_without_ssl_warns(tmp_path, caplog):
    Wire(tmp_path, sasl_password='hunter2')
    assert 'sasl_password will be sent without ssl' in caplog.text
