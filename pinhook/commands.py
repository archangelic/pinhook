"""Typed command arguments: read from a handler's signature, parsed from chat, and shown in help.

    async def roll(self, ctx, dice: Annotated[str, 'dice like 2d6'] = '1d6', times: int = 1)

reads `!roll 2d20 3` as dice='2d20', times=3. Arguments are split shlex-style,
so quotes group words, and a final str argument takes the rest of the line as
written. Bad input gets the usage line, `roll [dice=1d6] [times=1]`.
"""
import inspect
import types
import typing

# what bool arguments accept, in either case
TRUE = {'true', 'yes', 'on', '1'}
FALSE = {'false', 'no', 'off', '0'}
SUPPORTED = (str, int, float, bool)
# how a type is named to someone typing the command
KINDS = {int: 'a whole number', float: 'a number', str: 'text'}


class UsageError(Exception):
    """The arguments don't fit the command."""


class Param:
    """One argument a command takes.

    Attributes:
        name: the argument's name.
        type: str, int, float or bool. For a Literal, the type of its choices.
        choices: a Literal's allowed values, or None.
        default: the default value, or Param.REQUIRED.
        description: from Annotated[type, 'description'], or None.
    """
    REQUIRED = inspect.Parameter.empty

    def __init__(self, name, type_, default, description=None, choices=None):
        self.name = name
        self.type = type_
        self.default = default
        self.description = description
        self.choices = choices

    @property
    def required(self):
        return self.default is Param.REQUIRED

    def usage(self):
        if self.required:
            return '<{}>'.format('|'.join(map(str, self.choices)) if self.choices else self.name)
        if self.default is None:
            return '[{}]'.format(self.name)
        return '[{}={}]'.format(self.name, str(self.default).lower()
                                if isinstance(self.default, bool) else self.default)

    def convert(self, text):
        if self.choices:
            for choice in self.choices:
                if str(choice) == text:
                    return choice
            raise UsageError('{} must be one of {}'.format(self.name, ', '.join(map(str,
                                                                                    self.choices))))
        if self.type is bool:
            if text.lower() in TRUE:
                return True
            if text.lower() in FALSE:
                return False
            raise UsageError('{} must be true or false'.format(self.name))
        try:
            return self.type(text)
        except ValueError:
            raise UsageError('{} must be {}'.format(self.name, KINDS[self.type]))


def params_of(func, skip=1):
    """The typed arguments func takes after ctx. Raises TypeError for ones it can't take.

    skip is how many arguments come first: 1 for ctx, 2 for a method's self and ctx.
    """
    signature = inspect.signature(func)
    hints = typing.get_type_hints(func, include_extras=True)
    params = list(signature.parameters.values())
    if len(params) < skip:
        raise TypeError('{} needs a ctx argument'.format(func.__qualname__))
    found = []
    for param in params[skip:]:
        if param.kind not in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY):
            raise TypeError('{} can only take named arguments, not {}'.format(
                func.__qualname__, param))
        found.append(read_param(func, param, hints.get(param.name, str)))
    return found


def read_param(func, param, hint):
    description = None
    if typing.get_origin(hint) is typing.Annotated:
        hint, *extras = typing.get_args(hint)
        description = next((e for e in extras if isinstance(e, str)), None)
    default = param.default
    hint, optional = unwrap_optional(hint)
    if optional and default is Param.REQUIRED:
        default = None
    choices = None
    if typing.get_origin(hint) is typing.Literal:
        choices = typing.get_args(hint)
        hint = type(choices[0])
    if hint not in SUPPORTED or (choices and not all(isinstance(c, hint) for c in choices)):
        raise TypeError('{} argument {} has type {}, commands take str, int, float, bool, '
                        'Literal and Optional'.format(func.__qualname__, param.name, hint))
    return Param(param.name, hint, default, description, choices)


def unwrap_optional(hint):
    # Optional[int] and int | None
    origin = typing.get_origin(hint)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        if len(args) == 1 and len(typing.get_args(hint)) == 2:
            return args[0], True
    return hint, False


def next_word(text, start):
    """The next shlex-style word in text from start, and where it ended. ('', end) at the end.

    Quotes group words. An unclosed quote is read as plain text, never an error.
    """
    i = start
    while i < len(text) and text[i].isspace():
        i += 1
    if i >= len(text):
        return None, i
    if text[i] in '"\'':
        close = text.find(text[i], i + 1)
        if close != -1:
            return text[i + 1:close], close + 1
    end = i
    while end < len(text) and not text[end].isspace():
        end += 1
    return text[i:end], end


def parse(params, text):
    """The arguments text gives, as a dict for calling the handler. Raises UsageError."""
    values = {}
    position = 0
    for index, param in enumerate(params):
        last = index == len(params) - 1
        if last and param.type is str and not param.choices:
            # the last str takes the rest of the line, as written
            rest = text[position:].strip()
            if rest:
                values[param.name] = rest
            elif param.required:
                raise UsageError('missing {}'.format(param.name))
            position = len(text)
            continue
        word, position = next_word(text, position)
        if word is None:
            if param.required:
                raise UsageError('missing {}'.format(param.name))
            continue
        values[param.name] = param.convert(word)
    extra, _ = next_word(text, position)
    if extra is not None:
        raise UsageError('too many arguments')
    return values


def usage(name, params):
    """The usage line, like 'roll [dice=1d6] [times=1]'."""
    return ' '.join([name] + [p.usage() for p in params])


def describe(params):
    """A line for each argument that has a description or choices, for !help."""
    lines = []
    for param in params:
        parts = [param.description] if param.description else []
        if param.choices:
            parts.append('one of ' + ', '.join(map(str, param.choices)))
        if parts:
            lines.append('{}: {}'.format(param.name, '; '.join(parts)))
    return lines
