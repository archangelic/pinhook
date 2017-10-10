import pinhook.plugin

@pinhook.plugin.register('!test')
def test(msg):
    return pinhook.plugin.message("{}: Test".format(msg.nick))

