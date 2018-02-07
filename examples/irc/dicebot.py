import pinhook.bot

ph = pinhook.bot.Bot(
    channels=['#dicechannel'],
    nickname='dicebot',
    server='irc.freenode.net',
    ops=['archangelic']
)
ph.start()
