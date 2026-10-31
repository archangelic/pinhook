"""Loading recipe files, and checking everything about them before they ever run.

    # recipes/gamenight.yaml
    version: 1
    name: gamenight
    help: pick tonight's game and who goes first
    steps:
      - command: 'quote random games'
        save: game
      - reply: 'Tonight: {game}. {members|random} goes first'

Files are read with pyyaml's safe_load, never its full loader, which can run code.
"""
import difflib
import os
import re
from dataclasses import dataclass

import yaml

from ..api import NAME as COMMAND_NAME
from .steps import NAME, STEPS
from .templates import Template, TemplateError

VERSION = 1
LEVELS = ('open', 'restricted', 'ops')
TOP_LEVEL = {'version', 'name', 'help', 'access', 'steps'}
RECIPE_NAME = COMMAND_NAME
CONDITION = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_.-]*)\s+(is not|is)\s+(.*?)\s*$')
GIVEN = ('nick', 'channel', 'arg', 'members', 'store')


class RecipeError(ValueError):
    """A recipe file that can't be loaded, and where it went wrong."""


@dataclass(frozen=True)
class Condition:
    """A step's when: the variable, whether it's `is not`, and the value it's compared to."""
    path: str
    negate: bool
    value: str


@dataclass
class Step:
    """One step of a recipe, checked: its type, its fields with templates parsed, and its
    condition. where says where it is in the file, for errors."""
    type: str
    fields: dict
    when: Condition | None
    where: str


@dataclass
class Recipe:
    """A recipe, loaded and checked. access is 'open', 'restricted' or 'ops'."""
    name: str
    help: str
    access: str
    steps: list
    path: str | None = None
    version: int = VERSION


def load_recipe(path):
    """Read and check one recipe file. Raises RecipeError saying what's wrong and where."""
    try:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except (yaml.YAMLError, UnicodeDecodeError) as e:
        raise RecipeError("{} isn't valid YAML, or holds something recipes don't allow: {}"
                          .format(path, e))
    except OSError as e:
        raise RecipeError("{} can't be read: {}".format(path, e.strerror))
    default_name = os.path.splitext(os.path.basename(path))[0]
    return parse_recipe(data, default_name, path)


def load_recipes(folder):
    """Every *.yaml recipe in folder, as ({name: Recipe}, [problems]). A broken file is left
    out and its problem listed, so one mistake doesn't stop the rest."""
    recipes, problems = {}, []
    if not folder or not os.path.isdir(folder):
        return recipes, problems
    for file_name in sorted(os.listdir(folder)):
        if not file_name.endswith(('.yaml', '.yml')):
            continue
        path = os.path.join(folder, file_name)
        try:
            recipe = load_recipe(path)
        except RecipeError as e:
            problems.append(str(e))
            continue
        if recipe.name in recipes:
            problems.append('{}: there is already a recipe called {}, in {}'.format(
                path, recipe.name, recipes[recipe.name].path))
            continue
        recipes[recipe.name] = recipe
    return recipes, problems


def store_keys(steps):
    """The store keys some steps read and the ones they set, as two sets, loops included."""
    reads, sets = set(), set()
    for step in steps:
        paths = [step.when.path] if step.when else []
        kinds = STEPS[step.type].fields
        for name, value in step.fields.items():
            if kinds[name] == 'template':
                paths += value.paths
            elif kinds[name] == 'path':
                paths.append(value)
            elif kinds[name] == 'steps':
                inner_reads, inner_sets = store_keys(value)
                reads |= inner_reads
                sets |= inner_sets
        if step.type == 'store':
            sets.add(step.fields['store'])
        reads.update(path.split('.')[1] for path in paths if path.startswith('store.'))
    return reads, sets


def store_warnings(recipes):
    """A warning for each store key a recipe reads that no recipe sets. All recipes share
    one store, so this is most often a typo, like store.game where another sets games."""
    keys = {name: store_keys(recipe.steps) for name, recipe in recipes.items()}
    sets = set().union(*(recipe_sets for _, recipe_sets in keys.values()))
    warnings = []
    for name, (reads, _) in keys.items():
        for key in sorted(reads - sets):
            close = difflib.get_close_matches(key, sets, n=1)
            hint = ', did you mean store.{}?'.format(close[0]) if close else ''
            warnings.append('{} reads store.{}, which no recipe sets{}'.format(name, key, hint))
    return warnings


def parse_recipe(data, default_name, path=None):
    """Check a recipe's data, as read from YAML, and return the Recipe."""
    where = path or default_name
    if not isinstance(data, dict):
        raise RecipeError('{} should hold a recipe: version, name, help and steps'.format(where))
    unknown = sorted(set(data) - TOP_LEVEL)
    if unknown:
        raise RecipeError("{} has settings recipes don't have: {}. A recipe has {}".format(
            where, ', '.join(map(str, unknown)), ', '.join(sorted(TOP_LEVEL))))
    if data.get('version') != VERSION:
        raise RecipeError('{} should start with version: {}, the recipe format it uses'.format(
            where, VERSION))
    name = data.get('name', default_name)
    if not isinstance(name, str) or not RECIPE_NAME.match(name):
        raise RecipeError('{}: the name {!r} should be letters, digits, - and _, like '
                          'gamenight, and it becomes the command'.format(where, name))
    help_text = data.get('help', 'N/A')
    if not isinstance(help_text, str):
        raise RecipeError('{}: help should be one line of text'.format(where))
    access = data.get('access', 'open')
    if access not in LEVELS:
        raise RecipeError('{}: access should be open, restricted or ops, not {!r}'.format(
            where, access))
    raw_steps = data.get('steps')
    if not isinstance(raw_steps, list) or not raw_steps:
        raise RecipeError('{}: steps should be a list with at least one step'.format(where))
    known = set(GIVEN)
    steps = parse_steps(raw_steps, where, known)
    return Recipe(name, help_text.strip(), access, steps, path)


def parse_steps(raw_steps, where, known):
    steps = []
    for number, raw in enumerate(raw_steps, 1):
        steps.append(parse_step(raw, '{}: step {}'.format(where, number), known))
    return steps


def parse_step(raw, where, known):
    if not isinstance(raw, dict):
        raise RecipeError('{} should be a step, like reply: hello'.format(where))
    types = [key for key in raw if key in STEPS]
    if len(types) != 1:
        raise RecipeError('{} should be exactly one kind of step: {}'.format(
            where, ', '.join(sorted(STEPS))))
    step_type = STEPS[types[0]]
    where = '{} ({})'.format(where, step_type.name)
    allowed = set(step_type.fields) | {'when'}
    unknown = sorted(set(map(str, raw)) - allowed)
    if unknown:
        raise RecipeError("{} has fields a {} step doesn't have: {}. It takes {}".format(
            where, step_type.name, ', '.join(unknown), ', '.join(sorted(allowed))))
    missing = sorted(step_type.required - set(raw))
    if missing:
        raise RecipeError('{} needs {}'.format(where, ', '.join(missing)))
    for group in step_type.one_of:
        given = sorted(group & set(raw))
        if len(given) != 1:
            raise RecipeError('{} needs exactly one of {}'.format(where, ', '.join(sorted(group))))
    when = parse_condition(raw['when'], where, known) if 'when' in raw else None
    fields = {}
    for name, value in raw.items():
        if name == 'when':
            continue
        fields[name] = parse_field(name, step_type.fields[name], value, where, known)
    if step_type.saves and fields.get(step_type.saves):
        known.add(fields[step_type.saves])
    return Step(step_type.name, fields, when, where)


def parse_field(name, kind, value, where, known):
    if kind == 'template':
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        try:
            template = Template(value)
        except TemplateError as e:
            raise RecipeError('{}: {}: {}'.format(where, name, e))
        check_names(template.names, where, known)
        return template
    if kind == 'text':
        if not isinstance(value, str):
            raise RecipeError('{}: {} should be text'.format(where, name))
        return value
    if kind == 'name':
        if not isinstance(value, str) or not NAME.match(value) or value in GIVEN:
            raise RecipeError('{}: {} should be a new variable name, like game, not {!r}'
                              .format(where, name, value))
        return value
    if kind == 'path':
        if not isinstance(value, str):
            raise RecipeError('{}: {} should name a variable, like members'.format(where, name))
        check_names([value.split('.')[0]], where, known)
        return value
    if kind == 'steps':
        if not isinstance(value, list) or not value:
            raise RecipeError('{}: {} should be a list with at least one step'.format(
                where, name))
        return parse_steps(value, where, set(known) | {'item'})
    if kind == 'flag':
        if not isinstance(value, bool):
            raise RecipeError('{}: {} should be true or false'.format(where, name))
        return value
    return value


def parse_condition(value, where, known):
    match = CONDITION.match(value) if isinstance(value, str) else None
    if not match:
        raise RecipeError('{}: when should compare a variable with a value, like '
                          '"when: sorted.category is bug", not {!r}'.format(where, value))
    path, op, compared = match.groups()
    check_names([path.split('.')[0]], where, known)
    if len(compared) >= 2 and compared[0] == compared[-1] and compared[0] in '"\'':
        compared = compared[1:-1]
    return Condition(path, op == 'is not', compared)


def check_names(names, where, known):
    for name in names:
        if name not in known:
            raise RecipeError("{}: {{{}}} isn't set by this point. Recipes can use {}".format(
                where, name, ', '.join(sorted(known))))
