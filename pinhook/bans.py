import fnmatch
import json
import os

import irc.strings

# ban and op entries can be one of:
#   a nick                  troll
#   a hostmask              *!*@203.0.113.7  (* and ? are wildcards)
#   a services account      $a:troll


def is_account(entry):
    return entry.startswith('$a:')


def is_mask(entry):
    return '!' in entry or '@' in entry


def matches(entry, nick, user=None, host=None, account=None):
    # irc lowercasing also turns [ ] into { }, so nicks can't break the wildcard match
    entry = irc.strings.lower(entry)
    if is_account(entry):
        return bool(account) and irc.strings.lower(account) == entry[len('$a:'):]
    if is_mask(entry):
        mask = irc.strings.lower('{}!{}@{}'.format(nick, user or '', host or ''))
        return fnmatch.fnmatchcase(mask, entry)
    return irc.strings.lower(nick) == entry


def matches_any(entries, nick, user=None, host=None, account=None):
    return any(matches(e, nick, user, host, account) for e in entries)


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
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    # write to a temp file first so a crash can't leave a half written ban file
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(entries, f, indent=2)
    os.replace(tmp, path)
