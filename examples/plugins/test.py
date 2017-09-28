import pinhook.plugin

@pinhook.plugin.register('!test')
def test(**kwargs):
    nick = kwargs['nick']
    return pinhook.plugin.message("{}: Test".format(nick))

