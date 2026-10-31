"""The IRC transport, on irctokens and asyncio.

It connects, negotiates capabilities, logs in, tracks channel members and the
bot's own nick, and turns server lines into Events. Messages from the core are
split to fit IRC's 512 byte lines.
"""
import asyncio
import base64
from collections import OrderedDict
import contextlib
import socket
import ssl
import time

import irctokens

from ..__version__ import __version__
from .base import CHANTYPES, Event, Limits, Source, Whois, casefold, is_channel
from .identity import IrcIdentity, TwitchIdentity
from ..store import read_json, write_json
from . import sasl
from .members import Tracker

HOSTMASK_GUESS = len('!') + 10 + len('@') + 63
WANTED_CAPS = ('account-tag', 'multi-prefix', 'userhost-in-names', 'extended-join',
               'account-notify', 'away-notify', 'chghost', 'setname', 'server-time',
               'message-tags', 'invite-notify', 'cap-notify', 'batch', 'labeled-response',
               'echo-message')
CLIENT_TAG_FEATURES = ('typing', 'reply', 'channel-context')
WHOIS_REPLIES = {'311', '312', '313', '317', '319', '330', '301', '335', '671', '318', '401'}
WHOX_TOKEN = '152'


class IrcTransport(IrcIdentity):
    """A connection to an IRC server.

    Args:
        logger: the bot's logger.
        server, port, nickname, password: where to connect and who as.
        ssl_context: connect with ssl, using this context. None means no ssl.
        sasl_account, sasl_password: log in with SASL, if a password is given. SCRAM-SHA-256
            when the server offers it, PLAIN otherwise.
        sasl_mechanism: 'auto', or the one SASL mechanism to use.
        client_cert: True if ssl_context has a client certificate, so SASL EXTERNAL can
            log in with it.
        sts_path: where servers' STS policies are kept, or None to keep them in memory.
        nickserv, ns_pass: identify with NickServ instead, if SASL didn't log in.
        bot_mode: set the server's bot mode on the bot, if it has one.
    """
    name = 'irc'
    limits = Limits()
    asks_for_caps = True
    retry_first = 10
    retry_most = 300
    ping_after = 120

    def __init__(self, logger, server, port, nickname, password=None, ssl_context=None,
                 sasl_account=None, sasl_password=None, nickserv='NickServ', ns_pass=None,
                 bot_mode=True, sasl_mechanism='auto', client_cert=False, sts_path=None):
        self.logger = logger
        self.server = server
        self.port = port
        self.nickname = nickname
        self.password = password
        self.ssl_context = ssl_context
        self.sasl_account = sasl_account or nickname
        self.sasl_password = sasl_password
        self.sasl_mechanism = sasl_mechanism
        self.client_cert = client_cert
        self.sts_path = sts_path
        self.sts_policies = self.load_sts()
        self.sts_upgrade = False
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
        self.last_ctcp = float('-inf')
        for waiting in getattr(self, 'whois_waiting', {}).values():
            if not waiting.done():
                waiting.set_result(None)
        self.nick = self.nickname
        self.registered = False
        self.isupport = {}
        self.tracker = Tracker(self.casefold)
        self.server_caps = {}
        self.caps = set()
        self.batches = {}
        self.whois_waiting = {}
        self.whois_lines = {}
        self.labels = {}
        self.next_label = 0
        self.negotiating = False
        self.authenticating = False
        self.sasl_logged_in = False
        self.logged_in_as = None
        self.sasl = None
        self.challenge = ''
        self.hostmask_length = HOSTMASK_GUESS

    async def run(self):
        retry = self.retry_first
        while not self.closing:
            try:
                reader, writer = await self.open()
            except OSError:
                pass
            else:
                if self.closing:
                    writer.close()
                    break
                await self.session(reader, writer)
                if self.registered:
                    retry = self.retry_first
            if self.closing:
                break
            if self.sts_upgrade:
                self.sts_upgrade = False
                continue
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
        text = message.text.encode('utf-8', 'replace').decode('utf-8')
        for command, params, tags in self.lines(message, text):
            self.write(command, params, tags=tags)
        await self.writer.drain()

    def lines(self, message, text):
        """What a message is sent as: (command, params, tags) for each line, split to fit."""
        command = 'NOTICE' if message.kind == 'notice' else 'PRIVMSG'
        start, end = ('\x01ACTION ', '\x01') if message.kind == 'action' else ('', '')
        room = self.text_room(message.kind, message.target, message.prefix)
        tags = self.allowed_tags(message.tags)
        return [(command, [message.target, start + message.prefix + piece + end], tags)
                for piece in split_text(text, room)]

    def join(self, channel, key=''):
        self.write('JOIN', [channel, key] if key else [channel])

    def text_room(self, kind, target, prefix=''):
        return text_room(self.nick, kind, target, prefix, self.hostmask_length)

    def members(self, channel):
        return self.tracker.members(channel)

    def member(self, channel, nick):
        return self.tracker.find(channel, nick)

    def joined(self):
        return self.tracker.channel_names()

    def member_modes(self, channel, nick):
        return self.tracker.modes(channel, nick)

    def supports(self, feature):
        if feature in CLIENT_TAG_FEATURES:
            return self.client_tag_allowed('+' + feature)
        if feature in ('notice', 'private'):
            return True
        return feature in self.caps

    def client_tag_allowed(self, tag):
        if 'message-tags' not in self.caps:
            return False
        denied = self.isupport.get('CLIENTTAGDENY', '').split(',')
        name = tag.lstrip('+')
        if '-' + name in denied:
            return True
        return '*' not in denied and name not in denied

    def typing(self, target, state):
        if self.client_tag_allowed('+typing'):
            self.write('TAGMSG', [target], tags={'+typing': state})

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

    async def open(self):
        self.follow_sts()
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
            self.negotiating = True
            self.write('CAP', ['LS', '302'])
        if self.password:
            self.write('PASS', [self.password])
        self.write('NICK', [self.nickname])
        self.write('USER', [self.nickname, '0', '*', self.nickname])

    def allowed_tags(self, tags):
        allowed = {name: value for name, value in tags.items() if self.client_tag_allowed(name)}
        return allowed or None

    def write(self, command, params, tags=None):
        if not self.writer:
            return
        line = irctokens.build(command, params, tags=tags).format()
        self.writer.write(line.encode('utf-8', 'replace') + b'\r\n')

    def emit(self, event):
        self.queue.put_nowait(event)

    def is_me(self, nick):
        return self.casefold(nick) == self.casefold(self.nick)

    def is_channel(self, name):
        return is_channel(name, self.isupport.get('CHANTYPES') or CHANTYPES)

    def exempt(self, target):
        return False

    handlers = {
        'PING': 'on_ping', 'ERROR': 'on_error', 'CAP': 'on_cap',
        'AUTHENTICATE': 'on_authenticate', '900': 'on_logged_in', '903': 'on_sasl_success',
        '902': 'on_sasl_fail', '904': 'on_sasl_fail', '905': 'on_sasl_fail', '906': 'on_sasl_fail',
        '001': 'on_welcome', '005': 'on_isupport', '433': 'on_nick_in_use', '353': 'on_names',
        '376': 'on_registered', '422': 'on_registered', '731': 'on_monitor_offline',
        '352': 'on_who', '354': 'on_whox',
        'JOIN': 'on_join', 'PART': 'on_part', 'KICK': 'on_kick', 'QUIT': 'on_quit',
        'NICK': 'on_nick', 'PRIVMSG': 'on_privmsg', 'NOTICE': 'on_notice', 'TOPIC': 'on_topic',
        'INVITE': 'on_invite', 'MODE': 'on_mode', 'ACCOUNT': 'on_account', 'AWAY': 'on_away',
        'CHGHOST': 'on_chghost', 'SETNAME': 'on_setname', 'FAIL': 'on_standard_reply',
        'WARN': 'on_standard_reply', 'NOTE': 'on_standard_reply',
    }

    def handle(self, line):
        """Act on one line from the server."""
        tags = line.tags or {}
        if line.command.upper() == 'BATCH':
            self.on_batch(line)
            return
        batch = self.batches.get(tags.get('batch'))
        if batch is not None:
            batch['lines'].append(line)
            return
        if tags.get('label') in self.labels:
            self.answered(self.labels[tags['label']], [line])
            return
        if line.command in WHOIS_REPLIES and self.whois_reply(line):
            return
        name = self.handlers.get(line.command.upper())
        if name:
            getattr(self, name)(line)

    def on_batch(self, line):
        if not line.params:
            return
        ref = line.params[0]
        if ref.startswith('+') and len(line.params) > 1:
            self.batches[ref[1:]] = {'type': line.params[1], 'params': line.params[2:],
                                     'label': (line.tags or {}).get('label'), 'lines': []}
        elif ref.startswith('-'):
            batch = self.batches.pop(ref[1:], None)
            if batch is not None:
                self.batch_ended(batch)

    def batch_ended(self, batch):
        if batch['type'] == 'labeled-response' and batch['label'] in self.labels:
            self.answered(self.labels[batch['label']], batch['lines'])
        elif batch['type'] in ('netsplit', 'netjoin'):
            self.net_change(batch)
        else:
            for line in batch['lines']:
                self.handle(line)

    def net_change(self, batch):
        nicks = []
        for line in batch['lines']:
            if line.command.upper() == ('QUIT' if batch['type'] == 'netsplit' else 'JOIN'):
                nicks.append(line.hostmask.nickname)
                if batch['type'] == 'netsplit':
                    self.tracker.quit(line.hostmask.nickname)
                else:
                    self.on_join(line, emit=False)
            else:
                self.handle(line)
        if nicks:
            self.emit(Event(batch['type'], None, '', ' '.join(batch['params']),
                            data={'nicks': list(dict.fromkeys(nicks))}))

    async def whois(self, nick, timeout=10):
        key = self.casefold(nick)
        waiting = self.whois_waiting.get(key)
        if waiting is None:
            if not self.writer:
                return None
            waiting = asyncio.get_running_loop().create_future()
            self.whois_waiting[key] = waiting
            self.whois_lines[key] = []
            if 'labeled-response' in self.caps:
                self.next_label += 1
                label = 'ph{}'.format(self.next_label)
                self.labels[label] = key
                self.write('WHOIS', [nick], tags={'label': label})
            else:
                self.write('WHOIS', [nick])
        try:
            async with asyncio.timeout(timeout):
                return await asyncio.shield(waiting)
        except TimeoutError:
            self.logger.warning('the server never answered a WHOIS for {}'.format(nick))
            self.whois_done(key, None)
            return None

    def whois_reply(self, line):
        if len(line.params) < 2:
            return False
        key = self.casefold(line.params[1])
        if key not in self.whois_waiting or key in self.labels.values():
            return False
        self.whois_lines[key].append(line)
        if line.command in ('318', '401'):
            self.answered(key, [])
        return True

    def answered(self, key, lines):
        lines = self.whois_lines.get(key, []) + lines
        self.whois_done(key, parse_whois(lines, self.prefixes()))

    def whois_done(self, key, result):
        waiting = self.whois_waiting.pop(key, None)
        self.whois_lines.pop(key, None)
        for label in [label for label, owner in self.labels.items() if owner == key]:
            del self.labels[label]
        if waiting is not None and not waiting.done():
            waiting.set_result(result)

    def on_ping(self, line):
        self.write('PONG', line.params)

    def on_error(self, line):
        self.logger.warning('the server closed the connection: {}'.format(
            line.params[-1] if line.params else ''))

    def on_cap(self, line):
        subcommand, args = line.params[1], line.params[2:]
        if subcommand == 'LS' and self.negotiating:
            self.offered(args[-1])
            if 'sts' in self.server_caps and self.sts_offered():
                return
            if len(args) > 1 and args[0] == '*':
                return
            if self.request(self.wanted(during_registration=True)):
                return
        elif subcommand == 'NEW':
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
            if 'sasl' in acked and self.wants_sasl() and not self.sasl_logged_in:
                if self.start_sasl():
                    return
        elif subcommand == 'NAK':
            if self.wants_sasl() and 'sasl' in args[-1].split():
                self.logger.error("the server refused SASL, so the bot isn't logged in")
        else:
            return
        if self.negotiating:
            self.end_caps()

    def offered(self, caps):
        names = []
        for cap in caps.split():
            name, _, value = cap.partition('=')
            self.server_caps[name] = value
            names.append(name)
        return names

    def wanted(self, names=None, during_registration=False):
        names = self.server_caps if names is None else names
        wanted = [cap for cap in WANTED_CAPS if cap in names and cap not in self.caps]
        if self.wants_sasl() and not self.sasl_logged_in and 'sasl' in names:
            if self.mechanism():
                wanted.append('sasl')
            else:
                self.no_usable_sasl()
        elif self.wants_sasl() and during_registration and 'sasl' not in names:
            self.no_usable_sasl()
        return wanted

    def request(self, caps):
        if caps:
            self.write('CAP', ['REQ', ' '.join(caps)])
        return bool(caps)

    def wants_sasl(self):
        return bool(self.sasl_password) or self.client_cert

    def mechanism(self):
        offered = self.server_caps.get('sasl')
        listed = set(offered.upper().split(',')) if offered else None
        return sasl.choose(listed, bool(self.sasl_password), self.client_cert,
                           self.sasl_mechanism)

    def no_usable_sasl(self):
        offered = self.server_caps.get('sasl')
        what = ('it offers {}'.format(offered.replace(',', ', ')) if offered
                else "it doesn't offer SASL")
        self.logger.error("the bot can't log in with SASL here, so it isn't logged in: {}, "
                          "and the bot has {}".format(what, self.login_details()))

    def login_details(self):
        has = []
        if self.sasl_password:
            has.append('a password')
        if self.client_cert:
            has.append('a client certificate')
        if self.sasl_mechanism != 'auto':
            has.append('sasl_mechanism {}'.format(self.sasl_mechanism))
        return ' and '.join(has) or 'nothing to log in with'

    def start_sasl(self):
        name = self.mechanism()
        if name is None:
            self.no_usable_sasl()
            return False
        if name == 'EXTERNAL':
            self.sasl = sasl.External()
        elif name == 'SCRAM-SHA-256':
            self.sasl = sasl.ScramSha256(self.sasl_account, self.sasl_password)
        else:
            self.sasl = sasl.Plain(self.sasl_account, self.sasl_password)
        self.authenticating = True
        self.challenge = ''
        self.write('AUTHENTICATE', [name])
        return True

    def end_caps(self):
        self.negotiating = False
        self.write('CAP', ['END'])

    def on_authenticate(self, line):
        if not self.authenticating or self.sasl is None or not line.params:
            return
        piece = line.params[0]
        if piece != '+':
            self.challenge += piece
            if len(piece) == 400:
                return
        try:
            challenge = base64.b64decode(self.challenge)
            self.challenge = ''
            response = self.sasl.respond(challenge)
        except (ValueError, sasl.SaslError) as e:
            self.logger.error('SASL login as {} stopped: {}'.format(self.sasl_account, e))
            self.write('AUTHENTICATE', ['*'])
            return
        for chunk in sasl.encode(response):
            self.write('AUTHENTICATE', [chunk])

    def on_logged_in(self, line):
        if len(line.params) > 2:
            self.logged_in_as = line.params[2]

    def on_sasl_success(self, line):
        self.sasl_logged_in = True
        self.authenticating = False
        self.logger.info('logged in as {} with SASL {}'.format(
            self.logged_in_as or self.sasl_account, self.sasl.name))
        if self.negotiating:
            self.end_caps()

    def on_sasl_fail(self, line):
        reason = line.params[-1] if len(line.params) > 1 else 'no reason given'
        if isinstance(self.sasl, sasl.External):
            advice = 'check the client certificate is added to the account'
        else:
            advice = 'check sasl_account and sasl_password'
        self.logger.error('SASL login as {} failed ({}), {}'.format(
            self.sasl_account, reason, advice))
        self.authenticating = False
        if self.negotiating:
            self.end_caps()

    def load_sts(self):
        try:
            policies = read_json(self.sts_path, {})
        except ValueError:
            self.logger.warning("couldn't read {}, so STS policies start afresh".format(
                self.sts_path))
            return {}
        return policies if isinstance(policies, dict) else {}

    def save_sts(self):
        if self.sts_path:
            write_json(self.sts_path, self.sts_policies)

    def follow_sts(self):
        policy = self.sts_policies.get(self.server.lower())
        if self.ssl_context is not None or not policy:
            return
        if policy.get('expires', 0) < time.time():
            del self.sts_policies[self.server.lower()]
            self.save_sts()
            return
        self.logger.info('{} asked to only be reached over TLS, so connecting to port {} '
                         'with TLS'.format(self.server, policy['port']))
        self.port = policy['port']
        self.ssl_context = ssl.create_default_context()

    def sts_offered(self):
        """Act on sts in CAP LS. True if the bot is reconnecting with TLS."""
        values = dict(part.partition('=')[::2] for part in self.server_caps['sts'].split(','))
        if self.ssl_context is None:
            port = values.get('port', '')
            if not port.isdigit():
                return False
            self.logger.info('{} asks for TLS on port {}, reconnecting'.format(self.server, port))
            self.port = int(port)
            self.ssl_context = ssl.create_default_context()
            self.sts_upgrade = True
            if self.writer:
                self.writer.close()
            return True
        duration = values.get('duration', '')
        if duration.isdigit():
            if int(duration) == 0:
                self.sts_policies.pop(self.server.lower(), None)
            else:
                self.sts_policies[self.server.lower()] = {
                    'port': self.port, 'expires': time.time() + int(duration)}
            self.save_sts()
        return False

    def on_welcome(self, line):
        self.registered = True
        self.negotiating = False
        self.nick = line.params[0]
        self.welcomed()
        self.emit(Event('connected'))

    def on_registered(self, line):
        if self.casefold(self.nick) != self.casefold(self.nickname) and \
                'MONITOR' in self.isupport:
            self.write('MONITOR', ['+', self.nickname])

    def on_monitor_offline(self, line):
        if len(line.params) < 2 or self.casefold(self.nick) == self.casefold(self.nickname):
            return
        nicks = [target.partition('!')[0] for target in line.params[1].split(',')]
        if any(self.casefold(n) == self.casefold(self.nickname) for n in nicks):
            self.logger.info('{} is free again, taking it back'.format(self.nickname))
            self.write('NICK', [self.nickname])

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
            if name == 'BOT' and value and self.bot_mode:
                self.logger.info('setting bot mode +{}'.format(value))
                self.write('MODE', [self.nick, '+' + value])

    def on_nick_in_use(self, line):
        if self.registered:
            return
        taken = line.params[1]
        self.logger.warning('nickname {} in use, trying {}'.format(taken, taken + '_'))
        self.write('NICK', [taken + '_'])

    def prefixes(self):
        letters, _, symbols = self.isupport.get('PREFIX', '(qaohv)~&@%+').lstrip('(').partition(')')
        if not symbols or len(letters) != len(symbols):
            letters, symbols = 'qaohv', '~&@%+'
        return dict(zip(symbols, letters))

    def on_names(self, line):
        channel = line.params[2]
        if not self.tracker.has_channel(channel):
            return
        symbols = self.prefixes()
        for name in line.params[3].split():
            letters, hostmask = self.split_prefix(name, symbols)
            nick, _, rest = hostmask.partition('!')
            user, _, host = rest.partition('@')
            self.tracker.join(channel, nick, user=user or None, host=host or None)
            self.tracker.set_modes(channel, nick, letters)

    @staticmethod
    def split_prefix(name, symbols):
        bare = name.lstrip(''.join(symbols))
        return {symbols[s] for s in name[:len(name) - len(bare)]}, bare

    def who(self, channel):
        if 'WHOX' in self.isupport:
            self.write('WHO', [channel, '%tcuhnfar,' + WHOX_TOKEN])
        else:
            self.write('WHO', [channel])

    def on_who(self, line):
        if len(line.params) < 8:
            return
        _, channel, user, host, _, nick, flags, last = line.params[:8]
        self.who_reply(channel, nick, user, host, flags, None, last.partition(' ')[2])

    def on_whox(self, line):
        if len(line.params) < 9 or line.params[1] != WHOX_TOKEN:
            return
        _, _, channel, user, host, nick, flags, account, realname = line.params[:9]
        self.who_reply(channel, nick, user, host, flags, account, realname)

    def who_reply(self, channel, nick, user, host, flags, account, realname):
        if not self.tracker.has_channel(channel):
            return
        bot_letter = self.isupport.get('BOT')
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

    def on_join(self, line, emit=True):
        nick = line.hostmask.nickname
        channel = line.params[0]
        if self.is_me(nick):
            self.tracker.add_channel(channel)
            if line.hostmask.username and line.hostmask.hostname:
                hostmask = '!{}@{}'.format(line.hostmask.username, line.hostmask.hostname)
                self.hostmask_length = len(hostmask.encode('utf-8'))
            self.who(channel)
        self.tracker.join(channel, nick, user=line.hostmask.username, host=line.hostmask.hostname)
        if len(line.params) >= 3:
            self.tracker.update(nick, realname=line.params[2])
            self.logged_in(nick, line.params[1])
        if emit:
            self.emit(Event('join', self.source(line), channel, tags=self.tags(line)))

    def logged_in(self, nick, account):
        if account in ('*', '0', ''):
            self.tracker.log_out(nick)
        else:
            self.tracker.update(nick, account=account)

    def leave(self, channel, nick):
        if self.is_me(nick):
            self.tracker.remove_channel(channel)
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
            if self.casefold(new) == self.casefold(self.nickname):
                self.logger.info('got the nick {} back'.format(new))
                if 'MONITOR' in self.isupport:
                    self.write('MONITOR', ['-', self.nickname])
        self.emit(Event('nick', self.source(line), '', tags=self.tags(line),
                        data={'new_nick': new}))

    def on_account(self, line):
        if line.params:
            self.logged_in(line.hostmask.nickname, line.params[0])

    def on_away(self, line):
        self.tracker.update(line.hostmask.nickname, away=bool(line.params))

    def on_chghost(self, line):
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
        if len(line.params) > 1:
            self.emit(Event('invite', self.source(line), line.params[1], tags=self.tags(line),
                            data={'invited': line.params[0]}))

    def on_mode(self, line):
        if len(line.params) > 1 and self.is_channel(line.params[0]):
            self.track_modes(line.params[0], line.params[1], line.params[2:])
        if line.source and '!' in line.source:
            self.emit(Event('mode', self.source(line), line.params[0], tags=self.tags(line),
                            data={'modes': line.params[1:]}))

    def track_modes(self, channel, changes, args):
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
        if len(line.params) < 3:
            return
        command, code, description = line.params[0], line.params[1], line.params[-1]
        level = {'FAIL': 'error', 'WARN': 'warning'}.get(line.command.upper(), 'info')
        context = ' '.join(line.params[2:-1])
        getattr(self.logger, level)('the server said {} {}{}: {}'.format(
            command, code, ' ({})'.format(context) if context else '', description))

    @staticmethod
    def last(line, index):
        return line.params[index] if len(line.params) > index else ''

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
        if not line.source or '!' not in line.source or len(line.params) < 2:
            return
        if line.params[1].startswith('\x01'):
            return
        self.emit(Event('message', self.source(line), line.params[0], line.params[1], 'notice',
                        dict(line.tags or {})))

    ctcp_interval = 2.0

    def answer_ctcp(self, nick, ctcp, rest):
        if ctcp not in ('VERSION', 'PING'):
            return
        now = time.monotonic()
        if now - self.last_ctcp < self.ctcp_interval:
            self.logger.debug('not answering a CTCP {} from {}, one was answered just now'.format(
                ctcp, nick))
            return
        self.last_ctcp = now
        if ctcp == 'VERSION':
            self.write('NOTICE', [nick, '\x01VERSION pinhook {}\x01'.format(__version__)])
        elif ctcp == 'PING':
            self.write('NOTICE', [nick, '\x01PING {}\x01'.format(rest)])


class TwitchTransport(TwitchIdentity, IrcTransport):
    """Twitch chat, which is IRC with its own capabilities and rules.

    Twitch takes 20 lines in any 30 seconds, and one a second in each channel where
    the bot isn't a moderator or VIP. It splits nothing itself and allows 500
    characters a message, drops a message identical to the last one, and has no
    notices or private messages from bots.
    """
    name = 'twitch'
    asks_for_caps = False
    limits = Limits(burst=20, interval=1.5, per_target=1.0)
    handlers = {**IrcTransport.handlers, 'USERSTATE': 'on_userstate'}
    max_length = 500
    repeat_window = 30
    repeat_mark = ' \U000E0000'

    def reset(self):
        super().reset()
        self.privileged = set()
        self.recent = {}
        self.badges_seen = OrderedDict()

    def welcomed(self):
        self.logger.info('requesting permissions')
        for cap in ('twitch.tv/membership', 'twitch.tv/tags', 'twitch.tv/commands'):
            self.write('CAP', ['REQ', cap])

    def supports(self, feature):
        if feature in ('notice', 'private'):
            return False
        return super().supports(feature)

    def who(self, channel):
        pass

    def exempt(self, target):
        return self.casefold(target) in self.privileged

    @staticmethod
    def badges(tags):
        names = {badge.partition('/')[0] for badge in (tags.get('badges') or '').split(',')
                 if badge}
        if tags.get('mod') == '1':
            names.add('moderator')
        return names

    def on_userstate(self, line):
        if not line.params:
            return
        key = self.casefold(line.params[0])
        if self.badges(line.tags or {}) & {'broadcaster', 'moderator', 'vip'}:
            self.privileged.add(key)
        else:
            self.privileged.discard(key)

    def on_privmsg(self, line):
        if line.source and len(line.params) >= 2 and self.is_channel(line.params[0]):
            badges = self.badges(line.tags or {})
            nick, channel = line.hostmask.nickname, line.params[0]
            self.tracker.set_mode(channel, nick, 'o', bool(badges & {'broadcaster', 'moderator'}))
            self.tracker.set_mode(channel, nick, 'v', 'vip' in badges)
            key = (self.casefold(channel), self.casefold(nick))
            self.badges_seen[key] = frozenset(badges)
            self.badges_seen.move_to_end(key)
            while len(self.badges_seen) > self.badges_kept:
                self.badges_seen.popitem(last=False)
        super().on_privmsg(line)

    badges_kept = 10000

    def source(self, line):
        user_id = (line.tags or {}).get('user-id')
        if user_id and line.source:
            self.tracker.update(line.hostmask.nickname, account=user_id)
        return super().source(line)

    def member_badges(self, channel, nick):
        return self.badges_seen.get((self.casefold(channel), self.casefold(nick)), frozenset())

    def text_room(self, kind, target, prefix=''):
        start = '/me ' if kind == 'action' else ''
        return max(self.max_length - len(start + prefix + self.repeat_mark), 64)

    def lines(self, message, text):
        if message.kind == 'notice' and not self.is_channel(message.target):
            self.logger.debug("twitch doesn't deliver notices to people, dropping one to "
                              "{}".format(message.target))
            return []
        start = '/me ' if message.kind == 'action' else ''
        room = self.text_room(message.kind, message.target, message.prefix)
        return [('PRIVMSG', [message.target,
                             self.unrepeat(message.target, start + message.prefix + piece)], None)
                for piece in split_text(text, room, chars=True)]

    def unrepeat(self, target, line):
        key = self.casefold(target)
        now = time.monotonic()
        last = self.recent.get(key)
        if last and now - last[1] < self.repeat_window and \
                last[0].removesuffix(self.repeat_mark) == line and \
                not last[0].endswith(self.repeat_mark):
            line += self.repeat_mark
        self.recent[key] = (line, now)
        return line


def parse_whois(lines, symbols):
    """A Whois from the server's WHOIS replies, or None for no such nick."""
    found = {}
    for line in lines:
        p = line.params
        if line.command == '401':
            return None
        if line.command == '311' and len(p) >= 6:
            found.update(nick=p[1], user=p[2], host=p[3], realname=p[5])
        elif line.command == '319' and len(p) >= 3:
            channels = found.setdefault('channels', [])
            channels.extend(name.lstrip(''.join(symbols)) for name in p[2].split())
        elif line.command == '330' and len(p) >= 3:
            found['account'] = p[2]
        elif line.command == '301' and len(p) >= 3:
            found['away'] = p[2]
        elif line.command == '312' and len(p) >= 3:
            found['server'] = p[2]
        elif line.command == '317' and len(p) >= 3 and p[2].isdigit():
            found['idle'] = int(p[2])
        elif line.command == '313':
            found['operator'] = True
        elif line.command == '335':
            found['is_bot'] = True
        elif line.command == '671':
            found['secure'] = True
    if 'nick' not in found:
        return None
    found['channels'] = tuple(found.get('channels', ()))
    return Whois(**found)


def text_room(nick, kind, target, prefix='', hostmask_length=HOSTMASK_GUESS):
    """How many bytes of text fit in one message to target, after the server adds who sent it."""
    command = 'NOTICE' if kind == 'notice' else 'PRIVMSG'
    start, end = ('\x01ACTION ', '\x01') if kind == 'action' else ('', '')
    relayed = ':{} {} {} :{}{}{}\r\n'.format(nick, command, target, start, prefix, end)
    return max(512 - len(relayed.encode()) - hostmask_length, 64)


def split_text(text, room, chars=False):
    """Split text into lines of at most room bytes of utf-8, or room characters if chars,
    at spaces where it can."""
    def size(s):
        return len(s) if chars else len(s.encode('utf-8'))

    pieces = []
    for line in text.splitlines():
        while size(line) > room:
            fits = room if chars else len(line.encode('utf-8')[:room].decode('utf-8', 'ignore'))
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
