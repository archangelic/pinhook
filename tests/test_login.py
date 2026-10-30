"""Logging in and staying connected: SASL SCRAM-SHA-256 and EXTERNAL, STS, and MONITOR."""
import base64
import functools
import json
import ssl
import time

import pytest

from pinhook.transport import sasl

from wire import Wire, lines

# RFC 7677's example login, for user "user" with password "pencil"
NONCE = 'rOprNGfwEbeRWgbNEkqO'
SERVER_FIRST = ('r=rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0,'
                's=W22ZaJ0SNY7soEsUEjb6gQ==,i=4096')
CLIENT_FINAL = ('c=biws,r=rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0,'
                'p=dHzbZapWIk4jUhN+Ute9ytag9zjfMHgsqmmiz7AndVQ=')
SERVER_FINAL = 'v=6rriTRBi23WpRR/wtup+mMhUZUn/dB5nLTJRsjl95G4='


def b64(text):
    return base64.b64encode(text.encode()).decode()


def unb64(sent):
    # an answer can come in several 400 byte AUTHENTICATE lines
    return base64.b64decode(''.join(s.params[0] for s in sent if s.params[0] != '+')).decode()


def login_bot(tmp_path, offered, **options):
    w = Wire(tmp_path, **options)
    w.connect()
    w.receive(':irc.example.net CAP * LS :' + offered)
    w.sent()
    w.receive(':irc.example.net CAP * ACK :sasl')
    return w


# SCRAM-SHA-256

def test_scram_is_used_when_offered_and_proves_the_password(tmp_path, monkeypatch):
    monkeypatch.setattr(sasl, 'ScramSha256', functools.partial(sasl.ScramSha256, nonce=NONCE))
    w = login_bot(tmp_path, 'sasl=PLAIN,SCRAM-SHA-256', sasl_account='user',
                  sasl_password='pencil')
    assert lines(w.sent()) == ['AUTHENTICATE SCRAM-SHA-256']
    w.receive('AUTHENTICATE +')
    assert unb64(w.sent()) == 'n,,n=user,r=' + NONCE
    w.receive('AUTHENTICATE ' + b64(SERVER_FIRST))
    # the password itself never goes to the server, only a proof of it
    assert unb64(w.sent()) == CLIENT_FINAL
    w.receive('AUTHENTICATE ' + b64(SERVER_FINAL))
    assert lines(w.sent()) == ['AUTHENTICATE +']
    w.receive(':irc.example.net 903 pinbot :SASL authentication successful')
    assert lines(w.sent()) == ['CAP END']
    assert w.bot.sasl_logged_in


def test_a_server_that_doesnt_know_the_password_is_refused(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(sasl, 'ScramSha256', functools.partial(sasl.ScramSha256, nonce=NONCE))
    w = login_bot(tmp_path, 'sasl=SCRAM-SHA-256', sasl_account='user', sasl_password='pencil')
    w.receive('AUTHENTICATE +', 'AUTHENTICATE ' + b64(SERVER_FIRST))
    w.sent()
    w.receive('AUTHENTICATE ' + b64('v=' + b64('not the right signature')))
    assert lines(w.sent()) == ['AUTHENTICATE *']
    assert "the server's SCRAM signature is wrong" in caplog.text
    w.receive(':irc.example.net 906 pinbot :SASL authentication aborted')
    assert lines(w.sent()) == ['CAP END']
    assert not w.bot.sasl_logged_in


def test_challenges_longer_than_400_bytes_are_put_back_together(tmp_path):
    login = sasl.ScramSha256('user', 'pencil', nonce=NONCE)
    login.respond(b'')
    first = 'r=' + NONCE + 'x' * 400 + ',s=W22ZaJ0SNY7soEsUEjb6gQ==,i=4096'
    w = login_bot(tmp_path, 'sasl=SCRAM-SHA-256', sasl_password='pencil')
    w.bot.transport.sasl = login
    w.sent()
    encoded = b64(first)
    w.receive(*['AUTHENTICATE ' + encoded[i:i + 400] for i in range(0, len(encoded), 400)])
    assert unb64(w.sent()).startswith('c=biws,r=' + NONCE + 'x' * 400)


def test_plain_is_used_when_the_server_doesnt_list_scram(tmp_path):
    w = login_bot(tmp_path, 'sasl=PLAIN,EXTERNAL', sasl_password='hunter2')
    assert lines(w.sent()) == ['AUTHENTICATE PLAIN']


def test_sasl_mechanism_insists_on_one(tmp_path):
    w = login_bot(tmp_path, 'sasl=PLAIN,SCRAM-SHA-256', sasl_password='hunter2',
                  sasl_mechanism='plain')
    assert lines(w.sent()) == ['AUTHENTICATE PLAIN']


def test_an_unknown_sasl_mechanism_is_refused(tmp_path):
    with pytest.raises(ValueError, match='sasl_mechanism must be'):
        Wire(tmp_path, sasl_mechanism='MD5')


# EXTERNAL

def test_external_logs_in_with_the_client_certificate(tmp_path):
    w = Wire(tmp_path)
    w.bot.transport.client_cert = True
    w.connect()
    w.receive(':irc.example.net CAP * LS :sasl=PLAIN,EXTERNAL')
    assert lines(w.sent()) == ['CAP REQ sasl']
    w.receive(':irc.example.net CAP * ACK :sasl')
    assert lines(w.sent()) == ['AUTHENTICATE EXTERNAL']
    w.receive('AUTHENTICATE +')
    assert lines(w.sent()) == ['AUTHENTICATE +']


def test_a_failed_external_login_gives_certificate_advice(tmp_path, caplog):
    w = Wire(tmp_path)
    w.bot.transport.client_cert = True
    w.connect()
    w.receive(':irc.example.net CAP * LS :sasl=EXTERNAL', ':irc.example.net CAP * ACK :sasl',
              'AUTHENTICATE +', ':irc.example.net 904 pinbot :SASL authentication failed')
    assert 'check the client certificate is added to the account' in caplog.text


def test_the_client_certificate_options_load_into_the_ssl_context(tmp_path, monkeypatch):
    loaded = []
    monkeypatch.setattr(ssl.SSLContext, 'load_cert_chain',
                        lambda self, cert, key=None: loaded.append((cert, key)))
    w = Wire(tmp_path, ssl_required=True, ssl_certfile='bot.pem', ssl_keyfile='bot.key',
             bot_dir=str(tmp_path))
    assert loaded == [(str(tmp_path / 'bot.pem'), str(tmp_path / 'bot.key'))]
    assert w.bot.transport.client_cert


# STS

def sts_file(tmp_path):
    return tmp_path / 'data' / 'sts.json'


def test_sts_on_a_plain_connection_reconnects_with_tls(tmp_path):
    w = Wire(tmp_path)
    w.connect()
    w.receive(':irc.example.net CAP * LS :sts=port=6697,duration=300 account-tag')
    transport = w.bot.transport
    # nothing more is sent over the plain connection, not even CAP END
    assert lines(w.sent()) == []
    assert (transport.port, transport.sts_upgrade) == (6697, True)
    assert transport.ssl_context is not None
    # the policy is only kept once it's heard over TLS
    assert not sts_file(tmp_path).exists()


def test_sts_over_tls_is_remembered_for_its_duration(tmp_path):
    w = Wire(tmp_path, port=6697, ssl_required=True)
    w.connect()
    w.receive(':irc.example.net CAP * LS :sts=duration=300 account-tag')
    assert lines(w.sent()) == ['CAP REQ account-tag']
    policy = json.loads(sts_file(tmp_path).read_text())['irc.example.net']
    assert policy['port'] == 6697
    assert 290 < policy['expires'] - time.time() <= 300


def test_a_remembered_policy_makes_the_next_connection_use_tls(tmp_path):
    sts_file(tmp_path).parent.mkdir()
    sts_file(tmp_path).write_text(json.dumps(
        {'irc.example.net': {'port': 6697, 'expires': time.time() + 300}}))
    transport = Wire(tmp_path).bot.transport
    transport.follow_sts()
    assert transport.port == 6697 and transport.ssl_context is not None


def test_an_expired_policy_is_dropped(tmp_path):
    sts_file(tmp_path).parent.mkdir()
    sts_file(tmp_path).write_text(json.dumps(
        {'irc.example.net': {'port': 6697, 'expires': time.time() - 1}}))
    transport = Wire(tmp_path).bot.transport
    transport.follow_sts()
    assert transport.ssl_context is None and transport.port == 6667
    assert json.loads(sts_file(tmp_path).read_text()) == {}


def test_a_zero_duration_drops_the_policy(tmp_path):
    sts_file(tmp_path).parent.mkdir()
    sts_file(tmp_path).write_text(json.dumps(
        {'irc.example.net': {'port': 6697, 'expires': time.time() + 300}}))
    w = Wire(tmp_path, port=6697, ssl_required=True)
    w.connect()
    w.receive(':irc.example.net CAP * LS :sts=duration=0')
    assert json.loads(sts_file(tmp_path).read_text()) == {}


# MONITOR

def test_monitor_wins_the_nick_back(tmp_path):
    w = Wire(tmp_path)
    w.connect()
    w.receive(':irc.example.net 433 * pinbot :Nickname is already in use',
              ':irc.example.net 001 pinbot_ :Welcome',
              ':irc.example.net 005 pinbot_ CHANTYPES=# MONITOR=100 :are supported',
              ':irc.example.net 376 pinbot_ :End of /MOTD command')
    assert 'MONITOR + pinbot' in lines(w.sent())
    w.receive(':irc.example.net 731 pinbot_ :pinbot')
    assert lines(w.sent()) == ['NICK pinbot']
    w.receive(':pinbot_!p@host NICK pinbot')
    assert lines(w.sent()) == ['MONITOR - pinbot']
    assert w.bot.transport.nick == 'pinbot'


def test_no_monitor_when_the_bot_has_its_nick(tmp_path):
    w = Wire(tmp_path)
    w.connect()
    w.receive(':irc.example.net 001 pinbot :Welcome',
              ':irc.example.net 005 pinbot CHANTYPES=# MONITOR=100 :are supported',
              ':irc.example.net 422 pinbot :MOTD File is missing')
    assert not any(line.startswith('MONITOR') for line in lines(w.sent()))
