"""A bot folder a 1.12 bot left behind, its data written by 1.12's own code, runs on 2.0
with nothing lost."""
import os
import shutil

from pinhook.config import load_bot
from pinhook.transport.base import Source

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'bot-1.12')


def old_bot(tmp_path):
    folder = tmp_path / 'oldbot'
    shutil.copytree(FIXTURE, folder)
    return folder, load_bot(str(folder / 'config.yaml'), log_level='off')


def test_bans_from_1_12_still_apply(tmp_path):
    folder, bot = old_bot(tmp_path)
    assert bot.banned_users == ['$a:troll', '*!*spam@203.0.113.7']
    assert bot.ignores(Source('newnick', 'u', 'h', 'troll'))
    assert bot.ignores(Source('anyone', 'spam', '203.0.113.7'))
    assert not bot.ignores(Source('ana', 'ana', 'example.com'))


def test_plugin_stores_from_1_12_are_read(tmp_path):
    folder, bot = old_bot(tmp_path)
    assert bot.store('karma')['scores'] == {'ana': 3, 'bob': 1}


def test_the_1_12_plugin_and_its_settings_load(tmp_path):
    folder, bot = old_bot(tmp_path)
    assert 'karma' in bot.registry.plugins
    assert bot.config_for('karma')['label'] == 'points'
    assert os.path.normpath(bot.data_dir) == str(folder / 'data')
