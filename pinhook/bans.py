import fnmatch
import json
import os

from .store import write_json
from .transport.base import casefold

# ban and op entries can be one of:
#   a nick                  troll
#   a hostmask              *!*@203.0.113.7  (* and ? are wildcards)
#   a services account      $a:troll


def is_account(entry):
    return entry.startswith('$a:')


def is_mask(entry):
    return '!' in entry or '@' in entry


def matches(entry, nick, user=None, host=None, account=None, fold=casefold):
    # fold is the server's lowercasing. Its rfc1459 one turns [ ] into { }, so nicks
    # can't break the wildcard match
    entry = fold(entry)
    if is_account(entry):
        return bool(account) and fold(account) == entry[len('$a:'):]
    if is_mask(entry):
        mask = fold('{}!{}@{}'.format(nick, user or '', host or ''))
        return fnmatch.fnmatchcase(mask, entry)
    return fold(nick) == entry


def matches_any(entries, nick, user=None, host=None, account=None, fold=casefold):
    return any(matches(e, nick, user, host, account, fold) for e in entries)


def load(path):
    if not path or not os.path.exists(path):
        return []
    with open(path) as f:
        try:
            entries = json.load(f)
        except ValueError as e:
            raise ValueError("couldn't read ban file {}: {}".format(path, e))
    if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
        raise ValueError('ban file {} should be a list of ban entries'.format(path))
    return entries


def save(path, entries):
    if not path:
        return
    write_json(path, entries)
