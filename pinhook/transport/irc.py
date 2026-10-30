"""The IRC transport, on irctokens and asyncio.

It connects, negotiates capabilities, logs in, tracks channel members and the
bot's own nick, and turns server lines into Events. Messages from the core are
split to fit IRC's 512 byte lines.
"""
import asyncio
import base64
import contextlib
import socket
import ssl

import irctokens

from ..__version__ import __version__
from .base import Event, Limits, Source, casefold

# the longest !user@host a server shows for the bot, until it has seen its own
HOSTMASK_GUESS = len('!') + 10 + len('@') + 63


class IrcTransport:
    """A connection to an IRC server.

    Args:
        logger: the bot's logger.
        server, port, nickname, password: where to connect and who as.
        ssl_context: connect with ssl, using this context. None means no ssl.
        sasl_account, sasl_password: log in with SASL PLAIN, if a password is given.
        nickserv, ns_pass: identify with NickServ instead, if SASL didn't log in.
        bot_mode: set the server's bot mode on the bot, if it has one.
    """
    name = 'irc'
    limits = Limits()
    # ask the server what it supports before registering
    asks_for_caps = True
    # seconds between tries when connecting fails, doubling up to the most
    retry_first = 10
    retry_most = 300
    # a silent server gets a PING after this many seconds, and is given up on after twice that
    ping_after = 120

    def __init__(self, logger, server, port, nickname, password=None, ssl_context=None,
                 sasl_account=None, sasl_password=None, nickserv='NickServ', ns_pass=None,
                 bot_mode=True):
        self.logger = logger
        self.server = server
        self.port = port
        self.nickname = nickname
        self.password = password
        self.ssl_context = ssl_context
        self.sasl_account = sasl_account or nickname
        self.sasl_password = sasl_password
        self.nickserv = nickserv
        self.ns_pass = ns_pass
        self.bot_mode = bot_mode
        self.open_connection = asyncio.open_connection
        self.queue = asyncio.Queue()
        self.closed = asyncio.Event()
        self.closing = False
        self.writer = None
        self.reset()

    def reset(self):
        # what a connection learns, forgotten when it drops
        self.nick = self.nickname
        self.registered = False
        self.isupport = {}
        # casefolded channel name: {casefolded nick: nick}, and the name as the server wrote it
        self.channels = {}
        self.channel_names = {}
        self.server_caps = {}
        self.caps = set()
        self.negotiating = False
        self.sasl_logged_in = False
        self.hostmask_length = HOSTMASK_GUESS

    # the transport interface

    async def run(self):
        retry = self.retry_first
        while not self.closing:
            try:
                reader, writer = await self.open()
            except OSError:
                pass
            else:
                await self.session(reader, writer)
                if self.registered:
                    retry = self.retry_first
            if self.closing:
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.closed.wait(), retry)
            retry = min(retry * 2, self.retry_most)

    async def events(self):
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event

    async def send(self, message):
        if not self.writer:
            self.logger.debug('not connected, dropping a message to {}'.format(message.target))
            return
        command = 'NOTICE' if message.kind == 'notice' else 'PRIVMSG'
        start, end = ('\x01ACTION ', '\x01') if message.kind == 'action' else ('', '')
        # what the server puts in front when it passes the line on, and the line ending
        relayed = ':{} {} {} :{}{}{}\r\n'.format(self.nick, command, message.target, start,
                                                 message.prefix, end)
        # a very long target could leave no room at all, so always allow some
        room = max(512 - len(relayed.encode()) - self.hostmask_length, 64)
        for piece in split_text(message.text, room):
            self.write(command, [message.target, start + message.prefix + piece + end])
        await self.writer.drain()

    def join(self, channel, key=''):
        self.write('JOIN', [channel, key] if key else [channel])

    def members(self, channel):
        return list(self.channels.get(self.casefold(channel), {}).values())

    def joined(self):
        return list(self.channel_names.values())

    def supports(self, feature):
        return feature in self.caps

    def casefold(self, name):
        return casefold(name, self.isupport.get('CASEMAPPING', 'rfc1459'))

    async def close(self, reason=''):
        self.closing = True
        self.closed.set()
        if self.writer:
            writer = self.writer
            self.write('QUIT', [reason])
            with contextlib.suppress(OSError):
                await writer.drain()
            writer.close()
        self.queue.put_nowait(None)

    @property
    def account_tag(self):
        return 'account-tag' in self.caps

    # connecting

    async def open(self):
        try:
            async with asyncio.timeout(30):
                return await self.open_connection(
                    self.server, self.port, ssl=self.ssl_context,
                    server_hostname=self.server if self.ssl_context else None)
        except OSError as e:
            self.logger.error(self.connection_error_message(e))
            raise

    def connection_error_message(self, error):
        start = "couldn't connect to {}:{}: ".format(self.server, self.port)
        end = ' (will keep retrying, waiting up to 5 minutes between tries)'
        if isinstance(error, ssl.SSLCertVerificationError):
            reason = error.verify_message.rstrip('.')
            start += "the server's ssl certificate failed verification ({}). ".format(reason)
            # openssl codes for hostname and ip address mismatch, and expired
            if error.verify_code in (62, 64):
                return (start + 'Set server to the name the certificate was issued for, '
                        'not an IP address or alias' + end)
            if error.verify_code == 10:
                return start + 'This needs fixing on the server' + end
            return (start + 'If this server uses a self-signed certificate, '
                    'set ssl_verify to false' + end)
        if isinstance(error, ssl.SSLError):
            reason = getattr(error, 'reason', None) or error
            return (start + 'ssl handshake failed ({}). '
                    "Check {} is the server's ssl port, usually 6697".format(reason, self.port)
                    + end)
        if isinstance(error, socket.gaierror):
            return start + 'server name not found, check the server setting' + end
        if isinstance(error, ConnectionRefusedError):
            return start + 'connection refused, check the server and port settings' + end
        if isinstance(error, TimeoutError):
            return start + 'the server took too long to answer' + end
        return start + str(error) + end

    async def session(self, reader, writer):
        self.begin(writer)
        decoder = irctokens.StatefulDecoder()
        pinged = False
        try:
            while True:
                try:
                    async with asyncio.timeout(self.ping_after):
                        data = await reader.read(65536)
                except TimeoutError:
                    if pinged:
                        self.logger.warning('the server stopped answering')
                        break
                    self.write('PING', ['pinhook'])
                    pinged = True
                    continue
                pinged = False
                lines = decoder.push(data)
                if lines is None:
                    break
                for line in lines:
                    try:
                        self.handle(line)
                    except Exception:
                        self.logger.exception("couldn't handle a line from the server: {}"
                                              .format(line.format()))
                await writer.drain()
        except OSError as e:
            self.logger.warning('lost the connection: {}'.format(e))
        finally:
            self.writer = None
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
        if not self.closing:
            self.logger.warning('disconnected from {}'.format(self.server))
            self.emit(Event('disconnected'))

    def begin(self, writer):
        """Start registering on a new connection."""
        self.reset()
        self.writer = writer
        if self.asks_for_caps:
            # some servers (like libera) only take CAP before registration
            self.negotiating = True
            self.write('CAP', ['LS', '302'])
        if self.password:
            self.write('PASS', [self.password])
        self.write('NICK', [self.nickname])
        self.write('USER', [self.nickname, '0', '*', self.nickname])

    def write(self, command, params):
        if not self.writer:
            return
        line = irctokens.build(command, params).format()
        self.writer.write(line.encode('utf-8') + b'\r\n')

    def emit(self, event):
        self.queue.put_nowait(event)

    def is_me(self, nick):
        return self.casefold(nick) == self.casefold(self.nick)

    # lines from the server

    handlers = {
        'PING': 'on_ping', 'ERROR': 'on_error', 'CAP': 'on_cap',
        'AUTHENTICATE': 'on_authenticate', '903': 'on_sasl_success',
        '902': 'on_sasl_fail', '904': 'on_sasl_fail', '905': 'on_sasl_fail', '906': 'on_sasl_fail',
        '001': 'on_welcome', '005': 'on_isupport', '433': 'on_nick_in_use', '353': 'on_names',
        'JOIN': 'on_join', 'PART': 'on_part', 'KICK': 'on_kick', 'QUIT': 'on_quit',
        'NICK': 'on_nick', 'PRIVMSG': 'on_privmsg', 'NOTICE': 'on_notice', 'TOPIC': 'on_topic',
        'INVITE': 'on_invite', 'MODE': 'on_mode',
    }

    def handle(self, line):
        """Act on one line from the server."""
        name = self.handlers.get(line.command.upper())
        if name:
            getattr(self, name)(line)

    def on_ping(self, line):
        self.write('PONG', line.params)

    def on_error(self, line):
        self.logger.warning('the server closed the connection: {}'.format(
            line.params[-1] if line.params else ''))

    # capabilities and sasl

    def on_cap(self, line):
        if not self.negotiating:
            return
        subcommand, args = line.params[1], line.params[2:]
        if subcommand == 'LS':
            for cap in args[-1].split():
                name, _, value = cap.partition('=')
                self.server_caps[name] = value
            # a * means the list carries on in another line
            if len(args) > 1 and args[0] == '*':
                return
            wanted = [cap for cap in ('account-tag',) if cap in self.server_caps]
            if self.sasl_password:
                if self.sasl_offered():
                    wanted.append('sasl')
                else:
                    self.logger.error("sasl_password is set, but this server doesn't offer "
                                      "SASL PLAIN logins, so the bot isn't logged in")
            if wanted:
                self.write('CAP', ['REQ', ' '.join(wanted)])
                return
        elif subcommand == 'ACK':
            acked = args[-1].split()
            self.caps.update(acked)
            if 'sasl' in acked:
                # carries on in on_authenticate, then on_sasl_success or a failure
                self.write('AUTHENTICATE', ['PLAIN'])
                return
        elif subcommand == 'NAK':
            if self.sasl_password:
                self.logger.error("the server refused SASL, so the bot isn't logged in")
        else:
            return
        self.end_caps()

    def sasl_offered(self):
        # sasl=PLAIN,EXTERNAL lists the methods, plain sasl means the server didn't say
        if 'sasl' not in self.server_caps:
            return False
        methods = self.server_caps['sasl']
        return not methods or 'PLAIN' in methods.upper().split(',')

    def end_caps(self):
        # registration waits until we say we're done
        self.negotiating = False
        self.write('CAP', ['END'])

    def on_authenticate(self, line):
        if line.params[0] != '+' or not self.negotiating:
            return
        login = '\0{}\0{}'.format(self.sasl_account, self.sasl_password)
        encoded = base64.b64encode(login.encode('utf-8')).decode('ascii')
        # the spec sends it in 400 byte pieces, and + after a last piece that's exactly 400
        for i in range(0, len(encoded), 400):
            self.write('AUTHENTICATE', [encoded[i:i + 400]])
        if len(encoded) % 400 == 0:
            self.write('AUTHENTICATE', ['+'])

    def on_sasl_success(self, line):
        self.sasl_logged_in = True
        self.logger.info('logged in as {} with SASL'.format(self.sasl_account))
        self.end_caps()

    def on_sasl_fail(self, line):
        reason = line.params[-1] if len(line.params) > 1 else 'no reason given'
        self.logger.error("SASL login as {} failed ({}), check sasl_account and sasl_password"
                          .format(self.sasl_account, reason))
        if self.negotiating:
            self.end_caps()

    # registering

    def on_welcome(self, line):
        # registering is done, so any capability negotiation is too
        self.registered = True
        self.negotiating = False
        self.nick = line.params[0]
        self.welcomed()
        self.emit(Event('connected'))

    def welcomed(self):
        if self.ns_pass and not self.sasl_logged_in:
            self.logger.info('identifying with nickserv')
            self.write('PRIVMSG', [self.nickserv, 'identify {}'.format(self.ns_pass)])

    def on_isupport(self, line):
        for token in line.params[1:-1]:
            name, _, value = token.partition('=')
            if name.startswith('-'):
                self.isupport.pop(name[1:], None)
                continue
            self.isupport[name] = value
            # servers that support bot mode advertise its letter as BOT=<mode>
            # https://ircv3.net/specs/extensions/bot-mode
            if name == 'BOT' and value and self.bot_mode:
                self.logger.info('setting bot mode +{}'.format(value))
                self.write('MODE', [self.nick, '+' + value])

    def on_nick_in_use(self, line):
        # once registered, a failed nick change just keeps the nick we already have
        if self.registered:
            return
        taken = line.params[1]
        self.logger.warning('nickname {} in use, trying {}'.format(taken, taken + '_'))
        self.write('NICK', [taken + '_'])

    # channels and members

    def prefixes(self):
        # PREFIX=(ov)@+ gives the symbols that can come before a nick in NAMES
        prefix = self.isupport.get('PREFIX', '(qaohv)~&@%+')
        return prefix.partition(')')[2] or '~&@%+'

    def on_names(self, line):
        channel = self.channels.get(self.casefold(line.params[2]))
        if channel is None:
            return
        symbols = self.prefixes()
        for name in line.params[3].split():
            nick = name.lstrip(symbols).partition('!')[0]
            channel[self.casefold(nick)] = nick

    def on_join(self, line):
        nick = line.hostmask.nickname
        key = self.casefold(line.params[0])
        if self.is_me(nick):
            self.channels[key] = {}
            self.channel_names[key] = line.params[0]
            if line.hostmask.username and line.hostmask.hostname:
                hostmask = '!{}@{}'.format(line.hostmask.username, line.hostmask.hostname)
                self.hostmask_length = len(hostmask.encode('utf-8'))
        if key in self.channels:
            self.channels[key][self.casefold(nick)] = nick
        self.emit(Event('join', self.source(line), line.params[0], tags=dict(line.tags or {})))

    def leave(self, channel, nick):
        key = self.casefold(channel)
        if self.is_me(nick):
            self.channels.pop(key, None)
            self.channel_names.pop(key, None)
        elif key in self.channels:
            self.channels[key].pop(self.casefold(nick), None)

    def on_part(self, line):
        self.leave(line.params[0], line.hostmask.nickname)
        self.emit(Event('part', self.source(line), line.params[0], self.last(line, 1)))

    def on_kick(self, line):
        self.leave(line.params[0], line.params[1])
        self.emit(Event('kick', self.source(line), line.params[0], self.last(line, 2),
                        data={'kicked': line.params[1]}))

    def on_quit(self, line):
        folded = self.casefold(line.hostmask.nickname)
        for members in self.channels.values():
            members.pop(folded, None)
        self.emit(Event('quit', self.source(line), '', self.last(line, 0)))

    def on_nick(self, line):
        old, new = line.hostmask.nickname, line.params[0]
        for members in self.channels.values():
            if members.pop(self.casefold(old), None) is not None:
                members[self.casefold(new)] = new
        if self.is_me(old):
            self.nick = new
        self.emit(Event('nick', self.source(line), '', data={'new_nick': new}))

    def on_topic(self, line):
        self.emit(Event('topic', self.source(line), line.params[0], self.last(line, 1)))

    def on_invite(self, line):
        # INVITE <the bot> <channel>
        if len(line.params) > 1:
            self.emit(Event('invite', self.source(line), line.params[1]))

    def on_mode(self, line):
        # only modes someone set, not the server setting the bot's own when it connects
        if line.source and '!' in line.source:
            self.emit(Event('mode', self.source(line), line.params[0],
                            data={'modes': line.params[1:]}))

    def source(self, line):
        tags = line.tags or {}
        account = tags.get('account')
        hostmask = line.hostmask
        return Source(hostmask.nickname, hostmask.username, hostmask.hostname,
                      None if account in (None, '', '*') else account)

    @staticmethod
    def last(line, index):
        # a reason or topic at params[index], if the line has one
        return line.params[index] if len(line.params) > index else ''

    # messages

    def on_privmsg(self, line):
        if not line.source or len(line.params) < 2:
            return
        target, text = line.params[0], line.params[1]
        kind = 'privmsg'
        if text.startswith('\x01'):
            ctcp, _, rest = text.strip('\x01').partition(' ')
            if ctcp.upper() != 'ACTION':
                self.answer_ctcp(line.hostmask.nickname, ctcp.upper(), rest)
                return
            kind, text = 'action', rest
        self.emit(Event('message', self.source(line), target, text, kind, dict(line.tags or {})))

    def on_notice(self, line):
        # notices from people, not the server's own before and while the bot registers.
        # CTCP replies are notices too, and plugins don't need them
        if not line.source or '!' not in line.source or len(line.params) < 2:
            return
        if line.params[1].startswith('\x01'):
            return
        self.emit(Event('message', self.source(line), line.params[0], line.params[1], 'notice',
                        dict(line.tags or {})))

    def answer_ctcp(self, nick, ctcp, rest):
        if ctcp == 'VERSION':
            self.write('NOTICE', [nick, '\x01VERSION pinhook {}\x01'.format(__version__)])
        elif ctcp == 'PING':
            self.write('NOTICE', [nick, '\x01PING {}\x01'.format(rest)])


class TwitchTransport(IrcTransport):
    """Twitch chat, which is IRC with its own capabilities, asked for once connected."""
    name = 'twitch'
    asks_for_caps = False

    def welcomed(self):
        self.logger.info('requesting permissions')
        for cap in ('twitch.tv/membership', 'twitch.tv/tags', 'twitch.tv/commands'):
            self.write('CAP', ['REQ', cap])


def split_text(text, room):
    """Split text into lines of at most room bytes of utf-8, at spaces where it can."""
    pieces = []
    for line in text.splitlines():
        while len(line.encode('utf-8')) > room:
            # how many characters fit, without cutting one in half
            fits = len(line.encode('utf-8')[:room].decode('utf-8', 'ignore'))
            space = line.rfind(' ', 0, fits + 1)
            if space > 0:
                pieces.append(line[:space])
                line = line[space + 1:]
            else:
                pieces.append(line[:fits])
                line = line[fits:]
        if line:
            pieces.append(line)
    return pieces
