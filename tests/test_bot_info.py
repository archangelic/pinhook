"""self.bot in a Plugin class and ctx.bot in a handler: what a plugin can see of the bot."""
import os

from pinhook.testing import TestBot

SKILLS = '''
from pinhook import Plugin, command


class Skills(Plugin):
    def setup(self, previous):
        self.where = (self.bot.nick, self.bot.prefix, self.bot.data_dir)

    @command('where')
    async def where(self, ctx):
        await ctx.reply('{} {} {}'.format(*self.where))

    @command('who')
    async def who(self, ctx, entry: str):
        await ctx.reply('{} {} {}'.format(ctx.bot.is_op(ctx.source),
                                          ctx.bot.matches(entry, ctx.source),
                                          ctx.bot.keeps_history(ctx.channel)))
'''


def make_bot(tmp_path, **options):
    plugins = tmp_path / 'plugins'
    plugins.mkdir(exist_ok=True)
    (plugins / 'skills.py').write_text(SKILLS)
    return TestBot(plugin_dir=str(plugins), ops=['$a:mal'], **options)


def test_a_plugin_class_gets_the_bot_before_setup(tmp_path):
    bot = make_bot(tmp_path)
    nick, prefix, data_dir = bot.say('!where')[0].split(' ')
    assert (nick, prefix) == ('testbot', '!')
    assert os.path.isdir(data_dir) and data_dir == bot.data_dir
    assert bot.registry.instances[('skills', 'Skills')].bot is bot.info


def test_is_op_matches_and_keeps_history(tmp_path):
    bot = make_bot(tmp_path, history={'channels': ['#test']})
    assert bot.say('!who $a:mal', nick='mal', account='mal') == ['True True True']
    assert bot.say('!who $a:mal', nick='ana', account='ana', channel='#other') == [
        'False False False']
