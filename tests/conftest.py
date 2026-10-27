import logging
from types import SimpleNamespace
from unittest import mock

import pytest

from pinhook import bot as pinhook_bot
from pinhook import plugin


@pytest.fixture(autouse=True)
def clear_plugins():
    # plugin registries are module level, so clear them between tests
    plugin.cmds.clear()
    plugin.lstnrs.clear()
    plugin.plugins.clear()
    yield
    plugin.cmds.clear()
    plugin.lstnrs.clear()
    plugin.plugins.clear()
    # close log files the bots opened during the test
    for name in list(logging.root.manager.loggerDict):
        if name == 'bot' or name.startswith('bot.'):
            logger = logging.getLogger(name)
            for handler in list(logger.handlers):
                if isinstance(handler, logging.FileHandler):
                    logger.removeHandler(handler)
                    handler.close()


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    # record flood protection pauses instead of waiting for them
    calls = []
    monkeypatch.setattr(pinhook_bot, 'time', SimpleNamespace(sleep=calls.append))
    return calls


@pytest.fixture
def plugin_dir(tmp_path):
    def write_plugin(name, code):
        (tmp_path / '{}.py'.format(name)).write_text(code)
        return str(tmp_path)
    return write_plugin


@pytest.fixture
def make_bot(tmp_path):
    # builds a Bot without connecting, with a fake channel and connection
    def build(plugin_path=None, **kwargs):
        kwargs.setdefault('plugin_dir', plugin_path or str(tmp_path / 'plugins'))
        kwargs.setdefault('log_file', str(tmp_path / 'bot.log'))
        b = pinhook_bot.Bot(['#test'], 'pinbot', 'localhost', **kwargs)
        b.channels['#test'] = mock.MagicMock()
        b.channels['#test'].users.return_value = []
        return b
    return build


@pytest.fixture
def conn():
    c = mock.MagicMock()
    c.get_nickname.return_value = 'pinbot'
    return c


def event(nick, target, text, type='pubmsg'):
    return SimpleNamespace(
        source=SimpleNamespace(nick=nick, user='user'),
        target=target,
        arguments=[text],
        type=type,
    )
