from pinhook import plugin


def test_command_hide_option(plugin_dir):
    path = plugin_dir('hidden_cmd', (
        "import pinhook.plugin as p\n"
        "@p.command('!secret', hide=True)\n"
        "def secret(msg): pass\n"
    ))
    plugin.load_plugins(path)
    assert plugin.cmds['!secret'].hide


def test_command_not_hidden_by_default(plugin_dir):
    path = plugin_dir('visible_cmd', (
        "import pinhook.plugin as p\n"
        "@p.command('!visible')\n"
        "def visible(msg): pass\n"
    ))
    plugin.load_plugins(path)
    assert not plugin.cmds['!visible'].hide


def test_message_splits_string_lines():
    assert plugin.message('one\ntwo').msg == ['one', 'two']


def test_message_splits_lines_inside_list():
    assert plugin.message(['one\ntwo', 'three']).msg == ['one', 'two', 'three']


def test_action_splits_lines_inside_list():
    assert plugin.action(('one\r\ntwo',)).msg == ['one', 'two']


def test_reload_picks_up_plugin_changes(plugin_dir):
    path = plugin_dir('changing', (
        "import pinhook.plugin as p\n"
        "@p.command('!cmd', help_text='old')\n"
        "def cmd(msg): pass\n"
    ))
    plugin.load_plugins(path)
    plugin_dir('changing', (
        "import pinhook.plugin as p\n"
        "@p.command('!cmd', help_text='new and longer')\n"
        "def cmd(msg): pass\n"
    ))
    plugin.load_plugins(path)
    assert plugin.cmds['!cmd'].help_text == 'new and longer'


def test_plugin_named_like_stdlib_module_does_not_replace_it(plugin_dir):
    import json
    json_file = json.__file__
    path = plugin_dir('json', (
        "import pinhook.plugin as p\n"
        "@p.command('!j')\n"
        "def j(msg): pass\n"
    ))
    plugin.load_plugins(path)
    assert '!j' in plugin.cmds
    assert json.__file__ == json_file
    assert not hasattr(json, 'j')


def test_reload_removes_deleted_plugins(plugin_dir, tmp_path):
    path = plugin_dir('gone', (
        "import pinhook.plugin as p\n"
        "@p.command('!gone')\n"
        "def gone(msg): pass\n"
    ))
    plugin.load_plugins(path)
    (tmp_path / 'gone.py').unlink()
    plugin.load_plugins(path)
    assert '!gone' not in plugin.cmds
    assert '!gone' not in plugin.plugins


def test_reload_keeps_disabled_plugins_disabled(plugin_dir):
    path = plugin_dir('stays', (
        "import pinhook.plugin as p\n"
        "@p.command('!stays')\n"
        "def stays(msg): pass\n"
    ))
    plugin.load_plugins(path)
    plugin.plugins['!stays'].disable()
    plugin.load_plugins(path)
    assert not plugin.plugins['!stays'].enabled


def test_deprecated_decorators_do_not_use_deprecated_logging(recwarn):
    plugin.register('!old')(lambda msg: None)
    plugin.ops('!old', 'ops only')(lambda msg: None)
    assert not [w for w in recwarn if "'warn' method is deprecated" in str(w.message)]
