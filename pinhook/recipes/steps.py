"""Recipe steps: the four core ones, and the registry plugins add more through.

A step type declares its fields, so a recipe file using it is checked when it
loads. Each field has a kind:

    template   text with {variables}, checked and filled in when the step runs
    text       plain text
    name       a variable name, like a save
    path       a variable to read, like members or store.games
    steps      a list of steps, like for_each's
    flag       true or false
    any        anything YAML can hold, passed through as it is

Every step can also carry `when`, a condition like `sorted.category is bug`.
"""
import re
from dataclasses import dataclass, field

KINDS = {'template', 'text', 'name', 'path', 'steps', 'flag', 'any'}
NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


@dataclass
class StepType:
    """A kind of step: its name, which is also its key in a recipe file, its fields and
    their kinds, the ones it can't do without, and the async function that runs it.

    saves names the field that holds the variable the step saves to, if any.
    """
    name: str
    fields: dict[str, str]
    required: frozenset[str]
    run: object
    saves: str | None = None
    one_of: tuple[frozenset[str], ...] = field(default_factory=tuple)


STEPS: dict[str, StepType] = {}


def step(name, fields, required=(), saves=None, one_of=()):
    """Register a step type, for plugins. The function runs it, with a Run, which fills
    in templates and runs commands as the person who started the recipe, and the
    step's fields, templates parsed.

        @recipes.step('weather', {'weather': 'template', 'save': 'name'}, saves='save')
        async def weather(run, fields):
            run.save(fields.get('save'), await forecast(run.render(fields['weather'])))

    Args:
        name: the step's name, and its key in a recipe file.
        fields: each field's kind, the step's own key included.
        required: fields it can't do without. Its own key always is.
        saves: the field naming the variable it saves to, so later steps can use it.
        one_of: sets of fields of which exactly one must be given.
    """
    for field_name, kind in fields.items():
        if kind not in KINDS:
            raise ValueError('field {} of step {} has kind {!r}, which should be one of {}'
                             .format(field_name, name, kind, ', '.join(sorted(KINDS))))
    if name not in fields:
        raise ValueError('step {} needs a field called {}, its own key'.format(name, name))

    def register(func):
        STEPS[name] = StepType(name, dict(fields), frozenset(required) | {name}, func, saves,
                               tuple(frozenset(group) for group in one_of))
        return func
    return register


# the core steps


@step('command', {'command': 'template', 'save': 'name'}, saves='save')
async def command(run, fields):
    """Run a command as the person who started the recipe. With save, what it says goes in
    that variable, as a list of lines. Without, it's said."""
    lines = await run.run_command(run.render(fields['command']))
    if fields.get('save'):
        run.save(fields['save'], lines)
    else:
        await run.reply(lines)


@step('reply', {'reply': 'template'})
async def reply(run, fields):
    """Say something where the recipe was started."""
    await run.reply(run.render(fields['reply']))


@step('store', {'store': 'name', 'set': 'template', 'add': 'template', 'remove': 'template',
                'clear': 'flag'}, one_of=({'set', 'add', 'remove', 'clear'},))
async def store(run, fields):
    """Keep something in the recipes' store, which every recipe shares, lasts between
    restarts and reads back as {store.key}: set it, add to a list, remove from one, or
    clear it."""
    run.store_change(fields)


@step('for_each', {'for_each': 'path', 'steps': 'steps'}, required=('steps',))
async def for_each(run, fields):
    """Run some steps once for each item in a list, with the item as {item}."""
    await run.each(fields['for_each'], fields['steps'])
