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
