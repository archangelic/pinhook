import pinhook.plugin

def test(**kwargs):
    return pinhook.plugin.message("Test")

pinhook.plugin.add_plugin('!test', test)
