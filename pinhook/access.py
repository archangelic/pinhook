"""Who can trigger what: access levels, grants and denies, and the entries ops and bans use.

An entry names people: a nick, a hostmask or a $a:account, as the transport
understands them (see transport/identity.py). Grants and denies can also name a
group: one from the access config's groups, ops, or one of the transport's built-in
groups, like IRC's chanops (+o in the channel), voiced (+v or more) and logged-in.
The rules are here, and who matches an entry or is in a group is the transport's to say.
"""
import json
import os

from .recipes.engine import RECIPES
from .store import write_json
from .transport.identity import entry_kind

# least strict first
LEVELS = ('open', 'restricted', 'ops')


KINDS = {'nick': ('a nick', 'nicks'), 'mask': ('a hostmask', 'hostmasks'),
         'account': ('an account', '$a:accounts')}


def entry_problem(transport, entry):
    """Why transport can't use entry, which isn't a group, or None if it can."""
    kind = entry_kind(entry)
    if kind in transport.entry_kinds:
        return None
    takes = [KINDS[k][1] for k in KINDS if k in transport.entry_kinds]
    return "{} is {}, which {} doesn't use. It takes {}".format(
        entry, KINDS[kind][0], transport.name, ' and '.join(takes))


def check_entries(transport, entries, where):
    """Raise ValueError naming where, for the first entry transport can't use."""
    for entry in entries:
        problem = entry_problem(transport, entry)
        if problem:
            raise ValueError('{}: {}'.format(where, problem))


def matches_any(transport, entries, who):
    """True if any of entries, which aren't groups, names who."""
    return any(transport.matches(entry, who) for entry in entries)


def load_bans(path):
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


def save_bans(path, entries):
    if path:
        write_json(path, entries)


class Rule:
    """The access settings for one plugin or command: its level, if set, and who's allowed
    and denied."""

    def __init__(self, level=None, allow=(), deny=(), commands=None):
        self.level = level
        self.allow = list(allow)
        self.deny = list(deny)
        self.commands = commands or {}


def entry_list(value, where):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(e, str) and e for e in value):
        raise ValueError('{} should be a list of entries, like ["$a:carol"]'.format(where))
    return value


def parse_rule(value, where, commands=True):
    # weather: ops, or weather: {allow: [...], deny: [...], commands: {...}}.
    # an allow list makes it restricted
    if isinstance(value, str):
        if value not in LEVELS:
            raise ValueError('{} should be open, restricted or ops, not {!r}'.format(where, value))
        return Rule(value)
    if not isinstance(value, dict):
        raise ValueError('{} should be a level, like restricted, or settings like '
                         '{{allow: [...]}}'.format(where))
    known = {'level', 'allow', 'deny'} | ({'commands'} if commands else set())
    unknown = sorted(set(value) - known)
    if unknown:
        raise ValueError('{} has settings pinhook doesn\'t know: {}. It takes {}'.format(
            where, ', '.join(unknown), ', '.join(sorted(known))))
    allow = entry_list(value.get('allow', []), where + '.allow')
    deny = entry_list(value.get('deny', []), where + '.deny')
    level = value.get('level')
    if level is not None and level not in LEVELS:
        raise ValueError('{}.level should be open, restricted or ops, not {!r}'.format(
            where, level))
    if allow and level in ('open', 'ops'):
        raise ValueError('{} has an allow list, which only means something when it\'s '
                         'restricted, but its level is {}'.format(where, level))
    if allow:
        level = 'restricted'
    rule = Rule(level, allow, deny)
    if commands:
        cmds = value.get('commands') or {}
        if not isinstance(cmds, dict):
            raise ValueError('{}.commands should map command names to their settings'.format(
                where))
        rule.commands = {name: parse_rule(setting, '{}.commands.{}'.format(where, name), False)
                         for name, setting in cmds.items()}
    return rule


def parse_config(config, builtin_groups):
    """The access section of the config, checked: (default level, groups, {plugin: Rule}).
    builtin_groups are the names config groups can't have."""
    config = config or {}
    if not isinstance(config, dict):
        raise ValueError('access should be settings like {default: open, plugins: {...}}')
    unknown = sorted(set(config) - {'default', 'groups', 'plugins', 'recipes'})
    if unknown:
        raise ValueError("access has settings pinhook doesn't know: {}. It takes default, "
                         "groups, plugins and recipes".format(', '.join(unknown)))
    default = config.get('default', 'open')
    if default not in LEVELS:
        raise ValueError('access.default should be open, restricted or ops, not {!r}'.format(
            default))
    groups = config.get('groups') or {}
    if not isinstance(groups, dict):
        raise ValueError('access.groups should map group names to lists of entries')
    for name in groups:
        if name in builtin_groups:
            raise ValueError("access.groups can't have a group called {}, pinhook has a "
                             "built-in one".format(name))
        if entry_kind(name) != 'nick':
            raise ValueError("access.groups: {} looks like an entry, not a group name".format(
                name))
    groups = {name: entry_list(entries, 'access.groups.' + name)
              for name, entries in groups.items()}
    plugins = config.get('plugins') or {}
    if not isinstance(plugins, dict):
        raise ValueError('access.plugins should map plugin names to their settings')
    rules = {name: parse_rule(value, 'access.plugins.' + name) for name, value in plugins.items()}
    # recipes are commands of their own pseudo plugin, so their settings sit under it
    recipes = config.get('recipes') or {}
    if not isinstance(recipes, dict):
        raise ValueError('access.recipes should map recipe names to their settings')
    if recipes:
        rules[RECIPES] = Rule(commands={
            name: parse_rule(value, 'access.recipes.' + name, commands=False)
            for name, value in recipes.items()})
    return default, groups, rules


class Access:
    """Who can trigger each plugin and command: the access config, with !allow and !deny on top.

    A command's level is the one set for it under its plugin's commands, if there is
    one. Otherwise it's the stricter of what its author chose (ops=True or
    restricted=True) and its plugin's level, which is the default unless the config
    sets one. Listeners go by their plugin's level.

    Ops can trigger anything. Otherwise a deny for the command or its plugin keeps
    someone off it, open lets everyone else on, and restricted needs a grant for the
    command or its plugin. Bans beat all of it.

    Args:
        bot: the bot, for its plugins, ops, bans and who has which modes where.
        config: the access section of the config.
        path: where !allow and !deny are saved, or None to keep them in memory.
    """

    def __init__(self, bot, config, path):
        self.bot = bot
        self.path = path
        self.default, self.groups, self.rules = self.parse(config)
        self.saved = self.load()

    def configure(self, config):
        """Use a new access section, like on !reload. Raises ValueError, keeping the old one,
        if it has a problem."""
        self.default, self.groups, self.rules = self.parse(config)

    def parse(self, config):
        # the config, checked, with every entry one the transport can use
        default, groups, rules = parse_config(config, self.builtin_groups())
        names = set(groups) | self.builtin_groups()
        transport = self.bot.transport

        def check(entries, where):
            check_entries(transport, [e for e in entries if e not in names], where)
        for name, entries in groups.items():
            check(entries, 'access.groups.' + name)
        for plugin, rule in rules.items():
            where = 'access.recipes' if plugin == RECIPES else 'access.plugins.' + plugin
            for command, own in [(None, rule)] + list(rule.commands.items()):
                place = where if command is None else (
                    where + '.' + command if plugin == RECIPES else
                    '{}.commands.{}'.format(where, command))
                check(own.allow, place + '.allow')
                check(own.deny, place + '.deny')
        return default, groups, rules

    def builtin_groups(self):
        # ops, which the core knows, and the transport's own
        return {'ops'} | set(self.bot.transport.groups)

    def load(self):
        if not self.path or not os.path.exists(self.path):
            return {}
        with open(self.path) as f:
            try:
                saved = json.load(f)
            except ValueError as e:
                raise ValueError("couldn't read {}: {}".format(self.path, e))
        if not isinstance(saved, dict):
            raise ValueError('{} should hold a JSON object'.format(self.path))
        return saved

    def save(self):
        if self.path:
            write_json(self.path, self.saved)

    # levels and entries

    def level(self, handler):
        """A command or listener's level: 'open', 'restricted' or 'ops'."""
        rule = self.rules.get(handler.plugin, Rule())
        author = 'open'
        if handler.kind == 'command':
            own = rule.commands.get(handler.name)
            if own and own.level:
                return own.level
            author = 'ops' if handler.ops else 'restricted' if handler.restricted else 'open'
        plugin_level = rule.level or self.default
        return max(author, plugin_level, key=LEVELS.index)

    def saved_rule(self, plugin, command=None):
        entry = self.saved.get(plugin, {})
        if command is not None:
            entry = entry.get('commands', {}).get(command, {})
        return entry

    def entries(self, handler, which):
        """Everyone allowed, or denied, a command or listener: the config's, then !allow's
        or !deny's, for it and for its plugin."""
        rule = self.rules.get(handler.plugin, Rule())
        found = getattr(rule, which) + self.saved_rule(handler.plugin).get(which, [])
        if handler.kind == 'command':
            own = rule.commands.get(handler.name, Rule())
            found += getattr(own, which) + self.saved_rule(handler.plugin, handler.name).get(
                which, [])
        return found

    def is_group(self, entry):
        return entry in self.groups or entry in self.builtin_groups()

    def matches(self, who, entries, channel, groups_seen=()):
        """True if who is one of entries. channel is where they are, for groups like chanops."""
        transport = self.bot.transport
        for entry in entries:
            if entry in self.groups:
                if entry not in groups_seen and self.matches(who, self.groups[entry], channel,
                                                             groups_seen + (entry,)):
                    return True
            elif entry == 'ops':
                if self.bot.is_op(who):
                    return True
            elif entry in transport.groups:
                if transport.in_group(entry, who, channel):
                    return True
            elif transport.matches(entry, who):
                return True
        return False

    # checks

    def allows(self, who, handler, channel=None):
        """True if who can trigger a command or listener in channel, None for a private
        message. Bans are checked before this."""
        if self.bot.is_op(who):
            return True
        level = self.level(handler)
        if level == 'ops' or self.matches(who, self.entries(handler, 'deny'), channel):
            return False
        return level == 'open' or self.matches(who, self.entries(handler, 'allow'), channel)

    def can_run(self, who, command, channel=None):
        """True if who can trigger command in channel, the same check the bot makes.

        Args:
            who: a Source, or anything with nick, user, host and account.
            command: a command's name without a prefix, or its Handler.
            channel: where they'd run it, or None for a private message.
        """
        handler = self.bot.registry.commands.get(command) if isinstance(command, str) else command
        if handler is None or self.bot.ignores(who):
            return False
        return self.allows(who, handler, channel)

    # !allow, !deny and !revoke

    def add(self, which, plugin, command, entry):
        """Save a grant ('allow') or deny for a plugin, or one of its commands. False if it
        was already there."""
        entry_dict = self.saved.setdefault(plugin, {})
        if command is not None:
            entry_dict = entry_dict.setdefault('commands', {}).setdefault(command, {})
        found = entry_dict.setdefault(which, [])
        fold = self.bot.transport.casefold
        if any(fold(e) == fold(entry) for e in found):
            return False
        found.append(entry)
        self.save()
        return True

    def remove(self, plugin, command, wanted):
        """Take entries off a plugin or command's saved grants and denies. wanted says which.
        Returns what came off."""
        entry_dict = self.saved_rule(plugin, command)
        removed = []
        for which in ('allow', 'deny'):
            kept = []
            for entry in entry_dict.get(which, []):
                (removed if wanted(entry) else kept).append(entry)
            if which in entry_dict:
                entry_dict[which] = kept
        if removed:
            self.save()
        return removed

    def in_config(self, plugin, command, wanted):
        rule = self.rules.get(plugin, Rule())
        if command is not None:
            rule = rule.commands.get(command, Rule())
        return [e for e in rule.allow + rule.deny if wanted(e)]
