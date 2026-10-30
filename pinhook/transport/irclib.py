"""The irc library behind the transport interface, until irctokens replaces it."""
import base64
import functools
import socket
import ssl

import irc.bot
import irc.client
import irc.connection

from .base import Event, MessageTooLong, Source


irc.client.ServerConnection.buffer_class.errors = 'replace'


class IrcLibTransport(irc.bot.SingleServerIRCBot):
    """An IRC connection, using the irc library's bot to connect and track channels.

    Args:
        handler: called with each Event.
        logger: the bot's logger.
        server, port, nickname, password: where to connect and who as.
        ssl_context: connect with ssl, using this context. None means no ssl.
        sasl_account, sasl_password: log in with SASL PLAIN, if a password is given.
        nickserv, ns_pass: identify with NickServ instead, if SASL didn't log in.
        bot_mode: set the server's bot mode on the bot, if it has one.
        owner: the Bot, whose irc library handlers (like on_join) still get events.
    """
    name = 'irc'
    # set once the server agrees to tag messages with the sender's account
    account_tag = False
    _negotiating_caps = False
    # set once the bot has logged in to its account with sasl
    sasl_logged_in = False

    def __init__(self, handler, logger, server, port, nickname, password=None, ssl_context=None,
                 sasl_account=None, sasl_password=None, nickserv='NickServ', ns_pass=None,
                 bot_mode=True, owner=None):
        self.handler = handler
        self.logger = logger
        self.sasl_account = sasl_account or nickname
        self.sasl_password = sasl_password
        self.nickserv = nickserv
        self.ns_pass = ns_pass
        self.bot_mode = bot_mode
        self.owner = owner
        if ssl_context:
            wrapper = functools.partial(ssl_context.wrap_socket, server_hostname=server)
            factory = irc.connection.Factory(wrapper=wrapper)
        else:
            factory = irc.connection.Factory()
        super().__init__([(server, port, password)], nickname, nickname,
                         connect_factory=self.connect_factory(factory))

    # the transport interface

    @property
    def nick(self):
        return self.connection.get_nickname()

    def send(self, message):
        send = {'privmsg': self.connection.privmsg, 'action': self.connection.action,
                'notice': self.connection.notice}[message.kind]
        try:
            send(message.target, message.text)
        except irc.client.MessageTooLong as e:
            raise MessageTooLong(str(e)) from e

    def join(self, channel, key=''):
        self.connection.join(channel, key)

    def members(self, channel):
        return list(self.channels[channel].users())

    def supports(self, feature):
        return feature == 'account-tag' and self.account_tag

    def close(self, reason=''):
        self.connection.quit(reason)

    # connecting

    def connect_factory(self, factory):
        return self.cap_factory(factory)

    def connect(self, *args, **kwargs):
        # the irc library quietly retries failed connections, so say why it failed
        try:
            super().connect(*args, **kwargs)
        except irc.client.ServerConnectionError as e:
            self.logger.error(self.connection_error_message(args[0], args[1], e))
            raise

    def connection_error_message(self, host, port, error):
        cause = error.__cause__
        start = "couldn't connect to {}:{}: ".format(host, port)
        end = ' (will keep retrying every 1-5 minutes)'
        if isinstance(cause, ssl.SSLCertVerificationError):
            reason = cause.verify_message.rstrip('.')
            start += "the server's ssl certificate failed verification ({}). ".format(reason)
            # openssl codes for hostname and ip address mismatch, and expired
            if cause.verify_code in (62, 64):
                return (start + 'Set server to the name the certificate was issued for, '
                        'not an IP address or alias' + end)
            if cause.verify_code == 10:
                return start + 'This needs fixing on the server' + end
            return (start + 'If this server uses a self-signed certificate, '
                    'set ssl_verify to false' + end)
        if isinstance(cause, ssl.SSLError):
            reason = getattr(cause, 'reason', None) or cause
            return (start + 'ssl handshake failed ({}). '
                    "Check {} is the server's ssl port, usually 6697".format(reason, port) + end)
        if isinstance(cause, socket.gaierror):
            return start + 'server name not found, check the server setting' + end
        if isinstance(cause, ConnectionRefusedError):
            return start + 'connection refused, check the server and port settings' + end
        return start + str(cause or error) + end

    # capabilities and sasl

    def cap_factory(self, factory):
        # ask what the server supports before the irc library sends NICK and USER,
        # some servers (like libera) only allow it before registration
        def connect(address):
            sock = factory(address)
            sock.send(b'CAP LS 302\r\n')
            self._negotiating_caps = True
            self._server_caps = {}
            self.account_tag = False
            self.sasl_logged_in = False
            return sock
        return connect

    def on_cap(self, c, e):
        if not self._negotiating_caps:
            return
        subcommand = e.arguments[0]
        if subcommand == 'LS':
            for cap in e.arguments[-1].split():
                name, _, value = cap.partition('=')
                self._server_caps[name] = value
            # a * means the list carries on in another line
            if len(e.arguments) > 2 and e.arguments[1] == '*':
                return
            wanted = [cap for cap in ('account-tag',) if cap in self._server_caps]
            if self.sasl_password:
                if self.sasl_offered():
                    wanted.append('sasl')
                else:
                    self.logger.error("sasl_password is set, but this server doesn't offer "
                                      "SASL PLAIN logins, so the bot isn't logged in")
            if wanted:
                c.cap('REQ', *wanted)
                return
        elif subcommand == 'ACK':
            acked = e.arguments[-1].split()
            self.account_tag = 'account-tag' in acked
            if 'sasl' in acked:
                # carries on in on_authenticate, then on_saslsuccess or a failure
                c.send_raw('AUTHENTICATE PLAIN')
                return
        elif subcommand == 'NAK':
            if self.sasl_password:
                self.logger.error("the server refused SASL, so the bot isn't logged in")
        else:
            return
        self.end_caps(c)

    def sasl_offered(self):
        # sasl=PLAIN,EXTERNAL lists the methods, plain sasl means the server didn't say
        if 'sasl' not in self._server_caps:
            return False
        methods = self._server_caps['sasl']
        return not methods or 'PLAIN' in methods.upper().split(',')

    def end_caps(self, c):
        # registration waits until we say we're done
        self._negotiating_caps = False
        c.cap('END')

    def on_authenticate(self, c, e):
        if e.target != '+' or not self._negotiating_caps:
            return
        login = '\0{}\0{}'.format(self.sasl_account, self.sasl_password)
        encoded = base64.b64encode(login.encode('utf-8')).decode('ascii')
        # the spec sends it in 400 byte pieces, and + after a last piece that's exactly 400
        for i in range(0, len(encoded), 400):
            c.send_raw('AUTHENTICATE ' + encoded[i:i + 400])
        if len(encoded) % 400 == 0:
            c.send_raw('AUTHENTICATE +')

    def on_saslsuccess(self, c, e):
        self.sasl_logged_in = True
        self.logger.info('logged in as {} with SASL'.format(self.sasl_account))
        self.end_caps(c)

    def on_saslfail(self, c, e):
        reason = e.arguments[-1] if e.arguments else 'no reason given'
        self.logger.error("SASL login as {} failed ({}), check sasl_account and sasl_password"
                          .format(self.sasl_account, reason))
        if self._negotiating_caps:
            self.end_caps(c)

    # the other ways a sasl login can end without logging in
    on_sasltoolong = on_saslfail
    on_saslaborted = on_saslfail
    on_nicklocked = on_saslfail

    # registering

    def on_welcome(self, c, e):
        # registering is done, so any capability negotiation is too
        self._negotiating_caps = False
        if self.ns_pass and not self.sasl_logged_in:
            self.logger.info('identifying with nickserv')
            c.privmsg(self.nickserv, 'identify {}'.format(self.ns_pass))
        self.handler(Event('connected'))

    def on_nicknameinuse(self, c, e):
        # servers call us * until we're registered, after that a failed
        # nick change should just keep the nick we already have
        if e.target != '*':
            return
        new_nick = e.arguments[0] + '_'
        self.logger.warning('nickname {} in use, trying {}'.format(e.arguments[0], new_nick))
        c.nick(new_nick)

    def on_featurelist(self, c, e):
        # servers that support bot mode advertise its letter as BOT=<mode>
        # https://ircv3.net/specs/extensions/bot-mode
        if not self.bot_mode:
            return
        for feature in e.arguments:
            if feature.startswith('BOT='):
                mode = feature[len('BOT='):]
                self.logger.info('setting bot mode +{}'.format(mode))
                c.mode(c.get_nickname(), '+' + mode)

    # messages

    def on_pubmsg(self, c, e):
        self.deliver_message(e, 'privmsg')

    def on_privmsg(self, c, e):
        self.deliver_message(e, 'privmsg')

    def on_action(self, c, e):
        self.deliver_message(e, 'action')

    def deliver_message(self, e, kind):
        tags = {tag['key']: tag['value'] for tag in e.tags or []}
        account = tags.get('account')
        if account == '*':
            account = None
        source = Source(e.source.nick, e.source.user, e.source.host, account)
        text = e.arguments[0] if e.arguments else ''
        self.handler(Event('message', source, e.target, text, kind, tags))

    def _dispatcher(self, connection, event):
        super()._dispatcher(connection, event)
        # 1.x Bot subclasses can handle irc library events, like adminbot's on_join
        method = getattr(self.owner, 'on_' + event.type, None)
        if method:
            method(connection, event)


class TwitchIrcLibTransport(IrcLibTransport):
    """Twitch chat, which is IRC with its own capabilities."""
    name = 'twitch'

    def connect_factory(self, factory):
        # twitch doesn't need capabilities asked for before registering
        return factory

    def on_welcome(self, c, e):
        self.logger.info('requesting permissions')
        c.cap('REQ', ':twitch.tv/membership')
        c.cap('REQ', ':twitch.tv/tags')
        c.cap('REQ', ':twitch.tv/commands')
        self.handler(Event('connected'))
