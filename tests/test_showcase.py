"""The showcase bot in tests/fixtures/showcase: every plugin feature, 1.x and 2.0, run
through TestBot. The same folder is for trying 2.0 on a real network."""
import os
import shutil

import pytest
import yaml
from click.testing import CliRunner

from pinhook.cli import cli
from pinhook.testing import PluginError, TestBot

SHOWCASE = os.path.join(os.path.dirname(__file__), 'fixtures', 'showcase')


@pytest.fixture
def bot(tmp_path):
    folder = tmp_path / 'showcase'
    shutil.copytree(SHOWCASE, folder)
    config = yaml.safe_load((folder / 'config.yaml').read_text())
    access = config['access']
    access['groups']['trusted'] = ['$a:ana']
    return TestBot(plugin_dir=str(folder / 'plugins'), recipe_dir=str(folder / 'recipes'),
                   ops=['$a:mal'], plugin_config=config['plugin_config'], access=access,
                   history={'channels': ['#test']})


def mal(bot, text):
    return bot.say(text, nick='mal', account='mal')


def test_the_showcase_config_checks_clean(tmp_path):
    folder = tmp_path / 'showcase'
    shutil.copytree(SHOWCASE, folder)
    result = CliRunner().invoke(cli, ['check', '--strict', str(folder / 'config.yaml')])
    assert result.exit_code == 0, result.output
    assert 'Loaded 2 plugins' in result.output and '4 recipes' in result.output


# 1.x

def test_1x_commands_and_replies(bot):
    assert bot.say('!legacy', nick='ana') == ['hello ana from 1.x']
    bot.say('!legacyaction')
    assert bot.sent[-1].kind == 'action' and bot.sent[-1].text == 'waves the 1.x way'
    assert bot.say('!legacylines') == ['first line', 'second line']


def test_1x_sending_as_it_goes(bot):
    bot.say('!legacysend', nick='ana')
    sent = [(s.kind, s.target, s.text) for s in bot.sent[-5:]]
    # the output queue takes turns between targets, so ana's notice follows #test's action
    assert sent == [('message', '#test', 'replied as I go'),
                    ('message', '#showcase-test', 'sent to #showcase-test'),
                    ('message', 'ana', 'a private message'), ('action', '#test', 'acts as I go'),
                    ('notice', 'ana', 'a notice')]


def test_1x_store_config_ops_hidden_and_details(bot):
    assert bot.say('!legacycount') == ['counted 1 with legacy']
    assert bot.say('!legacycount') == ['counted 2 with legacy']
    assert bot.say('!legacyops', nick='ana') == ['ops only, sorry']
    assert mal(bot, '!legacyops') == ['hello op']
    assert bot.say('!legacyhidden') == ['found the hidden one']
    assert 'legacyhidden' not in ' '.join(bot.private('!help', nick='ana'))
    assert bot.say('!legacywho a b', nick='ana') == [
        'nick=ana op=False private=False botnick=testbot people=4 cmd=!legacywho arg=a b']


def test_1x_msg_bot_and_listeners(bot):
    with pytest.warns(DeprecationWarning):
        assert bot.say('!legacybot') == ['bot is testbot']
    assert bot.say('ping legacy') == ['pong from a 1.x listener']


# 2.0

def test_typed_commands_and_aliases(bot):
    assert bot.say('!roll 2 20', nick='ana') == ['ana rolled 2d20']
    assert bot.say('!r', nick='ana') == ['ana rolled 1d6']
    assert bot.say('!types hi 3 1.5 yes b 7 and the rest') == ['hi 3 1.5 True b 7 and the rest']
    assert bot.say('!types hi three 1 no') == [
        'usage: types <word> <number> <ratio> <loud> [mode=a] [extra] [rest=] '
        '(number must be a whole number)']
    assert bot.private('!help r', nick='ana')[:2] == [
        '!roll -- roll dice, like roll 2 20', 'also !r']


def test_class_state_carries_across_reload(bot):
    assert bot.say('!reloads') == ['reloaded 0 times']
    mal(bot, '!reload')
    assert bot.say('!reloads') == ['reloaded 1 times']


def test_store_config_and_history(bot):
    assert bot.say('!count') == ['counted 1 with modern']
    bot.say('first', nick='ana')
    bot.say('second', nick='bob')
    assert bot.say('!history', nick='cat') == ['ana:first | bob:second | cat:!history']


def test_ways_to_answer(bot):
    bot.say('!thread', nick='ana')
    assert bot.sent[-1].text == 'ana: a threaded reply'
    bot.say('!private', nick='ana')
    assert bot.sent_to('ana')[-1] == 'just for you'
    bot.say('!say', nick='ana')
    sent = [(s.kind, s.target, s.text) for s in bot.sent[-4:]]
    assert sent == [('action', '#test', 'waves'), ('notice', 'ana', 'a notice for you'),
                    ('message', '#showcase-test', 'sent to #showcase-test'),
                    ('message', '#showcase-test', 'on two lines')]
    assert bot.say('!slow') == ['done slowly']


def test_who_members_whois_and_supports(bot):
    assert mal(bot, '!who') == [
        'nick=mal account=mal op=True chanop=False private=False addressed=False bot=testbot']
    assert bot.say('testbot: who', nick='ana')[0].endswith('addressed=True bot=testbot')
    assert bot.say('!members', nick='ana') == ['3 here, me=ana']
    assert bot.say('!whois ana') == ['ana account=None']
    assert bot.say('!whois nobody') == ['nobody']
    # TestBot's network has no client tags, so threaded replies start with the nick
    assert bot.say('!supports') == ['typing=False reply=False private=True notice=True']


def test_access_failures_and_limits(bot):
    assert bot.say('!secret', nick='bob') == ['ask an op']
    assert bot.say('!secret', nick='ana', account='ana') == ['the secret']
    assert bot.say('!admin', nick='ana') == []
    assert mal(bot, '!admin') == ['admin things']
    # TestBot fails a test when a plugin raises, after the error_msg is said
    with pytest.raises(PluginError, match='broken on purpose'):
        bot.say('!broken')
    assert bot.sent_to('#test')[-1] == 'that went wrong'
    assert bot.say('!sleepy') == []
    assert '!hidden' not in ' '.join(bot.private('!help', nick='mal', account='mal'))
    assert bot.say('!hidden') == ['found the hidden one']


def test_events_and_the_timer(bot):
    bot.event('join', nick='newbie')
    assert bot.sent[-1].text == 'welcome, newbie'
    bot.event('topic', nick='mal', text='game night')
    bot.event('nick', nick='newbie', new_nick='newbie_')
    bot.event('mode', nick='mal', modes=['+o', 'newbie_'])
    bot.event('kick', nick='mal', kicked='newbie_', text='bye')
    assert bot.say('!events') == [
        'join newbie, topic game night, nick newbie>newbie_, mode +o newbie_, kick newbie_']
    # it keeps the last five
    bot.event('part', nick='mal')
    assert bot.say('!events') == [
        'topic game night, nick newbie>newbie_, mode +o newbie_, kick newbie_, part mal']
    assert bot.say('testbot: hello', nick='ana') == ['hello ana, you addressed me']
    assert [(s.target, s.text) for s in bot.tick(1800)] == [('#showcase-test', 'the timer fired')]


# recipes

def test_recipes(bot):
    assert bot.say('!gamenight', nick='ana')[0].startswith('Tonight: ana rolled 2d6. ')
    bot.say('!addgame wingspan')
    assert bot.say('!addgame Azul') == ['games: Azul, wingspan']
    assert bot.say('!eachgame') == ['* WINGSPAN', '* AZUL']
    assert bot.say('!vip', nick='bob') == []
    assert bot.say('!vip', nick='ana', account='ana') == []
    mal(bot, '!allow vip ana')
    assert bot.say('!vip', nick='ana', account='ana') == ['welcome to the vip list, ana']
