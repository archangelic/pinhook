import random
import re

import pinhook.plugin

dicepattern = re.compile('(?P<amount>\d+)d(?P<sides>\d+)\+?(?P<modifier>\d+)?')

def build_output(rolls, modifier):
    if len(rolls) == 1:
        start = str(sum(rolls))
    else:
        all_rolls = ''.join([str(i)+', ' for i in rolls]).strip(', ')
        start = '{} = {}'.format(all_rolls, sum(rolls))
    if modifier:
        output = start + ' + {} = '.format(modifier)
    else:
        output = start
    return output

@pinhook.plugin.register('!roll')
def roll(msg):
    matches = dicepattern.match(msg.arg)
    if matches:
        msg.logger.info('Valid dice roll: {}'.format(msg.arg))
        rolls = [random.randrange(1, int(matches.group('sides'))+1) for i in range(int(matches.group('amount')))]
        output = build_output(rolls, matches.group('modifier'))
    else:
        output = '{}: improper format, should be NdN+N'.format(msg.nick)
    return pinhook.plugin.message(output)
