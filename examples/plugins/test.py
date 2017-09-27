import pinhook.plugin

@pinhook.plugin.register('!test')
def test(**kwargs):
    return pinhook.plugin.message("Test")

