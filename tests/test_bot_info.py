"""self.bot in a Plugin class and ctx.bot in a handler: what a plugin can see of the bot,
and what a class plugin can change of its own."""
import logging
import os

import pytest

from pinhook import Plugin
from pinhook.testing import TestBot
from pinhook.transport.base import Source

SKILLS = '''
from pinhook import Plugin, command, recipes


def make(name, reply, access='open'):
    return recipes.parse_recipe({'version': 1, 'name': name, 'help': 'a skill',
                                 'access': access, 'steps': [{'reply': reply}]}, name)


class Skills(Plugin):
    def setup(self, previous):
        self.where = (self.bot.nick, self.bot.prefix, self.bot.data_dir)
        self.units = self.config.get('units', 'none')
        self.bot.logger.info('skills set up')
        self.problems = self.set_recipes([make('hug', '{nick} hugs {arg}'),
                                          make('pick', 'picked', 'restricted')])

    @command('where')
    async def where(self, ctx):
        await ctx.reply('{} {} {}'.format(*self.where))

    @command('units')
    async def units(self, ctx):
        await ctx.reply(self.units)

    @command('reset', ops=True)
    async def reset(self, ctx):
        await ctx.reply('reset')

    @command('learn')
    async def learn(self, ctx, name: str, reply: str):
        problems = self.set_recipes([make(name, reply)])
        await ctx.reply(problems or 'learned ' + name)

    @command('grant')
    async def grant(self, ctx, nick: str):
        await ctx.reply(str(self.allow('pick', ctx.member(nick))))

    @command('who')
    async def who(self, ctx, entry: str):
        await ctx.reply('{} {} {}'.format(ctx.bot.is_op(ctx.source),
                                          ctx.bot.matches(entry, ctx.source),
                                          ctx.bot.keeps_history(ctx.channel)))
'''

MOVES = '''
from pinhook import Plugin, command, recipes


class Moves(Plugin):
    def setup(self, previous):
        self.set_recipes([recipes.parse_recipe({'version': 1, 'name': 'dance', 'help': 'a move',
                                                'steps': [{'reply': 'dances'}]}, 'dance')])

    @command('secret', restricted=True)
    async def secret(self, ctx):
        await ctx.reply('shh')
'''

ANA = Source('ana', '~ana', 'example.com', 'ana')


def make_bot(tmp_path, **options):
    plugins = tmp_path / 'plugins'
    plugins.mkdir(exist_ok=True)
    (plugins / 'skills.py').write_text(SKILLS)
    (plugins / 'moves.py').write_text(MOVES)
    return TestBot(plugin_dir=str(plugins), ops=['$a:mal'], **options)


def skills(bot):
    return bot.registry.instances[('skills', 'Skills')]


def test_a_plugin_class_gets_the_bot_before_setup(tmp_path):
    bot = make_bot(tmp_path)
    nick, prefix, data_dir = bot.say('!where')[0].split(' ')
    assert (nick, prefix) == ('testbot', '!')
    assert os.path.isdir(data_dir) and data_dir == bot.data_dir
    assert skills(bot).bot is bot.info


def test_is_op_matches_and_keeps_history(tmp_path):
    bot = make_bot(tmp_path, history={'channels': ['#test']})
    assert bot.say('!who $a:mal', nick='mal', account='mal') == ['True True True']
    assert bot.say('!who $a:mal', nick='ana', account='ana', channel='#other') == [
        'False False False']


def test_the_bot_a_plugin_sees_changes_nothing(tmp_path):
    bot = make_bot(tmp_path)
    assert not any(hasattr(bot.info, name) for name in ('set_recipes', 'allow', 'config_of'))


def test_recipes_a_plugin_sets_are_its_own_commands(tmp_path):
    bot = make_bot(tmp_path)
    assert bot.say('!hug everyone', nick='ana') == ['ana hugs everyone']
    found = {c.name: c.plugin for c in bot.commands()}
    assert (found['hug'], found['dance']) == ('skills', 'moves')


def test_they_stay_through_a_reload_and_a_recipe_add(tmp_path):
    bot = make_bot(tmp_path, recipe_dir=str(tmp_path / 'recipes'))
    bot.say('!reload', nick='mal', account='mal')
    bot.say('!recipe add wave {nick} waves', nick='mal', account='mal')
    assert bot.say('!hug ana') == ['tester hugs ana']
    assert bot.say('!wave') == ['tester waves']


def test_setting_them_again_replaces_only_that_plugins_recipes(tmp_path):
    bot = make_bot(tmp_path)
    assert bot.say('!learn spin {nick} spins', nick='ana') == ['learned spin']
    assert bot.say('!spin', nick='ana') == ['ana spins']
    assert bot.say('!hug') == []
    assert bot.say('!where') and bot.say('!dance') == ['dances']


def test_a_name_thats_taken_is_left_out(tmp_path):
    bot = make_bot(tmp_path)
    assert bot.say('!learn where "nope"') == [
        'skills !where is already a command of plugin skills']
    assert bot.say('!learn dance "nope"') == [
        'skills !dance is already a command of plugin moves']


def test_switching_a_plugin_off_switches_its_recipes_off(tmp_path):
    bot = make_bot(tmp_path)
    bot.say('!disable skills', nick='mal', account='mal')
    assert bot.say('!hug') == []
    assert bot.say('!dance') == ['dances']


def test_allow_gives_access_to_one_of_the_plugins_restricted_commands(tmp_path):
    bot = make_bot(tmp_path)
    assert bot.say('!pick', nick='ana', account='ana') == []
    assert bot.say('!grant ana', nick='mal', account='mal') == ['True']
    assert bot.say('!pick', nick='ana', account='ana') == ['picked']
    assert bot.say('!grant ana', nick='mal', account='mal') == ['False']
    assert bot.access.entries(bot.registry.commands['pick'], 'allow') == ['$a:ana']


def test_allow_logs_each_grant_as_an_audit_line(tmp_path, caplog):
    bot = make_bot(tmp_path)
    with caplog.at_level(logging.INFO):
        skills(bot).allow('pick', ANA)
        skills(bot).allow('pick', ANA)
    assert [r.getMessage() for r in caplog.records if getattr(r, 'audit', False)] == [
        'plugin skills gave access to !pick to $a:ana']


def test_allow_takes_only_the_plugins_own_commands(tmp_path):
    bot = make_bot(tmp_path)
    for command in ('secret', 'dance', 'help', 'nothing'):
        with pytest.raises(ValueError, match='plugin skills has no command called ' + command):
            skills(bot).allow(command, ANA)
    assert bot.access.entries(bot.registry.commands['secret'], 'allow') == []


def test_allow_refuses_an_ops_only_command_and_skips_an_open_one(tmp_path):
    bot = make_bot(tmp_path)
    with pytest.raises(ValueError, match="!reset is ops only, so it can't be given out"):
        skills(bot).allow('reset', ANA)
    assert skills(bot).allow('where', ANA) is False
    assert bot.access.entries(bot.registry.commands['where'], 'allow') == []


def test_a_source_works_for_allow_without_an_account(tmp_path):
    bot = make_bot(tmp_path)
    assert skills(bot).allow('pick', Source('bob', '~bob', 'example.com', None))
    assert bot.access.entries(bot.registry.commands['pick'], 'allow') == ['*!*bob@example.com']


def test_set_recipes_and_allow_wait_for_the_bot():
    with pytest.raises(RuntimeError, match='from setup on'):
        Plugin().set_recipes([])
    with pytest.raises(RuntimeError, match='from setup on'):
        Plugin().allow('pick', ANA)


def test_split_says_what_lines_a_long_text_goes_as(tmp_path):
    bot = make_bot(tmp_path)
    text = ' '.join('word{}'.format(i) for i in range(150))
    lines = bot.info.split('#test', text + '\nshort', prefix='[x] ')
    assert len(lines) == 4 and lines[-1] == 'short'
    assert ' '.join(lines[:-1]) == text
    room = bot.transport.text_room('privmsg', '#test', '[x] ')
    assert all(len(line.encode()) <= room for line in lines)


def test_a_plugin_class_gets_its_config_before_setup(tmp_path):
    bot = make_bot(tmp_path, plugin_config={'skills': {'units': 'metric'}})
    assert bot.say('!units') == ['metric']
    assert make_bot(tmp_path).say('!units') == ['none']


def test_a_plugin_class_logs_through_the_bot(tmp_path, caplog):
    make_bot(tmp_path)
    assert 'skills set up' in caplog.text
