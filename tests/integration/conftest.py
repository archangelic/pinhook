"""Helpers for tests against a real Ergo IRC server.

They only run when PINHOOK_ERGO is set to the server's address, for example:

    tests/integration/ergo.sh
    PINHOOK_ERGO=127.0.0.1 pytest tests/integration
"""
import contextlib
import json
import os
import select
import shutil
import socket
import subprocess
import sys
import time

import pytest

HOST = os.environ.get('PINHOOK_ERGO')
PASSWORDS = {'malacct': 'correcthorse-mal', 'trollacct': 'correcthorse-troll'}


def pytest_collection_modifyitems(config, items):
    if HOST:
        return
    skip = pytest.mark.skip(reason='set PINHOOK_ERGO to run tests against a real Ergo server')
    for item in items:
        if 'integration' in str(item.fspath):
            item.add_marker(skip)


class NickTaken(Exception):
    pass


class User:
    """Someone on the IRC server, talking over a plain socket."""

    def __init__(self, nick, account=None):
        self.nick = nick
        self.sock = socket.create_connection((HOST, 6667), timeout=10)
        self.buf = b''
        self.lines = []
        self.send('NICK ' + nick)
        self.send('USER {0} 0 * :{0}'.format(nick))
        if ' 433 ' in self.wait_for_any(' 001 ', ' 433 '):
            self.close()
            raise NickTaken(nick)
        if account:
            self.send('PRIVMSG NickServ :IDENTIFY {} {}'.format(account, PASSWORDS[account]))
            self.wait_for("You're now logged in")

    def send(self, line):
        self.sock.sendall((line + '\r\n').encode())

    def read(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([self.sock], [], [], max(0, end - time.time()))
            if not ready:
                continue
            data = self.sock.recv(65536)
            if not data:
                break
            self.buf += data
            while b'\r\n' in self.buf:
                raw, self.buf = self.buf.split(b'\r\n', 1)
                line = raw.decode('utf-8', 'replace')
                if line.startswith('PING'):
                    self.send('PONG' + line[4:])
                self.lines.append(line)

    def wait_for_any(self, *texts, seconds=10):
        end = time.time() + seconds
        while time.time() < end:
            for i, line in enumerate(self.lines):
                if any(text in line for text in texts):
                    del self.lines[:i + 1]
                    return line
            self.read(0.1)
        raise AssertionError('{} never saw any of {!r}'.format(self.nick, texts))

    def wait_for(self, text, seconds=10):
        """Read until a line containing text arrives, and return it."""
        end = time.time() + seconds
        while time.time() < end:
            for i, line in enumerate(self.lines):
                if text in line:
                    del self.lines[:i + 1]
                    return line
            self.read(0.1)
        raise AssertionError('{} never saw {!r}'.format(self.nick, text))

    def join(self, channel):
        self.send('JOIN ' + channel)
        self.wait_for(' 366 ')

    def say(self, text, target, bot, seconds=1.5):
        """Send a message, and return what the bot sent back as (command, target, text)."""
        self.read(0.05)
        self.lines.clear()
        self.send('PRIVMSG {} :{}'.format(target, text))
        self.read(seconds)
        return heard(self.lines, bot)

    def close(self):
        # wait for the server to drop the connection, so the nick is free again
        with contextlib.suppress(OSError):
            self.send('QUIT')
            end = time.time() + 3
            while time.time() < end and select.select([self.sock], [], [], 0.1)[0]:
                if not self.sock.recv(65536):
                    break
            self.sock.close()


def heard(lines, bot):
    out = []
    for line in lines:
        if not line.startswith(':{}!'.format(bot)):
            continue
        parts = line.split(' ', 3)
        if len(parts) == 4 and parts[1] in ('PRIVMSG', 'NOTICE'):
            text = parts[3][1:] if parts[3].startswith(':') else parts[3]
            command = parts[1]
            if text.startswith('\x01ACTION '):
                command, text = 'ACTION', text[len('\x01ACTION '):].rstrip('\x01')
            out.append((command, parts[2], text))
    return out


def register(account, password):
    """Register an account named after a nick, unless it already is."""
    try:
        u = User(account)
    except NickTaken:
        # ergo keeps registered nicks for their account, so it's there from a past run
        return
    u.send('PRIVMSG NickServ :REGISTER ' + password)
    u.wait_for('NickServ')
    u.close()


@pytest.fixture(scope='session')
def accounts():
    """The test accounts on the server, registered the first time."""
    for account, password in PASSWORDS.items():
        register(account, password)
    return PASSWORDS


@pytest.fixture
def names(request):
    """A bot nick and channel just for this test, so tests can't see each other."""
    tag = str(abs(hash(request.node.name)) % 100000)
    return 'itbot' + tag, '#it' + tag


@pytest.fixture
def users():
    made = []

    def make(nick, account=None, channel=None):
        u = User(nick, account)
        if channel:
            u.join(channel)
        made.append(u)
        return u
    yield make
    for u in made:
        u.close()


class BotProcess:
    def __init__(self, folder, process):
        self.folder = folder
        self.process = process

    def log(self):
        logs = os.path.join(self.folder, 'bot', 'logs')
        if not os.path.isdir(logs):
            # the bot hasn't started logging yet
            return ''
        return ''.join(open(os.path.join(logs, f)).read() for f in os.listdir(logs))

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)


def pinhook_command():
    beside_python = os.path.join(os.path.dirname(sys.executable), 'pinhook')
    return beside_python if os.path.exists(beside_python) else shutil.which('pinhook')


@pytest.fixture
def start_bot(tmp_path, names):
    """Start a bot with the real pinhook command and a config file, in its own bot_dir."""
    started = []

    def start(watcher, plugins=None, env=None, wait=True, **options):
        nick, channel = names
        bot_dir = tmp_path / 'bot'
        (bot_dir / 'plugins').mkdir(parents=True, exist_ok=True)
        for name, code in (plugins or {}).items():
            (bot_dir / 'plugins' / (name + '.py')).write_text(code)
        config = dict(nickname=nick, server=HOST, port=6667, channels=[channel],
                      bot_dir=str(bot_dir), log_level='info')
        config.update(options)
        (tmp_path / 'config.json').write_text(json.dumps(config))
        run = tmp_path / 'run'
        run.mkdir(exist_ok=True)
        process = subprocess.Popen([pinhook_command(), str(tmp_path / 'config.json')], cwd=str(run),
                                   env=dict(os.environ, **(env or {})),
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        bot = BotProcess(str(tmp_path), process)
        started.append(bot)
        if wait:
            # the bot's own JOIN, not one from a user who joined before it. Its nick can
            # have something added if the nick was in use
            while not watcher.wait_for(' JOIN ', seconds=15).startswith(':' + nick):
                pass
        return bot
    yield start
    for bot in started:
        bot.stop()
