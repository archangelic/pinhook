import logging

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
