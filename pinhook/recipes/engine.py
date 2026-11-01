"""Running a recipe: its steps in order, as the person who started it.

Every command step runs through bot.run_as, with that person's own access, so a
recipe can never do more than they could. A step that's refused or fails stops
the recipe, and it says why.
"""
import contextvars

from ..transport.base import Source
from .steps import STEPS
from .templates import as_list, text

RECIPES = '(recipes)'
MAX_STEPS = 100
CHAIN: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    'pinhook_recipe_chain', default=())
MISSING = object()


class StopRecipe(Exception):
    """Stops a recipe, with what to tell the person who started it."""


STORE = '_recipes'


class Run:
    """One run of a recipe. Steps use it to fill in templates, run commands, save
    variables and reply.

    Attributes:
        ctx: the context of the message that started the recipe.
        vars: the variables so far: nick, channel, arg, members and what steps saved.
        store: the store all recipes share, kept between restarts, read as {store.key}.
    """

    def __init__(self, bot, recipe, ctx, arg):
        self.bot = bot
        self.recipe = recipe
        self.ctx = ctx
        self.who = Source(ctx.nick, ctx.user, ctx.host, ctx.account)
        self.channel = ctx.channel if self.bot.transport.is_channel(ctx.channel or '') else None
        self.store = bot.store(STORE)
        self.vars = {'nick': ctx.nick, 'channel': ctx.channel or '', 'arg': arg}
        self.steps_run = 0

    def lookup(self, path):
        name, *keys = path.split('.')
        if name == 'members' and name not in self.vars:
            self.vars['members'] = [m.nick for m in self.ctx.members()]
        value = self.store if name == 'store' else self.vars.get(name)
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        return value

    def render(self, template):
        """A template, filled in from the variables so far."""
        return template.render(self.lookup)

    def save(self, name, value):
        """Set a variable later steps can use."""
        if name:
            self.vars[name] = value

    async def reply(self, text_or_lines):
        await self.ctx.reply(text_or_lines)

    def stop(self, message):
        """Stop the recipe, telling the person who started it why."""
        raise StopRecipe(message)

    async def run_command(self, line):
        """Run a command, written without its prefix, as the person who started the recipe,
        and return what it said as a list of lines. Stops the recipe if it can't run."""
        word, _, arg = line.strip().partition(' ')
        if not word:
            self.stop('a command step had no command')
        handler = self.bot.registry.find(word, addressed=True)
        chain = CHAIN.get()
        if handler is not None and handler.plugin == RECIPES and handler.name in chain:
            self.stop('it calls itself: {}'.format(' -> '.join(chain + (handler.name,))))
        result = await self.bot.run_as(self.who, word, arg.strip(), self.channel)
        if result.status != 'ran':
            self.stop(result.error or '{} {}'.format(word, result.status))
        return list(result.lines)

    def store_change(self, fields):
        key = fields['store']
        if fields.get('clear'):
            self.store.pop(key, None)
        elif 'set' in fields:
            self.store[key] = self.render(fields['set'])
        elif 'add' in fields:
            current = self.store.get(key)
            items = list(current) if isinstance(current, list) else as_list(current)
            items.append(self.render(fields['add']))
            self.store[key] = items
        elif 'remove' in fields:
            gone = self.render(fields['remove'])
            current = self.store.get(key)
            if isinstance(current, list):
                self.store[key] = [item for item in current if text(item) != gone]
            elif text(current) == gone:
                self.store.pop(key, None)

    async def each(self, path, steps):
        before = self.vars.get('item', MISSING)
        try:
            for item in as_list(self.lookup(path)):
                self.vars['item'] = item
                await self.run_steps(steps)
        finally:
            if before is MISSING:
                self.vars.pop('item', None)
            else:
                self.vars['item'] = before

    def holds(self, condition):
        actual = text(self.lookup(condition.path)).strip()
        return (actual == condition.value) != condition.negate

    async def run_steps(self, steps):
        for step in steps:
            self.steps_run += 1
            if self.steps_run > MAX_STEPS:
                self.stop('it ran more than {} steps'.format(MAX_STEPS))
            if step.when is not None and not self.holds(step.when):
                continue
            await STEPS[step.type].run(self, step.fields)


async def run_recipe(bot, recipe, ctx, arg=''):
    """Run a recipe for the message in ctx, with arg as {arg}."""
    chain = CHAIN.get()
    if recipe.name in chain:
        await ctx.reply('{} stopped: it calls itself: {}'.format(
            recipe.name, ' -> '.join(chain + (recipe.name,))))
        return
    token = CHAIN.set(chain + (recipe.name,))
    run = Run(bot, recipe, ctx, arg)
    try:
        await run.run_steps(recipe.steps)
    except StopRecipe as e:
        bot.logger.info('recipe {} stopped for {}: {}'.format(recipe.name, ctx.nick, e))
        await ctx.reply('{} stopped: {}'.format(recipe.name, e))
    finally:
        CHAIN.reset(token)
        run.store.save_if_changed()
