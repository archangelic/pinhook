"""Recipe templates: variables, filters, and chat text that can't escape."""
import random
import string

import pytest

from pinhook import recipes
from pinhook.recipes.templates import FILTERS, Template, TemplateError

VALUES = {'nick': 'ana', 'arg': '', 'members': ['bob', 'ana', 'cy'], 'game': ['Blades'],
          'sorted': {'category': 'bug', 'summary': 'it broke'}, 'empty': []}


def lookup(path):
    name, *keys = path.split('.')
    value = VALUES.get(name)
    for key in keys:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def render(source, **values):
    VALUES.update(values)
    try:
        return Template(source).render(lookup)
    finally:
        for name in values:
            VALUES.pop(name, None)


def test_variables_fill_in():
    assert render('{nick} hugs {arg|default:everyone}') == 'ana hugs everyone'
    assert render('{nick} hugs {arg|default:everyone}', arg='bob') == 'ana hugs bob'


def test_lists_read_as_a_comma_list():
    assert render('Tonight: {game}. With {members}') == 'Tonight: Blades. With bob, ana, cy'


def test_mapping_keys_are_looked_up():
    assert render('{sorted.category}: {sorted.summary}') == 'bug: it broke'
    assert render('{sorted.nope}') == ''


@pytest.mark.parametrize('source, expected', [
    ('{members|sorted}', 'ana, bob, cy'),
    ('{members|count}', '3'),
    ('{members|first} {members|last}', 'bob cy'),
    ('{members|join: and }', 'bob and ana and cy'),
    ('{nick|upper}{nick|lower}', 'ANAana'),
    ('{empty|first|default:nobody}', 'nobody'),
    ('{members|sorted|first|upper}', 'ANA'),
])
def test_filters(source, expected):
    assert render(source) == expected


def test_random_picks_one():
    assert render('{members|random}') in VALUES['members']
    assert render('{empty|random}') == ''


def test_braces_are_written_twice():
    assert render('{{literal}} {nick}') == '{literal} ana'


def test_the_names_a_template_uses():
    assert Template('{nick} {sorted.summary} {members|random}').names == [
        'nick', 'sorted', 'members']


@pytest.mark.parametrize('source, problem', [
    ('{nick', 'never closed'),
    ('nick}', 'has no {'),
    ('{}', 'should be a name'),
    ('{ni ck}', 'should be a name'),
    ('{nick.__class__.__mro__}', None),
    ('{nick|shout}', 'is not a filter'),
    (3, 'should be text'),
])
def test_bad_templates_are_refused_when_parsed(source, problem):
    if problem is None:
        # dunder names are only ever mapping keys, never attributes
        assert render(source) == ''
        return
    with pytest.raises(TemplateError, match=problem):
        Template(source)


def test_chat_text_is_never_expanded_again():
    assert render('{arg}', arg='{nick} {members|random}') == '{nick} {members|random}'


def test_control_characters_are_stripped_from_values():
    assert render('said: {arg}', arg='\x01ACTION waves\x01\x02 bold\r\nQUIT') == (
        'said: ACTION waves boldQUIT')


def test_plugins_can_add_filters():
    @recipes.template_filter('shout')
    def shout(value, arg):
        return str(value).upper() + (arg or '!')
    try:
        assert render('{nick|shout}') == 'ANA!'
        assert render('{nick|shout:?!}') == 'ANA?!'
    finally:
        del FILTERS['shout']


def test_hostile_input_never_breaks_the_parser():
    # a template either parses or raises TemplateError, and a value is only ever text
    rng = random.Random(1)
    alphabet = string.printable + '{}|:.\x00\x01é'
    for _ in range(3000):
        source = ''.join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
        try:
            template = Template(source)
        except TemplateError:
            continue
        hostile = ''.join(rng.choice(alphabet) for _ in range(20))
        out = template.render(lambda path: hostile)
        assert not any(c in out for c in '\x00\x01') or any(c in source for c in '\x00\x01')
