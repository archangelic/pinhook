import base64
from types import SimpleNamespace
from unittest import mock


def cap(*arguments):
    return SimpleNamespace(arguments=list(arguments), target='*')


def reply(target='*', *arguments):
    return SimpleNamespace(arguments=list(arguments), target=target)


def connecting(make_bot, **options):
    # a bot that has just connected and sent CAP LS
    b = make_bot(**options)
    b.cap_factory(lambda address: mock.Mock())(('localhost', 6667))
    return b


def decoded(conn):
    # the login the bot sent, put back together from its AUTHENTICATE pieces
    pieces = [c.args[0][len('AUTHENTICATE '):] for c in conn.send_raw.call_args_list]
    payload = ''.join(p for p in pieces if p not in ('PLAIN', '+'))
    return base64.b64decode(payload).decode()


def test_sasl_logs_in_before_registering(make_bot, conn):
    b = connecting(make_bot, sasl_password='hunter2', sasl_account='pinbotacct')
    b.on_cap(conn, cap('LS', 'account-tag sasl=PLAIN,EXTERNAL'))
    conn.cap.assert_called_once_with('REQ', 'account-tag', 'sasl')
    b.on_cap(conn, cap('ACK', 'account-tag sasl'))
    conn.send_raw.assert_called_once_with('AUTHENTICATE PLAIN')
    b.on_authenticate(conn, reply('+'))
    assert decoded(conn) == '\0pinbotacct\0hunter2'
    # registration still waits for the login
    assert mock.call('END') not in conn.cap.call_args_list
    b.on_saslsuccess(conn, reply('pinbot', 'SASL authentication successful'))
    assert b.sasl_logged_in
    assert b.account_tag
    conn.cap.assert_called_with('END')


def test_sasl_account_defaults_to_the_nickname(make_bot, conn):
    b = connecting(make_bot, sasl_password='hunter2')
    b.on_cap(conn, cap('LS', 'sasl'))
    b.on_cap(conn, cap('ACK', 'sasl'))
    b.on_authenticate(conn, reply('+'))
    assert decoded(conn) == '\0pinbot\0hunter2'


def test_long_logins_are_sent_in_400_byte_pieces(make_bot, conn):
    # this password makes the encoded login exactly 800 bytes, so it ends with a +
    b = connecting(make_bot, sasl_password='x' * (600 - len('\0pinbot\0')))
    b.on_cap(conn, cap('LS', 'sasl'))
    b.on_cap(conn, cap('ACK', 'sasl'))
    b.on_authenticate(conn, reply('+'))
    pieces = [c.args[0] for c in conn.send_raw.call_args_list][1:]
    assert [len(p) - len('AUTHENTICATE ') for p in pieces] == [400, 400, 1]
    assert pieces[-1] == 'AUTHENTICATE +'
    assert decoded(conn) == '\0pinbot\0' + 'x' * (600 - len('\0pinbot\0'))


def test_failed_login_carries_on_and_says_why(make_bot, conn, caplog):
    b = connecting(make_bot, sasl_password='wrong')
    b.on_cap(conn, cap('LS', 'sasl'))
    b.on_cap(conn, cap('ACK', 'sasl'))
    b.on_authenticate(conn, reply('+'))
    b.on_saslfail(conn, reply('pinbot', 'SASL authentication failed'))
    assert not b.sasl_logged_in
    conn.cap.assert_called_with('END')
    assert ('SASL login as pinbot failed (SASL authentication failed), '
            'check sasl_account and sasl_password') in caplog.text


def test_server_without_sasl_is_reported(make_bot, conn, caplog):
    b = connecting(make_bot, sasl_password='hunter2')
    b.on_cap(conn, cap('LS', 'account-tag'))
    conn.cap.assert_called_once_with('REQ', 'account-tag')
    assert "this server doesn't offer SASL PLAIN logins" in caplog.text


def test_server_without_plain_is_reported(make_bot, conn, caplog):
    b = connecting(make_bot, sasl_password='hunter2')
    b.on_cap(conn, cap('LS', 'sasl=EXTERNAL'))
    conn.cap.assert_called_once_with('END')
    assert "this server doesn't offer SASL PLAIN logins" in caplog.text


def test_no_sasl_password_means_no_sasl(make_bot, conn):
    b = connecting(make_bot)
    b.on_cap(conn, cap('LS', 'account-tag sasl'))
    conn.cap.assert_called_once_with('REQ', 'account-tag')


def test_nickserv_is_skipped_after_a_sasl_login(make_bot, conn):
    b = connecting(make_bot, sasl_password='hunter2', ns_pass='hunter2')
    b.on_cap(conn, cap('LS', 'sasl'))
    b.on_cap(conn, cap('ACK', 'sasl'))
    b.on_saslsuccess(conn, reply('pinbot'))
    b.on_welcome(conn, SimpleNamespace())
    assert mock.call('NickServ', 'identify hunter2') not in conn.privmsg.call_args_list


def test_nickserv_is_the_fallback_when_sasl_fails(make_bot, conn):
    b = connecting(make_bot, sasl_password='wrong', ns_pass='hunter2')
    b.on_cap(conn, cap('LS', 'sasl'))
    b.on_cap(conn, cap('ACK', 'sasl'))
    b.on_saslfail(conn, reply('pinbot', 'SASL authentication failed'))
    b.on_welcome(conn, SimpleNamespace())
    assert mock.call('NickServ', 'identify hunter2') in conn.privmsg.call_args_list


def test_sasl_without_ssl_warns(make_bot, caplog):
    make_bot(sasl_password='hunter2')
    assert 'sasl_password will be sent without ssl' in caplog.text
