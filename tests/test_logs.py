import json
import logging

import pytest

from pinhook import log
from pinhook.testing import TestBot


def audit_lines(caplog):
    return [r.getMessage() for r in caplog.records if getattr(r, 'audit', False)]


def test_changes_to_who_can_do_what_are_audit_lines(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    bot = TestBot(ops=['$a:mal'], data_dir=str(tmp_path))
    bot.say('!op ana', nick='mal', account='mal')
    bot.say('!ban spammer', nick='mal', account='mal')
    bot.say('!disable help', nick='mal', account='mal')
    assert audit_lines(caplog) == [
        'mal (account mal) ran !op ana: ana added as op',
        "mal (account mal) ran !ban spammer: banned spammer (nick only, they haven't spoken "
        "since the bot started)",
        "mal (account mal) ran !disable help: 'help' not found",
    ]


def test_commands_that_change_nothing_and_non_ops_arent_audited(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    bot = TestBot(ops=['$a:mal'], data_dir=str(tmp_path))
    bot.say('!ops', nick='mal', account='mal')
    bot.say('!banlist', nick='mal', account='mal')
    bot.say('!ban mal', nick='ana')
    assert audit_lines(caplog) == []


def test_log_file_dash_logs_to_stdout_and_only_there(tmp_path, capsys):
    bot = TestBot(log_file='-', data_dir=str(tmp_path))
    bot.logger.warning('to stdout')
    out, err = capsys.readouterr()
    assert out.endswith(' - WARNING - bot.testbot - test_logs - to stdout\n')
    assert 'to stdout' not in err
    assert not (tmp_path / '-').exists()


def test_json_logs_are_one_object_per_line(tmp_path, capsys):
    bot = TestBot(log_file='-', log_format='json', ops=['$a:mal'], data_dir=str(tmp_path))
    bot.logger.info('hello')
    bot.say('!op ana', nick='mal', account='mal')
    try:
        raise ValueError('oops')
    except ValueError:
        bot.logger.exception('it broke')
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    hello = next(line for line in lines if line['message'] == 'hello')
    assert set(hello) == {'time', 'level', 'bot', 'message'}
    assert hello['level'] == 'info' and hello['bot'] == 'testbot'
    assert hello['time'].endswith('+00:00')
    audit = [line for line in lines if line.get('audit')]
    assert [line['message'] for line in audit] == [
        'mal (account mal) ran !op ana: ana added as op']
    assert lines[-1]['message'] == 'it broke'
    assert lines[-1]['error'].endswith('ValueError: oops')


def test_json_logs_are_masked(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(log, 'secrets', set())
    log.hide('hunter2')
    bot = TestBot(log_file='-', log_format='json', data_dir=str(tmp_path))
    bot.logger.info('password is hunter2')
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['message'] == 'password is ***'


def test_an_unknown_log_format_is_refused(tmp_path):
    with pytest.raises(ValueError, match='log_format must be text or json'):
        TestBot(log_format='xml', data_dir=str(tmp_path))
