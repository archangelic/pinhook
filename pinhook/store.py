from collections.abc import Iterator, Mapping
from types import MappingProxyType
import json
import os
import threading
from typing import Any


def to_json(data: Any) -> str:
    """data as the JSON pinhook saves: indented, with sorted keys."""
    return json.dumps(data, indent=2, sort_keys=True)


def write_text(path: str, text: str) -> None:
    """Write text to path, creating its folder if needed."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    # write to a temp file first so a crash can't leave a half written file
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, path)


def write_json(path: str, data: Any) -> None:
    """Write data to path as JSON, creating its folder if needed."""
    write_text(path, to_json(data))


def read_json(path: str | None, default: Any, what: str | None = None) -> Any:
    """The JSON in path, or default when there's no file. A file that isn't JSON raises
    ValueError, saying "couldn't read" what, the path unless given, and the problem."""
    if not path or not os.path.exists(path):
        return default
    with open(path) as f:
        try:
            return json.load(f)
        except ValueError as e:
            raise ValueError("couldn't read {}: {}".format(what or path, e))


def read_json_object(path: str | None) -> dict[str, Any]:
    """The JSON object in path, as a dict, or {} when there's no file."""
    data = read_json(path, {})
    if not isinstance(data, dict):
        raise ValueError('{} should hold a JSON object'.format(path))
    return data


class PluginConfig(Mapping[str, Any]):
    """A plugin's settings from plugin_config in the bot's config. Read only.

    Plugins get theirs as `msg.config`: their own section, keyed by plugin file
    name, and `msg.config.shared` for the section every plugin can read.
    """

    def __init__(self, name: str, settings: Mapping[str, Any] | None = None,
                 shared: Mapping[str, Any] | None = None) -> None:
        self.name = name
        self._settings = dict(settings or {})
        self.shared = MappingProxyType(dict(shared or {}))

    def __getitem__(self, key: str) -> Any:
        try:
            return self._settings[key]
        except KeyError:
            raise KeyError("plugin_config has no '{}' setting for the {} plugin".format(
                key, self.name)) from None

    def __iter__(self) -> Iterator[str]:
        return iter(self._settings)

    def __len__(self) -> int:
        return len(self._settings)

    def __repr__(self) -> str:
        return 'PluginConfig({!r}, {!r})'.format(self.name, self._settings)


class Store(dict[str, Any]):
    """A plugin's saved data: a dict that's kept between messages, reloads and restarts.

    Plugins get theirs as `msg.store`. The bot saves it after each plugin call
    if anything in it changed, nested changes included.

    Values have to be things JSON can hold: strings, numbers, lists, dicts,
    True, False and None. Keys are saved as strings.
    """

    def __init__(self, name: str, path: str | None = None) -> None:
        super().__init__()
        self.name = name
        self.path = path
        self._lock = threading.Lock()
        data = read_json(path, {}, 'the store for {} from {}'.format(name, path))
        if not isinstance(data, dict):
            raise ValueError('the store for {} in {} should hold a JSON object'.format(
                name, path))
        self.update(data)
        self._saved = self._snapshot()

    def _snapshot(self) -> str:
        try:
            return to_json(self)
        except (TypeError, ValueError) as e:
            raise TypeError('the store for {} can only hold JSON values (strings, numbers, lists, '
                            'dicts, True, False and None): {}'.format(self.name, e)) from e

    def save_if_changed(self) -> None:
        """Save the store if anything in it changed since it was last saved."""
        with self._lock:
            snapshot = self._snapshot()
            if snapshot == self._saved:
                return
            if self.path:
                write_text(self.path, snapshot)
            self._saved = snapshot
