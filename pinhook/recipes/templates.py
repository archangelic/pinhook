"""Recipe templates: {name} for a variable, and {name|filter} to change it.

    'Tonight: {game}. {members|random} goes first'
    '{nick} hugs {arg|default:everyone}'
    '{sorted.summary}'

A template is parsed once, when its recipe loads, and a variable's value is only
ever text: an arg holding {nick} stays {nick}. Control characters are stripped
from values, so text from chat can't become a CTCP message. Write {{ and }} for
literal braces. This is never Python's str.format, whose attribute access is a
well-known way out of a sandbox: {name.key} only looks a key up in a mapping.
"""
from collections.abc import Callable
import random as random_module
import re

# a variable path: a name, then .key lookups
PATH = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_-]+)*$')
FILTER = re.compile(r'^([a-z_][a-z0-9_]*)(?::(.*))?$', re.S)
# control characters, stripped from values
CONTROL = re.compile('[\x00-\x1f\x7f]')

# filter name: the function, taking the value and its argument
FILTERS: dict[str, Callable] = {}


class TemplateError(ValueError):
    """A template that can't be parsed, or uses a filter that doesn't exist."""


def template_filter(name):
    """Register a filter, for plugins: a function taking the value and the text after
    a colon, like 'everyone' in {arg|default:everyone}, or None.

        @recipes.template_filter('shout')
        def shout(value, arg):
            return text(value).upper() + '!'
    """
    def register(func):
        FILTERS[name] = func
        return func
    return register


def text(value):
    """How a value reads in a reply: a list as 'a, b, c', nothing as ''."""
    if value is None:
        return ''
    if isinstance(value, (list, tuple)):
        return ', '.join(text(item) for item in value)
    if isinstance(value, dict):
        return ', '.join('{}: {}'.format(k, text(v)) for k, v in value.items())
    return str(value)


def as_list(value):
    if value is None or value == '':
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


@template_filter('join')
def join(value, arg):
    return (arg if arg is not None else ', ').join(text(item) for item in as_list(value))


@template_filter('sorted')
def sorted_(value, arg):
    return sorted(as_list(value), key=lambda item: text(item).lower())


@template_filter('count')
def count(value, arg):
    return len(as_list(value))


@template_filter('first')
def first(value, arg):
    items = as_list(value)
    return items[0] if items else ''


@template_filter('last')
def last(value, arg):
    items = as_list(value)
    return items[-1] if items else ''


@template_filter('random')
def random(value, arg):
    items = as_list(value)
    return random_module.choice(items) if items else ''


@template_filter('upper')
def upper(value, arg):
    return text(value).upper()


@template_filter('lower')
def lower(value, arg):
    return text(value).lower()


@template_filter('default')
def default(value, arg):
    return value if text(value) else (arg or '')


class Template:
    """A parsed template.

    Attributes:
        source: the template as written.
        names: the variables it uses, by their first name, like 'sorted' for
            {sorted.summary}.
    """

    def __init__(self, source):
        self.source = source
        self.parts = parse(source)
        self.names = [part[0].split('.')[0] for part in self.parts if isinstance(part, tuple)]

    def render(self, lookup):
        """The template with its variables filled in. lookup(path) gives a value."""
        out = []
        for part in self.parts:
            if isinstance(part, str):
                out.append(part)
                continue
            path, filters = part
            value = lookup(path)
            for name, arg in filters:
                value = FILTERS[name](value, arg)
            out.append(CONTROL.sub('', text(value)))
        return ''.join(out)


def parse(source):
    """A template's pieces: plain strings, and (path, [(filter, arg)]) for variables."""
    if not isinstance(source, str):
        raise TemplateError('a template should be text, not {}'.format(type(source).__name__))
    parts, literal, i = [], [], 0
    while i < len(source):
        char = source[i]
        if source.startswith('{{', i) or source.startswith('}}', i):
            literal.append(char)
            i += 2
        elif char == '{':
            end = source.find('}', i)
            if end == -1:
                raise TemplateError('a {{ is never closed in {!r}'.format(source))
            if literal:
                parts.append(''.join(literal))
                literal = []
            parts.append(variable(source[i + 1:end], source))
            i = end + 1
        elif char == '}':
            raise TemplateError('a }} has no {{ before it in {!r}, write }}}} for a brace'
                                .format(source))
        else:
            literal.append(char)
            i += 1
    if literal:
        parts.append(''.join(literal))
    return parts


def variable(inside, source):
    path, *pipes = inside.split('|')
    path = path.strip()
    # spaces around a filter's name don't matter, but in its argument they do
    pipes = [pipe.lstrip() if ':' in pipe else pipe.strip() for pipe in pipes]
    if not PATH.match(path):
        raise TemplateError('{{{}}} in {!r} should be a name, like {{nick}}'.format(
            inside, source))
    filters = []
    for pipe in pipes:
        match = FILTER.match(pipe)
        if not match or match.group(1) not in FILTERS:
            raise TemplateError('{!r} in {!r} is not a filter. The filters are {}'.format(
                pipe, source, ', '.join(sorted(FILTERS))))
        filters.append((match.group(1), match.group(2)))
    return path, filters
