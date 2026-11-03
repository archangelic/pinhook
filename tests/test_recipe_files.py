"""Recipe files: loading, and everything checked before a recipe runs."""
import pytest
import yaml

from pinhook import recipes
from pinhook.recipes.loader import Condition, load_recipe, load_recipes, parse_recipe
from pinhook.recipes.steps import STEPS

GAMENIGHT = '''
version: 1
name: gamenight
help: pick tonight's game and who goes first
steps:
  - command: 'quote random games'
    save: game
  - reply: 'Tonight: {game}. {members|random} goes first'
'''


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def test_a_recipe_file_loads(tmp_path):
    recipe = load_recipe(write(tmp_path, 'gamenight.yaml', GAMENIGHT))
    assert (recipe.name, recipe.help, recipe.access) == (
        'gamenight', "pick tonight's game and who goes first", 'open')
    assert [s.type for s in recipe.steps] == ['command', 'reply']
    assert recipe.steps[0].fields['save'] == 'game'
    assert recipe.steps[1].fields['reply'].names == ['game', 'members']


def test_the_name_defaults_to_the_file_name(tmp_path):
    recipe = load_recipe(write(tmp_path, 'hug.yaml', 'version: 1\nsteps:\n  - reply: hugs\n'))
    assert (recipe.name, recipe.help) == ('hug', 'N/A')


def test_a_folder_of_recipes_loads_and_lists_what_it_couldnt(tmp_path):
    write(tmp_path, 'gamenight.yaml', GAMENIGHT)
    write(tmp_path, 'broken.yaml', 'version: 1\nsteps: []\n')
    write(tmp_path, 'notes.txt', 'not a recipe')
    found, problems = load_recipes(str(tmp_path))
    assert list(found) == ['gamenight']
    assert len(problems) == 1 and 'broken.yaml: steps should be a list' in problems[0]


def test_a_missing_folder_has_no_recipes(tmp_path):
    assert load_recipes(str(tmp_path / 'nope')) == ({}, [])


def test_two_recipes_with_one_name(tmp_path):
    write(tmp_path, 'a.yaml', GAMENIGHT)
    write(tmp_path, 'b.yaml', GAMENIGHT)
    found, problems = load_recipes(str(tmp_path))
    assert list(found) == ['gamenight']
    assert 'there is already a recipe called gamenight' in problems[0]


def test_a_python_object_tag_is_refused(tmp_path):
    path = write(tmp_path, 'evil.yaml',
                 'version: 1\nsteps:\n  - reply: !!python/object/apply:os.system ["echo hi"]\n')
    with pytest.raises(recipes.RecipeError, match="isn't valid YAML, or holds something"):
        load_recipe(path)


@pytest.mark.parametrize('text, problem', [
    ('- reply: hi', 'should hold a recipe'),
    ('version: 2\nsteps: [{reply: hi}]', 'should start with version: 1'),
    ('steps: [{reply: hi}]', 'should start with version: 1'),
    ('version: 1\nname: game night\nsteps: [{reply: hi}]', "the name 'game night' should be"),
    ('version: 1\naccess: secret\nsteps: [{reply: hi}]', 'access should be open, restricted'),
    ('version: 1\nsteps: [{reply: hi}]\nextra: 1', "settings recipes don't have: extra"),
    ('version: 1\nsteps: [{shout: hi}]', 'should be exactly one kind of step'),
    ('version: 1\nsteps: [{reply: hi, command: roll}]', 'should be exactly one kind of step'),
    ('version: 1\nsteps: [{reply: hi, save: x}]', "fields a reply step doesn't have: save"),
    ('version: 1\nsteps: [{reply: "{nick"}]', 'step 1 \\(reply\\): reply: a { is never'),
    ('version: 1\nsteps: [{reply: "{gmae}"}]', "{gmae} isn't set by this point"),
    ('version: 1\nsteps: [{reply: "{nick|shout}"}]', 'is not a filter'),
    ('version: 1\nsteps: [{command: roll, save: nick}]', 'save should be a new variable'),
    ('version: 1\nsteps: [{store: games}]', 'needs exactly one of add, clear, remove, set'),
    ('version: 1\nsteps: [{store: games, set: a, add: b}]', 'needs exactly one of'),
    ('version: 1\nsteps: [{store: games, clear: maybe}]', 'clear should be true or false'),
    ('version: 1\nsteps: [{for_each: members}]', 'needs steps'),
    ('version: 1\nsteps: [{for_each: nobody, steps: [{reply: hi}]}]', "{nobody} isn't set"),
    ('version: 1\nsteps: [{reply: hi, when: nick equals mal}]', 'when should compare'),
    ('version: 1\nsteps: [{reply: hi, when: who is mal}]', "{who} isn't set"),
])
def test_problems_are_found_when_the_file_loads(text, problem):
    with pytest.raises(recipes.RecipeError, match=problem):
        parse_recipe(yaml.safe_load(text), 'r')


def test_saved_variables_are_known_after_the_step_that_saves_them():
    data = {'version': 1, 'steps': [{'reply': '{game}'}, {'command': 'roll', 'save': 'game'}]}
    with pytest.raises(recipes.RecipeError, match="step 1 \\(reply\\): {game} isn't set"):
        parse_recipe(data, 'r')


def test_item_is_only_known_inside_a_for_each():
    loop = {'for_each': 'members', 'steps': [{'reply': 'hi {item}'}]}
    parse_recipe({'version': 1, 'steps': [loop]}, 'r')
    with pytest.raises(recipes.RecipeError, match="{item} isn't set"):
        parse_recipe({'version': 1, 'steps': [loop, {'reply': '{item}'}]}, 'r')


def test_conditions_are_parsed():
    recipe = parse_recipe({'version': 1, 'steps': [
        {'command': 'sort {arg}', 'save': 'sorted'},
        {'reply': 'a bug', 'when': 'sorted.category is bug'},
        {'reply': 'empty', 'when': "arg is not ''"}]}, 'r')
    assert recipe.steps[1].when == Condition('sorted.category', False, 'bug')
    assert recipe.steps[2].when == Condition('arg', True, '')


def test_plugins_register_step_types_that_get_checked():
    @recipes.step('weather', {'weather': 'template', 'save': 'name', 'units': 'text'},
                  saves='save')
    async def weather(run, fields):
        pass
    try:
        recipe = parse_recipe({'version': 1, 'steps': [
            {'weather': '{arg}', 'save': 'forecast', 'units': 'metric'},
            {'reply': '{forecast}'}]}, 'r')
        assert recipe.steps[0].type == 'weather'
        with pytest.raises(recipes.RecipeError, match="fields a weather step doesn't have"):
            parse_recipe({'version': 1, 'steps': [{'weather': 'x', 'colour': 'red'}]}, 'r')
    finally:
        del STEPS['weather']


def test_a_step_type_with_a_made_up_kind_is_refused():
    with pytest.raises(ValueError, match="has kind 'number'"):
        recipes.step('bad', {'bad': 'number'})
