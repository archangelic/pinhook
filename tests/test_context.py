import warnings

import pytest

from pinhook import plugin
from pinhook.testing import Sent, TestBot


def plugins(tmp_path, code):
    (tmp_path / 'ctx.py').write_text("import pinhook.plugin as p\n" + code)
    return str(tmp_path)


def test_reply_sends_straight_away(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, (
        "@p.command('!count')\n"
        "def count(msg):\n"
        "    msg.reply('one')\n"
        "    msg.reply('two\\nthree')\n"
        "    msg.reply(['four', 'five', 'six'])\n"
    )))
    assert bot.say('!count') == ['one', 'two', 'three', 'four', 'five', 'six']
    # same flood protection as a returned reply: 4 lines at once, then one every 2 seconds
    assert bot.pauses == [2, 2]


def test_reply_to_a_private_message_goes_to_the_sender(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, (
        "@p.command('!hi')\n"
        "def hi(msg): msg.reply('hi there')\n"
    )))
    assert bot.private('!hi', nick='mal') == ['hi there']


def test_send_goes_somewhere_else(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, (
        "@p.command('!tell')\n"
        "def tell(msg): msg.send('#games', 'dice night is friday')\n"
    )))
    assert bot.say('!tell') == []
    assert bot.sent == [Sent('message', '#games', 'dice night is friday')]


def test_action_with_one_argument_replies(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, (
        "@p.command('!dance')\n"
        "def dance(msg):\n"
        "    msg.action('dances')\n"
        "    msg.action('#party', 'dances here too')\n"
    )))
    bot.say('!dance')
    assert bot.sent == [Sent('action', '#test', 'dances'),
                        Sent('action', '#party', 'dances here too')]


def test_notice_with_one_argument_goes_to_the_sender(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, (
        "@p.command('!psst')\n"
        "def psst(msg):\n"
        "    msg.notice('psst')\n"
        "    msg.notice('#test', 'everyone, psst')\n"
    )))
    bot.say('!psst', nick='mal')
    assert bot.sent == [Sent('notice', 'mal', 'psst'), Sent('notice', '#test', 'everyone, psst')]


def test_wrong_number_of_arguments_is_a_plugin_error(tmp_path):
    from pinhook.testing import PluginError
    bot = TestBot(plugin_dir=plugins(tmp_path, (
        "@p.command('!oops')\n"
        "def oops(msg): msg.action('a', 'b', 'c')\n"
    )))
    with pytest.raises(PluginError) as error:
        bot.say('!oops')
    assert 'expected (text) or (target, text), got 3 arguments' in str(error.value.__cause__)


def test_account_and_is_private(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, (
        "@p.command('!whoami')\n"
        "def whoami(msg): return p.message('{} {}'.format(msg.account, msg.is_private))\n"
    )))
    assert bot.say('!whoami', account='mal') == ['mal False']
    assert bot.private('!whoami') == ['None True']


# deprecations

def test_msg_bot_still_works_but_warns(tmp_path, caplog):
    bot = TestBot(plugin_dir=plugins(tmp_path, (
        "@p.command('!nick')\n"
        "def nick(msg): return p.message(msg.bot.bot_nick)\n"
    )))
    with pytest.warns(DeprecationWarning, match='msg.bot is deprecated'):
        assert bot.say('!nick') == ['testbot']
    with pytest.warns(DeprecationWarning):
        bot.say('!nick')
    # logged once per bot, so a busy bot's log isn't flooded
    assert caplog.text.count('msg.bot is deprecated') == 1


def test_removed_decorators_say_what_replaces_them():
    with pytest.raises(RuntimeError, match=r"@register was removed .* use @command\('!old'\)"):
        plugin.register('!old')
    with pytest.raises(RuntimeError, match=r"@ops was removed .* use @command\('!older', ops=True"):
        plugin.ops('!older', 'ops only')


def test_returning_output_still_works_with_no_warnings(tmp_path):
    bot = TestBot(plugin_dir=plugins(tmp_path, (
        "@p.command('!old')\n"
        "def old(msg): return p.message(msg.nick)\n"
    )))
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        assert bot.say('!old', nick='mal') == ['mal']
