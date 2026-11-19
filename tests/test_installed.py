"""Plugins from installed packages, named in the plugins option."""
import sys

import pytest

from pinhook.testing import PluginError, TestBot

PLUGIN = '''
from pinhook import Plugin, command


class Dice(Plugin):
    def setup(self, previous):
        self.loads = previous.loads + 1 if previous else 1

    @command('roll')
    async def roll(self, ctx, sides: int = 6):
        ctx.store['rolls'] = ctx.store.get('rolls', 0) + 1
        units = ctx.config.get('units', 'pips')
        await ctx.reply('{} rolled {} {} (load {})'.format(ctx.nick, sides, units, self.loads))
'''


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """Install a package offering plugins, as {entry point name: module code}."""
    def install(package, plugins):
        site = tmp_path / 'site'
        code = site / package
        code.mkdir(parents=True)
        (code / '__init__.py').write_text('')
        lines = ['[pinhook.plugins]']
        for name, source in plugins.items():
            (code / (name + '.py')).write_text(source)
            lines.append('{} = {}.{}'.format(name, package, name))
        info = site / '{}-1.0.dist-info'.format(package)
        info.mkdir()
        (info / 'METADATA').write_text('Metadata-Version: 2.1\nName: {}\nVersion: 1.0\n'
                                       .format(package))
        (info / 'entry_points.txt').write_text('\n'.join(lines) + '\n')
        monkeypatch.syspath_prepend(str(site))
        for module in [m for m in sys.modules if m.split('.')[0] == package]:
            monkeypatch.delitem(sys.modules, module)
    return install


def test_an_installed_plugin_loads_by_its_entry_point_name(tmp_path, installed):
    installed('dicepack', {'dice': PLUGIN})
    bot = TestBot(plugin_dir=str(tmp_path / 'plugins'), plugins=['dice'],
                  plugin_config={'dice': {'units': 'dots'}})
    assert bot.say('!roll 20', nick='ana') == ['ana rolled 20 dots (load 1)']
    assert bot.store('dice') == {'rolls': 1}
    assert [c.plugin for c in bot.commands()] == ['dice']


def test_reload_makes_new_instances_of_an_installed_plugin(tmp_path, installed):
    installed('dicepack2', {'dice': PLUGIN})
    bot = TestBot(plugin_dir=str(tmp_path / 'plugins'), plugins=['dice'], ops=['mal'])
    bot.say('!reload', nick='mal')
    assert bot.say('!roll', nick='ana') == ['ana rolled 6 pips (load 2)']


def test_a_plugin_nothing_installed_offers_fails_to_load(tmp_path, installed):
    installed('dicepack3', {'dice': PLUGIN})
    with pytest.raises(PluginError, match="no installed plugin called dcie, did you mean 'dice'"):
        TestBot(plugin_dir=str(tmp_path / 'plugins'), plugins=['dcie'])


def test_a_file_and_an_installed_plugin_cant_share_a_name(tmp_path, installed):
    installed('dicepack4', {'dice': PLUGIN})
    plugins = tmp_path / 'plugins'
    plugins.mkdir()
    (plugins / 'dice.py').write_text(PLUGIN.replace('rolled', 'threw'))
    with pytest.raises(PluginError, match='a file in .* and an installed plugin too'):
        TestBot(plugin_dir=str(plugins), plugins=['dice'])


def test_plugins_has_to_be_a_list_of_names(tmp_path):
    with pytest.raises(ValueError, match='plugins should list installed plugins by name'):
        TestBot(plugin_dir=str(tmp_path), plugins='vermilion')
