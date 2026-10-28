from collections.abc import Mapping
from types import MappingProxyType
import json
import os


def write_json(path, data):
    """Write data to path as JSON, creating its folder if needed."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    # write to a temp file first so a crash can't leave a half written file
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


class PluginConfig(Mapping):
    """A plugin's settings from plugin_config in the bot's config. Read only.

    Plugins get theirs as `msg.config`: their own section, keyed by plugin file
    name, and `msg.config.shared` for the section every plugin can read.
    """

    def __init__(self, name, settings=None, shared=None):
        self.name = name
        self._settings = dict(settings or {})
        self.shared = MappingProxyType(dict(shared or {}))

    def __getitem__(self, key):
        try:
            return self._settings[key]
        except KeyError:
            raise KeyError("plugin_config has no '{}' setting for the {} plugin".format(key, self.name)) from None

    def __iter__(self):
        return iter(self._settings)

    def __len__(self):
        return len(self._settings)

    def __repr__(self):
        return 'PluginConfig({!r}, {!r})'.format(self.name, self._settings)


class Store(dict):
    """A plugin's saved data: a dict that's kept between messages, reloads and restarts.

    Plugins get theirs as `msg.store`. The bot saves it after each plugin call
    if anything in it changed, nested changes included.

    Values have to be things JSON can hold: strings, numbers, lists, dicts,
    True, False and None. Keys are saved as strings.
    """

    def __init__(self, name, path=None):
        super().__init__()
        self.name = name
        self.path = path
        if path and os.path.exists(path):
            with open(path) as f:
                try:
                    data = json.load(f)
                except ValueError as e:
                    raise ValueError("couldn't read the store for {} from {}: {}".format(name, path, e))
            if not isinstance(data, dict):
                raise ValueError('the store for {} in {} should hold a JSON object'.format(name, path))
            self.update(data)
        self._saved = self._snapshot()

    def _snapshot(self):
        try:
            return json.dumps(self, sort_keys=True)
        except (TypeError, ValueError) as e:
            raise TypeError('the store for {} can only hold JSON values (strings, numbers, lists, dicts, True, False and None): {}'.format(self.name, e)) from e

    def save_if_changed(self):
        """Save the store if anything in it changed since it was last saved."""
        snapshot = self._snapshot()
        if snapshot == self._saved:
            return
        if self.path:
            write_json(self.path, json.loads(snapshot))
        self._saved = snapshot
