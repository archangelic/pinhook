import logging

import pytest

from pinhook import bot as pinhook_bot


PING_PLUGIN = (
    "import pinhook.plugin as p\n"
    "@p.command('!ping')\n"
    "def ping(msg): return p.message('pong')\n"
)


ECHO_PLUGIN = (
    "import pinhook.plugin as p\n"
    "@p.listener('echo')\n"
    "def echo(msg): return p.message(msg.text)\n"
)


def test_log_level_is_case_insensitive(make_bot):
    b = make_bot(log_level='INFO')
    assert b.logger.level == logging.INFO


def test_log_level_accepts_warn_and_warning(make_bot):
    assert make_bot(log_level='warn').logger.level == logging.WARNING
    assert make_bot(log_level='warning').logger.level == logging.WARNING


def test_bad_log_level_gives_clear_error(make_bot):
    with pytest.raises(ValueError, match='log_level must be one of'):
        make_bot(log_level='verbose')


def test_log_level_off_disables_logging(make_bot, tmp_path, caplog):
    b = make_bot(log_level='off')
    b.logger.error('should not appear')
    assert 'should not appear' not in caplog.text
    assert not (tmp_path / 'bot.log').exists()


def test_logging_works_again_after_off(make_bot, caplog):
    make_bot(log_level='off')
    b = make_bot(log_level='info')
    b.logger.error('should appear')
    assert 'should appear' in caplog.text


MESSAGE_ARGS = dict(bot=None, channel='#test', nick='mal', user='user', botnick='pinbot', ops=[],
                    logger=None, action=None, privmsg=None, notice=None, msg_type='message')


def test_message_needs_cmd_or_text():
    with pytest.raises(TypeError, match='missing cmd or text'):
        pinhook_bot.Bot.Message(**MESSAGE_ARGS)


def test_message_with_cmd_and_text_is_fine():
    msg = pinhook_bot.Bot.Message(cmd='!ping', arg='', text='!ping', **MESSAGE_ARGS)
    assert msg.cmd == '!ping' and msg.text == '!ping'


def test_several_bots_do_not_duplicate_log_lines(make_bot, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_bot(log_file='same.log')
    b = make_bot(log_file=str(tmp_path / 'same.log'))  # same file, absolute path
    b.logger.warning('one line please')
    assert (tmp_path / 'same.log').read_text().count('one line please') == 1


def test_each_bot_logs_to_its_own_file(tmp_path):
    alpha = pinhook_bot.Bot(['#test'], 'alpha', 'localhost', plugin_dir=str(tmp_path / 'p'),
                            log_file=str(tmp_path / 'alpha.log'))
    beta = pinhook_bot.Bot(['#test'], 'beta', 'localhost', plugin_dir=str(tmp_path / 'p'),
                           log_file=str(tmp_path / 'beta.log'))
    alpha.logger.warning('from alpha')
    beta.logger.warning('from beta')
    assert 'from alpha' in (tmp_path / 'alpha.log').read_text()
    assert 'from beta' not in (tmp_path / 'alpha.log').read_text()
    assert 'from beta' in (tmp_path / 'beta.log').read_text()
    assert 'from alpha' not in (tmp_path / 'beta.log').read_text()


def test_each_bot_has_its_own_log_level(tmp_path, caplog):
    quiet = pinhook_bot.Bot(['#test'], 'quiet', 'localhost', plugin_dir=str(tmp_path / 'p'),
                            log_file=str(tmp_path / 'q.log'), log_level='off')
    loud = pinhook_bot.Bot(['#test'], 'loud', 'localhost', plugin_dir=str(tmp_path / 'p'),
                           log_file=str(tmp_path / 'l.log'), log_level='debug')
    quiet.logger.error('quiet bot')
    loud.logger.debug('loud bot')
    assert 'quiet bot' not in caplog.text
    assert 'loud bot' in caplog.text


def test_unknown_option_warns_with_suggestion(make_bot, caplog):
    make_bot(ssl_requred=True)
    assert "unknown option 'ssl_requred' ignored, did you mean 'ssl_required'?" in caplog.text


def test_known_options_do_not_warn(make_bot, caplog):
    make_bot(ssl_verify=False, bot_mode=False, cmd_prefix='?')
    assert 'unknown option' not in caplog.text


def test_twitch_bot_warns_about_irc_only_options(tmp_path, caplog):
    pinhook_bot.TwitchBot('pinbot', '#chan', 'secret', plugin_dir=str(tmp_path / 'p'),
                          log_file=str(tmp_path / 't.log'), ns_pass='x')
    assert "unknown option 'ns_pass' ignored" in caplog.text
