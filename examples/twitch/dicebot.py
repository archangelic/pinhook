from pinhook.bot import TwitchBot

bot = TwitchBot(
    nickname='dicebot',
    channel='#dicechannel',
    token='supersecrettokenhere'
)
bot.start()