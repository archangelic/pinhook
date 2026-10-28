import os

from pinhook import bot as pinhook_bot

from conftest import event


def new_bot(**options):
    options.setdefault('log_level', 'info')
    return pinhook_bot.Bot(['#test'], 'pinbot', 'localhost', **options)


def files(folder):
    return sorted(str(p.relative_to(folder)) for p in folder.rglob('*'))


def test_without_bot_dir_files_go_where_they_did_in_1_11(tmp_path, monkeypatch, conn):
    monkeypatch.chdir(tmp_path)
    b = new_bot(ops=['mal'])
    b.channels['#test'] = conn
    b.process_event(conn, event('mal', '#test', '!ban troll'))
    assert files(tmp_path) == ['pinbot.bans.json', 'pinbot.log', 'plugins']
    assert b.data_dir == 'data'


def test_bot_dir_keeps_everything_in_one_folder(tmp_path, conn):
    b = new_bot(bot_dir=str(tmp_path / 'ph-bot'), ops=['mal'])
    b.channels['#test'] = conn
    b.process_event(conn, event('mal', '#test', '!ban troll'))
    assert files(tmp_path / 'ph-bot') == ['data', 'data/pinbot.bans.json', 'logs', 'logs/pinbot.log', 'plugins']
    assert b.data_dir == str(tmp_path / 'ph-bot' / 'data')


def test_bot_dir_loads_plugins_from_inside_it(tmp_path):
    (tmp_path / 'plugins').mkdir()
    (tmp_path / 'plugins' / 'hi.py').write_text("import pinhook.plugin as p\n@p.command('!hi')\ndef hi(msg): pass\n")
    from pinhook import plugin
    new_bot(bot_dir=str(tmp_path))
    assert '!hi' in plugin.cmds


def test_relative_options_are_inside_bot_dir(tmp_path):
    b = new_bot(bot_dir=str(tmp_path), plugin_dir='my-plugins', data_dir='stores', log_file='bot.log', ban_file='bans.json')
    assert b.plugin_dir == str(tmp_path / 'my-plugins')
    assert b.data_dir == str(tmp_path / 'stores')
    assert b.log_file == str(tmp_path / 'bot.log')
    assert b.ban_file == str(tmp_path / 'bans.json')


def test_absolute_options_stay_where_they_point(tmp_path):
    elsewhere = tmp_path / 'elsewhere'
    b = new_bot(bot_dir=str(tmp_path / 'ph-bot'), log_file=str(elsewhere / 'bot.log'), data_dir=str(elsewhere / 'data'))
    assert b.log_file == str(elsewhere / 'bot.log')
    assert b.data_dir == str(elsewhere / 'data')
    assert (elsewhere / 'bot.log').exists()


def test_home_folder_shortcut_works(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    b = new_bot(bot_dir='~/ph-bot')
    assert b.bot_dir == str(tmp_path / 'ph-bot')
    assert (tmp_path / 'ph-bot' / 'logs' / 'pinbot.log').exists()


def test_empty_ban_file_still_turns_saving_off(tmp_path):
    b = new_bot(bot_dir=str(tmp_path), ban_file='')
    assert b.ban_file is None


def test_twitch_bot_uses_the_same_layout(tmp_path):
    from unittest import mock
    with mock.patch('irc.connection.Factory'):
        b = pinhook_bot.TwitchBot('pinbot', '#chan', 'secret', bot_dir=str(tmp_path))
    assert b.log_file == os.path.join(str(tmp_path), 'logs', 'pinbot.log')
    assert b.ban_file == os.path.join(str(tmp_path), 'data', 'pinbot.bans.json')
