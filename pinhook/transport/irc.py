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
from .base import Event, Limits, Source, casefold, is_channel
from .members import Tracker

# the longest !user@host a server shows for the bot, until it has seen its own
HOSTMASK_GUESS = len('!') + 10 + len('@') + 63
# what the bot asks for when the server offers it
WANTED_CAPS = ('account-tag', 'multi-prefix', 'userhost-in-names', 'extended-join',
               'account-notify', 'away-notify', 'chghost', 'setname', 'server-time',
               'message-tags', 'invite-notify', 'cap-notify')
# marks the bot's own WHOX queries, so their replies can be told apart
WHOX_TOKEN = '152'


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
        # who is in each channel, and each channel's name as the server wrote it
        self.tracker = Tracker(self.casefold)
        self.channel_names = {}
        self.server_caps = {}
        self.caps = set()
        self.negotiating = False
        self.authenticating = False
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
        room = self.text_room(message.kind, message.target, message.prefix)
        # a plugin's broken text, like a lone surrogate, goes out as ? instead of failing
        text = message.text.encode('utf-8', 'replace').decode('utf-8')
        for piece in split_text(text, room):
            self.write(command, [message.target, start + message.prefix + piece + end])
        await self.writer.drain()

    def join(self, channel, key=''):
        self.write('JOIN', [channel, key] if key else [channel])

    def text_room(self, kind, target, prefix=''):
        return text_room(self.nick, kind, target, prefix, self.hostmask_length)

    def members(self, channel):
        return self.tracker.members(channel)

    def joined(self):
        return list(self.channel_names.values())

    def member_modes(self, channel, nick):
        return self.tracker.modes(channel, nick)

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
        # always valid utf-8, which a UTF8ONLY server insists on, even from a plugin's
        # broken text
        self.writer.write(line.encode('utf-8', 'replace') + b'\r\n')

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
        '352': 'on_who', '354': 'on_whox',
        'JOIN': 'on_join', 'PART': 'on_part', 'KICK': 'on_kick', 'QUIT': 'on_quit',
        'NICK': 'on_nick', 'PRIVMSG': 'on_privmsg', 'NOTICE': 'on_notice', 'TOPIC': 'on_topic',
        'INVITE': 'on_invite', 'MODE': 'on_mode', 'ACCOUNT': 'on_account', 'AWAY': 'on_away',
        'CHGHOST': 'on_chghost', 'SETNAME': 'on_setname', 'FAIL': 'on_standard_reply',
        'WARN': 'on_standard_reply', 'NOTE': 'on_standard_reply',
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
        subcommand, args = line.params[1], line.params[2:]
        if subcommand == 'LS' and self.negotiating:
            self.offered(args[-1])
            # a * means the list carries on in another line
            if len(args) > 1 and args[0] == '*':
                return
            if self.request(self.wanted(during_registration=True)):
                return
        elif subcommand == 'NEW':
            # cap-notify: the server offers something new, like sasl once services are back
            self.request(self.wanted(self.offered(args[-1])))
            return
        elif subcommand == 'DEL':
            for cap in args[-1].split():
                self.server_caps.pop(cap, None)
                self.caps.discard(cap)
            return
        elif subcommand == 'ACK':
            acked = args[-1].split()
            self.caps.update(cap for cap in acked if not cap.startswith('-'))
            self.caps.difference_update(cap[1:] for cap in acked if cap.startswith('-'))
            if 'sasl' in acked and self.sasl_password and not self.sasl_logged_in:
                # carries on in on_authenticate, then on_sasl_success or a failure
                self.authenticating = True
                self.write('AUTHENTICATE', ['PLAIN'])
                return
        elif subcommand == 'NAK':
            if self.sasl_password and 'sasl' in args[-1].split():
                self.logger.error("the server refused SASL, so the bot isn't logged in")
        else:
            return
        if self.negotiating:
            self.end_caps()

    def offered(self, caps):
        # what CAP LS or CAP NEW lists, like 'sasl=PLAIN,EXTERNAL multi-prefix'
        names = []
        for cap in caps.split():
            name, _, value = cap.partition('=')
            self.server_caps[name] = value
            names.append(name)
        return names

    def wanted(self, names=None, during_registration=False):
        # the caps worth asking for, out of names, or out of everything offered
        names = self.server_caps if names is None else names
        wanted = [cap for cap in WANTED_CAPS if cap in names and cap not in self.caps]
        if self.sasl_password and not self.sasl_logged_in and 'sasl' in names:
            if self.sasl_offered():
                wanted.append('sasl')
            else:
                self.logger.error("sasl_password is set, but this server doesn't offer "
                                  "SASL PLAIN logins, so the bot isn't logged in")
        elif self.sasl_password and during_registration and 'sasl' not in names:
            self.logger.error("sasl_password is set, but this server doesn't offer "
                              "SASL PLAIN logins, so the bot isn't logged in")
        return wanted

    def request(self, caps):
        if caps:
            self.write('CAP', ['REQ', ' '.join(caps)])
        return bool(caps)

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
        if line.params[0] != '+' or not self.authenticating:
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
        self.authenticating = False
        self.logger.info('logged in as {} with SASL'.format(self.sasl_account))
        if self.negotiating:
            self.end_caps()

    def on_sasl_fail(self, line):
        reason = line.params[-1] if len(line.params) > 1 else 'no reason given'
        self.logger.error("SASL login as {} failed ({}), check sasl_account and sasl_password"
                          .format(self.sasl_account, reason))
        self.authenticating = False
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
        # PREFIX=(ov)@+ gives the modes members can have, and the symbols NAMES shows for them
        letters, _, symbols = self.isupport.get('PREFIX', '(qaohv)~&@%+').lstrip('(').partition(')')
        if not symbols or len(letters) != len(symbols):
            letters, symbols = 'qaohv', '~&@%+'
        return dict(zip(symbols, letters))

    def on_names(self, line):
        # 353 <bot> = #channel :@mal +ana troll, or mal!m@host with userhost-in-names
        channel = line.params[2]
        if not self.tracker.has_channel(channel):
            return
        symbols = self.prefixes()
        for name in line.params[3].split():
            letters, hostmask = self.split_prefix(name, symbols)
            nick, _, rest = hostmask.partition('!')
            user, _, host = rest.partition('@')
            self.tracker.join(channel, nick, user=user or None, host=host or None)
            # without multi-prefix only the highest shows, which is enough to tell ops and voice
            self.tracker.set_modes(channel, nick, letters)

    @staticmethod
    def split_prefix(name, symbols):
        # '@+mal' -> ({'o', 'v'}, 'mal')
        bare = name.lstrip(''.join(symbols))
        return {symbols[s] for s in name[:len(name) - len(bare)]}, bare

    def who(self, channel):
        # everyone's account, host and away status, which NAMES doesn't give. WHOX can ask
        # for the account too
        if 'WHOX' in self.isupport:
            self.write('WHO', [channel, '%tcuhnfar,' + WHOX_TOKEN])
        else:
            self.write('WHO', [channel])

    def on_who(self, line):
        # 352 <bot> #channel user host server nick flags :hops realname
        if len(line.params) < 8:
            return
        _, channel, user, host, _, nick, flags, last = line.params[:8]
        self.who_reply(channel, nick, user, host, flags, None, last.partition(' ')[2])

    def on_whox(self, line):
        # 354 <bot> token #channel user host nick flags account :realname
        if len(line.params) < 9 or line.params[1] != WHOX_TOKEN:
            return
        _, _, channel, user, host, nick, flags, account, realname = line.params[:9]
        self.who_reply(channel, nick, user, host, flags, account, realname)

    def who_reply(self, channel, nick, user, host, flags, account, realname):
        if not self.tracker.has_channel(channel):
            return
        bot_letter = self.isupport.get('BOT')
        # flags are H or G for here or gone, * for an IRC operator, then the member's prefixes
        self.tracker.join(channel, nick, user=user, host=host, away=flags.startswith('G'),
                          realname=realname, is_bot=bool(bot_letter) and bot_letter in flags)
        symbols = self.prefixes()
        letters = {symbols[c] for c in flags if c in symbols}
        if letters:
            self.tracker.set_modes(channel, nick, letters)
        if account == '0':
            self.tracker.log_out(nick)
        elif account:
            self.tracker.update(nick, account=account)

    def on_join(self, line):
        nick = line.hostmask.nickname
        channel = line.params[0]
        if self.is_me(nick):
            self.tracker.add_channel(channel)
            self.channel_names[self.casefold(channel)] = channel
            if line.hostmask.username and line.hostmask.hostname:
                hostmask = '!{}@{}'.format(line.hostmask.username, line.hostmask.hostname)
                self.hostmask_length = len(hostmask.encode('utf-8'))
            self.who(channel)
        self.tracker.join(channel, nick, user=line.hostmask.username, host=line.hostmask.hostname)
        # extended-join: JOIN #channel account :real name, with * for no account
        if len(line.params) >= 3:
            self.tracker.update(nick, realname=line.params[2])
            self.logged_in(nick, line.params[1])
        self.emit(Event('join', self.source(line), channel, tags=self.tags(line)))

    def logged_in(self, nick, account):
        if account in ('*', '0', ''):
            self.tracker.log_out(nick)
        else:
            self.tracker.update(nick, account=account)

    def leave(self, channel, nick):
        if self.is_me(nick):
            self.tracker.remove_channel(channel)
            self.channel_names.pop(self.casefold(channel), None)
        else:
            self.tracker.leave(channel, nick)

    def on_part(self, line):
        source = self.source(line)
        self.leave(line.params[0], line.hostmask.nickname)
        self.emit(Event('part', source, line.params[0], self.last(line, 1), tags=self.tags(line)))

    def on_kick(self, line):
        self.leave(line.params[0], line.params[1])
        self.emit(Event('kick', self.source(line), line.params[0], self.last(line, 2),
                        tags=self.tags(line), data={'kicked': line.params[1]}))

    def on_quit(self, line):
        source = self.source(line)
        self.tracker.quit(line.hostmask.nickname)
        self.emit(Event('quit', source, '', self.last(line, 0), tags=self.tags(line)))

    def on_nick(self, line):
        old, new = line.hostmask.nickname, line.params[0]
        self.tracker.rename(old, new)
        if self.is_me(old):
            self.nick = new
        self.emit(Event('nick', self.source(line), '', tags=self.tags(line),
                        data={'new_nick': new}))

    def on_account(self, line):
        # account-notify: ACCOUNT <account>, or ACCOUNT * on logging out
        if line.params:
            self.logged_in(line.hostmask.nickname, line.params[0])

    def on_away(self, line):
        # away-notify: AWAY :reason when going away, a bare AWAY when back
        self.tracker.update(line.hostmask.nickname, away=bool(line.params))

    def on_chghost(self, line):
        # chghost: CHGHOST <new user> <new host>
        if len(line.params) >= 2:
            self.tracker.update(line.hostmask.nickname, user=line.params[0],
                                host=line.params[1])

    def on_setname(self, line):
        if line.params:
            self.tracker.update(line.hostmask.nickname, realname=line.params[0])

    def on_topic(self, line):
        self.emit(Event('topic', self.source(line), line.params[0], self.last(line, 1),
                        tags=self.tags(line)))

    def on_invite(self, line):
        # INVITE <who> <channel>. Usually the bot, and with invite-notify, anyone invited to
        # a channel the bot is in
        if len(line.params) > 1:
            self.emit(Event('invite', self.source(line), line.params[1], tags=self.tags(line),
                            data={'invited': line.params[0]}))

    def on_mode(self, line):
        if len(line.params) > 1 and is_channel(line.params[0]):
            self.track_modes(line.params[0], line.params[1], line.params[2:])
        # only modes someone set, not the server setting the bot's own when it connects
        if line.source and '!' in line.source:
            self.emit(Event('mode', self.source(line), line.params[0], tags=self.tags(line),
                            data={'modes': line.params[1:]}))

    def track_modes(self, channel, changes, args):
        # MODE #games +ov-v mal ana troll. Which other modes take an argument comes from
        # CHANMODES: lists and keys always, limits only when set, flags never
        if not self.tracker.has_channel(channel):
            return
        member = set(self.prefixes().values())
        lists, keys, limits = (self.isupport.get('CHANMODES', 'beI,k,l,') + ',,').split(',')[:3]
        args = list(args)
        adding = True
        for letter in changes:
            if letter in '+-':
                adding = letter == '+'
            elif letter in member and args:
                self.tracker.set_mode(channel, args.pop(0), letter, adding)
            elif (letter in lists + keys or (letter in limits and adding)) and args:
                args.pop(0)

    def source(self, line):
        # who sent a line. Without an account tag, the account comes from member tracking,
        # so account bans work on joins and nick changes too
        tags = line.tags or {}
        hostmask = line.hostmask
        known = self.tracker.lookup(hostmask.nickname) or {}
        account = tags.get('account')
        if account is None:
            account = known.get('account')
        elif account not in ('', '*'):
            self.tracker.update(hostmask.nickname, account=account)
        return Source(hostmask.nickname, hostmask.username or known.get('user'),
                      hostmask.hostname or known.get('host'),
                      None if account in (None, '', '*') else account)

    @staticmethod
    def tags(line):
        return dict(line.tags or {})

    def on_standard_reply(self, line):
        # FAIL, WARN or NOTE <command> <code> [<context>...] :<description>
        if len(line.params) < 3:
            return
        command, code, description = line.params[0], line.params[1], line.params[-1]
        level = {'FAIL': 'error', 'WARN': 'warning'}.get(line.command.upper(), 'info')
        context = ' '.join(line.params[2:-1])
        getattr(self.logger, level)('the server said {} {}{}: {}'.format(
            command, code, ' ({})'.format(context) if context else '', description))

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
        self.emit(Event('message', self.source(line), target, text, kind, self.tags(line)))

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


def text_room(nick, kind, target, prefix='', hostmask_length=HOSTMASK_GUESS):
    """How many bytes of text fit in one message to target, after the server adds who sent it."""
    command = 'NOTICE' if kind == 'notice' else 'PRIVMSG'
    start, end = ('\x01ACTION ', '\x01') if kind == 'action' else ('', '')
    # what the server puts in front when it passes the line on, and the line ending
    relayed = ':{} {} {} :{}{}{}\r\n'.format(nick, command, target, start, prefix, end)
    # a very long target could leave no room at all, so always allow some
    return max(512 - len(relayed.encode()) - hostmask_length, 64)


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
