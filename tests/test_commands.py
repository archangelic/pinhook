"""Typed command arguments, read from the handler's signature."""
from typing import Annotated, Literal, Optional

import pytest

from pinhook.commands import UsageError, describe, params_of, parse, usage


def roll(ctx, dice: Annotated[str, 'dice like 2d6'] = '1d6', times: int = 1):
    pass


def remind(ctx, when: str, what: str):
    pass


def weather(ctx, unit: Literal['metric', 'imperial'] = 'metric', days: Optional[int] = None,
            hourly: bool = False):
    pass


def test_arguments_come_from_the_signature():
    params = params_of(roll)
    assert [(p.name, p.type, p.default, p.description) for p in params] == [
        ('dice', str, '1d6', 'dice like 2d6'), ('times', int, 1, None)]


def test_words_become_typed_values():
    assert parse(params_of(roll), '2d20 3') == {'dice': '2d20', 'times': 3}


def test_left_out_arguments_keep_their_defaults():
    assert parse(params_of(roll), '') == {}
    assert parse(params_of(roll), '2d6') == {'dice': '2d6'}


def test_the_last_str_takes_the_rest_of_the_line_as_written():
    parsed = parse(params_of(remind), '5m  get the "tea"  ')
    assert parsed == {'when': '5m', 'what': 'get the "tea"'}


def test_quotes_group_words():
    assert parse(params_of(remind), '"tea time" 5m') == {'when': 'tea time', 'what': '5m'}


def test_an_unclosed_quote_is_plain_text():
    assert parse(params_of(remind), '"tea time 5m') == {'when': '"tea', 'what': 'time 5m'}


def test_literal_optional_and_bool():
    params = params_of(weather)
    assert parse(params, 'imperial 3 yes') == {'unit': 'imperial', 'days': 3, 'hourly': True}
    assert parse(params, '') == {}
    assert params[1].default is None


@pytest.mark.parametrize('func, text, problem', [
    (roll, '2d20 three', 'times must be a whole number'),
    (roll, '2d20 3 more', 'too many arguments'),
    (remind, '5m', 'missing what'),
    (remind, '', 'missing when'),
    (weather, 'kelvin', 'unit must be one of metric, imperial'),
    (weather, 'metric 2 maybe', 'hourly must be true or false'),
])
def test_bad_input_is_a_usage_error(func, text, problem):
    with pytest.raises(UsageError, match=problem):
        parse(params_of(func), text)


def test_usage_lines():
    assert usage('roll', params_of(roll)) == 'roll [dice=1d6] [times=1]'
    assert usage('remind', params_of(remind)) == 'remind <when> <what>'
    assert usage('weather', params_of(weather)) == 'weather [unit=metric] [days] [hourly=false]'


def test_descriptions_for_help():
    assert describe(params_of(roll)) == ['dice: dice like 2d6']
    assert describe(params_of(weather)) == ['unit: one of metric, imperial']


def test_methods_skip_self():
    class Dice:
        def roll(self, ctx, dice: str = '1d6'):
            pass
    assert [p.name for p in params_of(Dice().roll)] == ['dice']


@pytest.mark.parametrize('func', [
    lambda ctx, *words: None,
    lambda ctx, **options: None,
])
def test_variable_arguments_are_refused(func):
    with pytest.raises(TypeError, match='can only take named arguments'):
        params_of(func)


def test_unsupported_types_are_refused():
    def odd(ctx, when: list = None):
        pass
    with pytest.raises(TypeError, match='commands take str, int, float, bool, Literal'):
        params_of(odd)


def test_a_handler_needs_ctx():
    with pytest.raises(TypeError, match='needs a ctx argument'):
        params_of(lambda: None)
