"""Recipes running as commands: steps, variables, the store, loops, conditions, access
and limits."""
from pinhook.recipes.steps import STEPS
from pinhook.testing import TestBot
from pinhook.transport.base import Source

PLUGIN = '''
from pinhook import command, recipes

@command('quote')
async def quote(ctx, topic: str = 'any'):
    await ctx.reply('Blades in the Dark' if topic == 'random games' else 'a quote')

@command('weather', restricted=True)
async def weather(ctx):
    await ctx.reply('sunny')

@command('shutdown', ops=True)
async def shutdown(ctx):
    await ctx.reply('bye')

@command('two')
async def two(ctx):
    await ctx.reply('one line')
    await ctx.reply('another line')

@recipes.step('shout', {'shout': 'template'})
async def shout(run, fields):
    await run.reply(run.render(fields['shout']).upper() + '!')
'''


def make(tmp_path, ops=('$a:mal',), access=None, **files):
    plugins = tmp_path / 'plugins'
    plugins.mkdir(exist_ok=True)
    (plugins / 'plugin.py').write_text(PLUGIN)
    folder = tmp_path / 'recipes'
    folder.mkdir(exist_ok=True)
    for name, text in files.items():
        (folder / (name + '.yaml')).write_text('version: 1\n' + text)
    bot = TestBot(plugin_dir=str(plugins), recipe_dir=str(folder), ops=list(ops),
                  access=access)
    return bot


def teardown_function():
    STEPS.pop('shout', None)


def test_gamenight(tmp_path):
    bot = make(tmp_path, gamenight='''
help: pick tonight's game and who goes first
steps:
  - command: 'quote random games'
    save: game
  - reply: 'Tonight: {game}. {members|random} goes first'
''')
    bot.say('hi', nick='ana')
    [line] = bot.say('!gamenight', nick='bob')
    assert line.startswith('Tonight: Blades in the Dark. ')
    assert line.split('. ')[1].split()[0] in ('testbot', 'ana', 'bob')


def test_variables_and_filters(tmp_path):
    bot = make(tmp_path, hug="steps:\n  - reply: '{nick} hugs {arg|default:everyone}'\n")
    assert bot.say('!hug', nick='ana') == ['ana hugs everyone']
    assert bot.say('!hug bob and cy', nick='ana') == ['ana hugs bob and cy']
    # text from chat is never expanded again
    assert bot.say('!hug {nick}', nick='ana') == ['ana hugs {nick}']


def test_a_command_step_without_save_says_what_the_command_said(tmp_path):
    bot = make(tmp_path, both="steps:\n  - command: two\n  - reply: done\n")
    assert bot.say('!both') == ['one line', 'another line', 'done']


def test_the_store_lasts_between_runs(tmp_path):
    bot = make(tmp_path, games='''
steps:
  - store: games
    add: '{arg}'
    when: arg is not ''
  - reply: 'games: {store.games|sorted}'
''', forget='''
steps:
  - store: games
    remove: '{arg}'
  - reply: 'games: {store.games|default:none}'
''', reset="steps:\n  - store: games\n    clear: true\n  - reply: cleared\n")
    bot.say('!games wingspan')
    assert bot.say('!games azul') == ['games: azul, wingspan']
    # every recipe shares one store, so forget sees what games added
    assert bot.store('_recipes')['games'] == ['wingspan', 'azul']
    assert bot.say('!forget wingspan') == ['games: azul']
    assert bot.say('!reset') == ['cleared']
    assert bot.say('!games') == ['games: ']


def test_for_each_and_when(tmp_path):
    bot = make(tmp_path, roll_call='''
steps:
  - for_each: members
    steps:
      - reply: 'hello {item}'
        when: item is not testbot
''')
    bot.say('hi', nick='ana')
    assert bot.say('!roll_call', nick='bob') == ['hello ana', 'hello bob']


def test_a_step_someone_cant_run_stops_the_recipe_and_says_why(tmp_path):
    bot = make(tmp_path, forecast='''
steps:
  - reply: checking
  - command: weather
  - reply: never said
''')
    assert bot.say('!forecast', nick='ana', account='ana') == [
        'checking', "forecast stopped: ana doesn't have access to !weather"]
    bot.say('!allow weather $a:ana', nick='mal', account='mal')
    assert bot.say('!forecast', nick='ana', account='ana') == [
        'checking', 'sunny', 'never said']


def test_every_step_runs_as_the_person_who_started_it(tmp_path):
    bot = make(tmp_path, sneaky="steps:\n  - command: quote\n  - command: shutdown\n")
    assert bot.say('!sneaky', nick='ana') == [
        'a quote', "sneaky stopped: ana doesn't have access to !shutdown"]
    assert bot.say('!sneaky', nick='mal', account='mal') == ['a quote', 'bye']


def test_an_unknown_command_stops_the_recipe(tmp_path):
    bot = make(tmp_path, typo="steps:\n  - command: qoute\n")
    assert bot.say('!typo') == ["typo stopped: there's no command called qoute"]


def test_a_plugin_step(tmp_path):
    bot = make(tmp_path, loud="steps:\n  - shout: 'hello {nick}'\n")
    assert bot.say('!loud', nick='ana') == ['HELLO ANA!']


# limits

def test_the_step_cap(tmp_path):
    bot = make(tmp_path, many='''
steps:
  - for_each: members
    steps:
      - store: seen
        add: '{item}'
  - reply: done
''')
    for n in range(97):
        bot.say('hi', nick='user{}'.format(n))
    # testbot, tester and 97 users: the loop plus one step each is 100, and the reply 101
    assert bot.say('!many') == ['many stopped: it ran more than 100 steps']
    assert len(bot.store('_recipes')['seen']) == 99
    # with one member fewer to count, it fits exactly
    bot.channels['#test'].remove_user('user1')
    bot.store('_recipes').clear()
    assert bot.say('!many', nick='user0') == ['done']


def test_a_recipe_calling_itself_is_stopped(tmp_path):
    bot = make(tmp_path, again="steps:\n  - command: again\n",
               ping="steps:\n  - command: pong\n", pong="steps:\n  - command: ping\n")
    assert bot.say('!again') == ['again stopped: it calls itself: again -> again']
    assert bot.say('!ping') == ['pong stopped: it calls itself: ping -> pong -> ping']


# access

def test_a_recipe_file_sets_its_own_access(tmp_path):
    bot = make(tmp_path, secret="access: restricted\nsteps:\n  - reply: shh\n",
               boss="access: ops\nsteps:\n  - reply: yes boss\n")
    assert bot.say('!secret', nick='ana', account='ana') == []
    assert bot.say('!secret', nick='mal', account='mal') == ['shh']
    bot.say('!allow secret $a:ana', nick='mal', account='mal')
    assert bot.say('!secret', nick='ana', account='ana') == ['shh']
    assert bot.say('!boss', nick='ana', account='ana') == []
    assert bot.say('!allow boss $a:ana', nick='mal', account='mal')[0].endswith(
        "can't be given out or denied from chat. Its level is set in the config file")


def test_access_recipes_in_the_config(tmp_path):
    bot = make(tmp_path, access={'recipes': {'hug': {'allow': ['$a:ana']}}},
               hug="steps:\n  - reply: hugs\n")
    assert bot.say('!hug', nick='bob', account='bob') == []
    assert bot.say('!hug', nick='ana', account='ana') == ['hugs']
    assert bot.access.can_run(Source('ana', account='ana'), 'hug')


def test_settings_for_a_recipe_that_isnt_there_are_warned_about(tmp_path, caplog):
    make(tmp_path, access={'recipes': {'hgu': 'restricted'}}, hug="steps:\n  - reply: x\n")
    assert ("access.recipes has settings for 'hgu', but there's no recipe called that, did "
            "you mean 'hug'?") in caplog.text


# as commands

def test_recipes_are_in_help_and_the_command_listing(tmp_path):
    bot = make(tmp_path, gamenight="help: pick a game\nsteps:\n  - reply: x\n")
    bot.say('!help', nick='ana')
    assert '!gamenight' in bot.sent_to('ana')[0]
    info = {i.name: i for i in bot.commands()}['gamenight']
    assert (info.plugin, info.help, info.usage) == ('(recipes)', 'pick a game',
                                                    'gamenight [arg=]')


def test_a_recipe_cant_take_a_name_already_taken(tmp_path, caplog):
    bot = make(tmp_path, quote="steps:\n  - reply: x\n", help="steps:\n  - reply: x\n",
               fine="steps:\n  - reply: fine\n")
    assert sorted(bot.recipes) == ['fine']
    assert any('!quote is already a command of plugin plugin' in p for p in bot.recipe_problems)
    assert any('!help is already a command of the bot itself' in p
               for p in bot.recipe_problems)
    assert bot.say('!quote') == ['a quote']


def test_a_broken_recipe_is_left_out_and_logged(tmp_path, caplog):
    bot = make(tmp_path, broken="steps:\n  - reply: '{nope}'\n", fine="steps:\n  - reply: ok\n")
    assert sorted(bot.recipes) == ['fine']
    assert "{nope} isn't set by this point" in caplog.text


def test_reload_picks_up_new_and_changed_recipes(tmp_path):
    bot = make(tmp_path, hello="steps:\n  - reply: hello\n")
    (tmp_path / 'recipes' / 'hello.yaml').write_text('version: 1\nsteps:\n  - reply: hi\n')
    (tmp_path / 'recipes' / 'bye.yaml').write_text('version: 1\nsteps:\n  - reply: bye\n')
    bot.say('!reload', nick='mal', account='mal')
    assert bot.say('!hello') == ['hi']
    assert bot.say('!bye') == ['bye']


def test_recipes_can_be_switched_off(tmp_path):
    bot = make(tmp_path, hello="steps:\n  - reply: hello\n")
    bot.say('!disable hello', nick='mal', account='mal')
    assert bot.say('!hello') == []


def test_no_recipe_dir_means_no_recipes(tmp_path):
    bot = TestBot(plugin_dir=str(tmp_path))
    assert bot.recipes == {}
