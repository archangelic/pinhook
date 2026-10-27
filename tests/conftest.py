import pytest

from pinhook import plugin


@pytest.fixture(autouse=True)
def clear_plugins():
    # plugin registries are module level, so clear them between tests
    plugin.cmds.clear()
    plugin.lstnrs.clear()
    plugin.plugins.clear()
    yield
    plugin.cmds.clear()
    plugin.lstnrs.clear()
    plugin.plugins.clear()


@pytest.fixture
def plugin_dir(tmp_path):
    def write_plugin(name, code):
        (tmp_path / '{}.py'.format(name)).write_text(code)
        return str(tmp_path)
    return write_plugin
