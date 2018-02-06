import pinhook.plugin

@pinhook.plugin.register('!test')
def test(msg):
    msg.logger.info('This is test log output')
    return pinhook.plugin.message("{}: Test".format(msg.nick))

