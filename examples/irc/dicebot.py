from pinhook.bot import Bot

ph = Bot(
    channels=['#dicechannel'],
    nickname='dicebot',
    server='irc.freenode.net',
    ops=['archangelic']
)
ph.start()
