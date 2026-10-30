"""Access control: open, restricted and ops-only levels, grants, denies and the chat commands."""
import json

import pytest

from pinhook import command
from pinhook.testing import Sent, TestBot
from pinhook.transport.base import Source

HEAD = 'from pinhook import Plugin, command, on, every\nimport pinhook.plugin as p\n'

WEATHER = '''
@command('weather', restricted=True, help='the weather')
async def weather(ctx):
    await ctx.reply('sunny')

@command('forecast', help='the forecast')
async def forecast(ctx):
    await ctx.reply('rain later')
'''
QUOTES = '''
@command('quote', help='a quote')
async def quote(ctx):
    await ctx.reply('to be or not to be')

@p.listener('echo')
def echo(msg):
    return p.message('heard ' + msg.text)
'''
ADMIN = '''
@command('shutdown', ops=True, help='stop everything')
async def shutdown(ctx):
    await ctx.reply('bye')
'''


def bot_with(tmp_path, access=None, **files):
    for name, code in files.items():
        (tmp_path / (name + '.py')).write_text(HEAD + code)
    return TestBot(plugin_dir=str(tmp_path), ops=['$a:mal'], access=access)


def op(bot, text):
    return bot.say(text, nick='mal', account='mal')


# levels

def test_restricted_commands_need_access_and_say_nothing_without_it(tmp_path):
    bot = bot_with(tmp_path, weather=WEATHER)
    assert bot.say('!weather', nick='carol', account='carol') == []
    assert bot.say('!forecast', nick='carol') == ['rain later']
    assert op(bot, '!weather') == ['sunny']


def test_allow_gives_access_by_account_when_theyre_logged_in(tmp_path):
    bot = bot_with(tmp_path, weather=WEATHER)
    bot.say('hi', nick='carol', account='carol')
    assert op(bot, '!allow weather carol') == [
        'mal: gave access to plugin weather to carol (account carol)']
    assert op(bot, '!allow weather carol') == [
        'mal: gave access to plugin weather to carol (account carol) (already)']
    assert bot.say('!weather', nick='carol', account='carol') == ['sunny']
    # someone else on carol's nick isn't carol
    assert bot.say('!weather', nick='carol') == []
    # and the bot now knows that nick as their host
    assert op(bot, '!allow !weather carol') == [
        'mal: gave access to !weather to carol (*!*carol@example.com)']


def test_a_plugin_grant_covers_its_restricted_commands(tmp_path):
    bot = bot_with(tmp_path, weather=WEATHER)
    op(bot, '!allow weather $a:carol')
    assert op(bot, '!access weather') == ['plugin weather: open',
                                          '!weather: restricted, allowed: ops, $a:carol']
    assert bot.say('!weather', nick='carol', account='carol') == ['sunny']


def test_the_command_is_named_with_its_prefix_when_a_plugin_shares_its_name(tmp_path):
    bot = bot_with(tmp_path, weather=WEATHER)
    op(bot, '!allow !weather $a:carol')
    assert op(bot, '!access !weather') == ['!weather: restricted, allowed: ops, $a:carol']
    assert op(bot, '!access weather') == ['plugin weather: open',
                                          '!weather: restricted, allowed: ops, $a:carol']


def test_denied_msg_is_said_to_anyone_without_access(tmp_path):
    bot = bot_with(tmp_path, w=(
        "@command('weather', restricted=True, denied_msg='ask mal for access')\n"
        "async def weather(ctx): await ctx.reply('sunny')\n"))
    assert bot.say('!weather') == ['ask mal for access']


def test_ops_and_restricted_together_is_a_mistake():
    with pytest.raises(ValueError, match='not both'):
        command('x', ops=True, restricted=True)


def test_ops_only_cant_be_given_out_from_chat(tmp_path):
    bot = bot_with(tmp_path, admin=ADMIN)
    assert op(bot, '!allow shutdown $a:carol') == [
        "mal: !shutdown is ops only, so it can't be given out or denied from chat. "
        "Its level is set in the config file"]
    assert bot.say('!shutdown', nick='carol', account='carol') == []


def test_open_commands_cant_be_given_out(tmp_path):
    bot = bot_with(tmp_path, quotes=QUOTES)
    assert op(bot, '!allow quote $a:carol') == [
        "mal: !quote is open to everyone, so access to it can't be given out. "
        "To make it restricted, set that in the config file"]


# denies

def test_deny_keeps_someone_off_an_open_plugin_and_its_listeners(tmp_path):
    bot = bot_with(tmp_path, quotes=QUOTES)
    assert op(bot, '!deny quotes $a:troll') == ['mal: kept off plugin quotes: $a:troll']
    assert bot.say('!quote', nick='troll', account='troll') == []
    assert bot.say('hello', nick='troll', account='troll') == []
    assert bot.say('hello', nick='ana') == ['heard hello']


def test_deny_beats_a_grant_but_not_an_op(tmp_path):
    bot = bot_with(tmp_path, weather=WEATHER)
    op(bot, '!allow weather $a:carol')
    op(bot, '!deny weather $a:carol')
    assert bot.say('!weather', nick='carol', account='carol') == []
    op(bot, '!deny weather $a:mal')
    assert op(bot, '!weather') == ['sunny']


def test_bans_beat_grants(tmp_path):
    bot = bot_with(tmp_path, weather=WEATHER)
    op(bot, '!allow weather $a:carol')
    bot.banned_users.append('$a:carol')
    assert bot.say('!weather', nick='carol', account='carol') == []


def test_revoke_takes_back_a_grant_or_a_deny(tmp_path):
    bot = bot_with(tmp_path, weather=WEATHER)
    op(bot, '!allow weather $a:carol')
    op(bot, '!deny weather $a:troll')
    assert op(bot, '!revoke weather $a:carol $a:troll') == [
        'mal: took back $a:carol, $a:troll on plugin weather']
    assert bot.say('!weather', nick='carol', account='carol') == []
    assert op(bot, '!revoke weather $a:carol') == [
        'mal: nothing to take back for $a:carol on plugin weather']


def test_revoke_by_the_nick_theyre_using_now(tmp_path):
    bot = bot_with(tmp_path, weather=WEATHER)
    op(bot, '!allow weather $a:carol')
    bot.say('hi', nick='caz', account='carol')
    assert op(bot, '!revoke weather caz') == ['mal: took back $a:carol on plugin weather']


def test_the_access_commands_are_ops_only_and_check_their_arguments(tmp_path):
    bot = bot_with(tmp_path, weather=WEATHER)
    assert bot.say('!allow weather $a:carol', nick='carol') == []
    assert op(bot, '!allow weather') == [
        'mal: usage: !allow <plugin or command> <who> [<who> ...]']
    assert op(bot, '!access') == ['mal: usage: !access <plugin or command>']
    assert op(bot, '!deny nope $a:troll') == ["mal: there's no plugin or command called nope"]


# the config

CONFIG = {
    'groups': {'trusted': ['$a:alice', '$a:bob']},
    'plugins': {
        'admin': 'ops',
        'weather': {'allow': ['trusted', '$a:carol']},
        'quotes': {'deny': ['$a:troll']},
        'dice': {'commands': {'roll': {'allow': ['voiced']}}},
    },
}
DICE = '''
@command('roll')
async def roll(ctx): await ctx.reply('4')
'''


def config_bot(tmp_path, config=CONFIG):
    return bot_with(tmp_path, config, weather=WEATHER, quotes=QUOTES, dice=DICE, admin=(
        "@command('reboot')\nasync def reboot(ctx): await ctx.reply('rebooting')\n"))


def test_an_allow_list_in_the_config_makes_a_plugin_restricted(tmp_path):
    bot = config_bot(tmp_path)
    assert bot.say('!forecast', nick='bob', account='bob') == ['rain later']
    assert bot.say('!forecast', nick='carol', account='carol') == ['rain later']
    assert bot.say('!forecast', nick='dave', account='dave') == []
    assert op(bot, '!access weather') == [
        'plugin weather: restricted, allowed: ops, trusted, $a:carol']


def test_a_config_level_makes_a_plugin_ops_only(tmp_path):
    bot = config_bot(tmp_path)
    assert bot.say('!reboot', nick='bob', account='bob') == []
    assert op(bot, '!reboot') == ['rebooting']


def test_a_config_deny_keeps_someone_off_an_open_plugin(tmp_path):
    bot = config_bot(tmp_path)
    assert bot.say('!quote', nick='troll', account='troll') == []
    assert bot.say('!quote', nick='ana') == ['to be or not to be']


def test_built_in_groups_voiced_and_chanops_go_by_the_channel(tmp_path):
    config = dict(CONFIG, plugins={'dice': {'commands': {'roll': {'allow': ['voiced']}}},
                                   'quotes': {'allow': ['chanops']}})
    bot = config_bot(tmp_path, config)
    assert bot.say('!roll', nick='ana') == []
    bot.event('mode', nick='chanserv', modes=['+v', 'ana'])
    assert bot.say('!roll', nick='ana') == ['4']
    # voiced in #test, not in #other
    assert bot.say('!roll', nick='ana', channel='#other') == []
    assert bot.say('!quote', nick='ana') == []
    bot.event('mode', nick='chanserv', modes=['+o-v', 'ana', 'ana'])
    assert bot.say('!quote', nick='ana') == ['to be or not to be']
    # +o counts as voiced too
    assert bot.say('!roll', nick='ana') == ['4']


def test_logged_in_and_ops_groups(tmp_path):
    bot = config_bot(tmp_path, {'default': 'restricted', 'plugins': {
        'quotes': {'allow': ['logged-in']}}})
    assert bot.say('!quote', nick='ana') == []
    assert bot.say('!quote', nick='ana', account='ana') == ['to be or not to be']
    # default restricted, and nobody's been given dice
    assert bot.say('!roll', nick='ana', account='ana') == []


def test_a_command_setting_beats_the_plugin_and_the_author(tmp_path):
    bot = config_bot(tmp_path, {'plugins': {'admin': {'commands': {'reboot': 'open'}},
                                            'weather': {'commands': {'weather': 'open'}}}})
    assert bot.say('!weather', nick='ana') == ['sunny']
    bot = config_bot(tmp_path, {'plugins': {'weather': {'level': 'restricted',
                                                        'commands': {'forecast': 'open'}}}})
    assert bot.say('!forecast', nick='ana') == ['rain later']


def test_a_plugin_setting_only_makes_its_commands_stricter(tmp_path):
    bot = bot_with(tmp_path, {'plugins': {'admin': 'restricted'}}, admin=ADMIN)
    assert op(bot, '!access shutdown') == ['!shutdown: ops only']


@pytest.mark.parametrize('config, problem', [
    ({'plugins': {'weather': 'closed'}}, "access.plugins.weather should be open, restricted"),
    ({'plugin': {}}, "access has settings pinhook doesn't know: plugin"),
    ({'default': 'nobody'}, 'access.default should be'),
    ({'groups': {'ops': ['$a:x']}}, "can't have a group called ops"),
    ({'plugins': {'w': {'allow': '$a:x', 'level': 'ops'}}}, 'has an allow list'),
    ({'plugins': {'w': {'commands': {'x': {'commands': {}}}}}},
     "access.plugins.w.commands.x has settings pinhook doesn't know: commands"),
    ({'plugins': {'w': {'deny': [3]}}}, 'access.plugins.w.deny should be a list of entries'),
])
def test_config_problems_stop_the_bot_starting(tmp_path, config, problem):
    with pytest.raises(ValueError, match=problem):
        TestBot(plugin_dir=str(tmp_path), access=config)


def test_settings_for_a_plugin_or_command_that_isnt_there_are_warned_about(tmp_path, caplog):
    bot_with(tmp_path, {'plugins': {'wether': 'ops', 'weather': {'commands': {'wether': 'ops'}}}},
             weather=WEATHER)
    assert "access.plugins has settings for 'wether', but there's no plugin called that, " \
           "did you mean 'weather'?" in caplog.text
    assert "plugin weather has no command called that, did you mean 'weather'?" in caplog.text


def test_reload_reads_access_from_the_config_file_again(tmp_path):
    bot = bot_with(tmp_path, weather=WEATHER)
    bot.config_file = 'config.yaml'
    bot.config_loader = lambda: {'access': {'plugins': {'weather': {'allow': ['$a:carol']}}}}
    assert op(bot, '!reload') == ['Plugins reloaded (and plugin_config and access from '
                                  'config.yaml)']
    assert bot.say('!forecast', nick='carol', account='carol') == ['rain later']
    bot.config_loader = lambda: {'access': {'plugins': {'weather': 'nope'}}}
    assert op(bot, '!reload')[0].endswith("weren't changed, see the log")
    assert bot.say('!forecast', nick='carol', account='carol') == ['rain later']


# what access covers

def test_timers_and_server_events_arent_checked(tmp_path):
    bot = bot_with(tmp_path, {'default': 'restricted'}, greet=(
        "@on('join')\nasync def hi(ctx): await ctx.send('#test', 'hi ' + ctx.nick)\n"
        "@every(seconds=5)\nasync def tick(ctx): await ctx.send('#test', 'tick')\n"))
    assert bot.event('join', nick='ana') == [Sent('message', '#test', 'hi ana')]
    assert bot.tick(5) == [Sent('message', '#test', 'tick')]


def test_message_handlers_only_hear_people_with_access(tmp_path):
    bot = bot_with(tmp_path, {'plugins': {'heard': {'deny': ['troll']}}}, heard=(
        "@on('message')\nasync def h(ctx): await ctx.reply('heard ' + ctx.nick)\n"))
    assert bot.say('hi', nick='troll') == []
    assert bot.say('hi', nick='ana') == ['heard ana']


def test_internal_commands_stay_ops_only_whatever_the_config_says(tmp_path):
    bot = bot_with(tmp_path, {'default': 'open', 'plugins': {'reload': 'open'}})
    assert bot.say('!reload', nick='ana') == []


# !help

def test_help_marks_what_someone_cant_use_and_hides_ops_only(tmp_path):
    bot = bot_with(tmp_path, {'plugins': {'quotes': {'deny': ['troll']}}}, weather=WEATHER,
                   quotes=QUOTES, admin=ADMIN)
    bot.say('!help', nick='troll')
    lines = bot.sent_to('troll')
    assert "!weather (restricted, you don't have access) -- the weather" in lines
    assert "!quote (you don't have access) -- a quote" in lines
    assert '!forecast -- the forecast' in lines
    assert not any('shutdown' in line for line in lines)
    op(bot, '!help')
    assert '!weather -- the weather' in bot.sent_to('mal')
    assert '!shutdown -- stop everything' in bot.sent_to('mal')


def test_help_for_one_restricted_command_is_marked(tmp_path):
    bot = bot_with(tmp_path, weather=WEATHER)
    bot.say('!help weather', nick='ana')
    assert bot.sent_to('ana')[0] == "!weather (restricted, you don't have access) -- the weather"
    bot.say('!help shutdown', nick='ana')
    assert bot.sent_to('ana')[-1] == "there's no command called shutdown"


def test_hidden_commands_are_hidden_from_ops_too(tmp_path):
    bot = bot_with(tmp_path, secret=(
        "@command('secret', ops=True, hide=True)\nasync def s(ctx): pass\n"))
    op(bot, '!help')
    assert not any('secret' in line for line in bot.sent_to('mal'))


# for code: bot.access.can_run

def test_can_run_is_the_check_the_bot_makes(tmp_path):
    bot = bot_with(tmp_path, weather=WEATHER)
    carol = Source('carol', 'carol', 'example.com', 'carol')
    assert not bot.access.can_run(carol, 'weather', '#test')
    op(bot, '!allow weather $a:carol')
    assert bot.access.can_run(carol, 'weather', '#test')
    assert bot.access.can_run(carol, bot.registry.commands['weather'])
    assert not bot.access.can_run(carol, 'nope')
    bot.banned_users.append('$a:carol')
    assert not bot.access.can_run(carol, 'weather')


# saving

def test_grants_and_denies_are_saved_and_loaded(make_bot, tmp_path):
    (tmp_path / 'plugins').mkdir()
    (tmp_path / 'plugins' / 'weather.py').write_text(HEAD + WEATHER)
    bot = make_bot(ops=['$a:mal'], data_dir=str(tmp_path / 'data'))
    reply = bot.call_internal_commands('#test', 'mal', 'allow', 'weather $a:carol', op=True)
    assert reply.msg == ['mal: gave access to plugin weather to $a:carol']
    bot.call_internal_commands('#test', 'mal', 'deny', '!weather troll', op=True)
    saved = json.loads((tmp_path / 'data' / 'pinbot.access.json').read_text())
    assert saved == {'weather': {'allow': ['$a:carol'],
                                 'commands': {'weather': {'deny': ['troll']}}}}
    again = make_bot(ops=['$a:mal'], data_dir=str(tmp_path / 'data'))
    assert again.access.can_run(Source('carol', account='carol'), 'weather')


def test_a_broken_access_file_stops_the_bot_starting(make_bot, tmp_path):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'pinbot.access.json').write_text('[')
    with pytest.raises(ValueError, match="couldn't read .*pinbot.access.json"):
        make_bot(data_dir=str(tmp_path / 'data'))
