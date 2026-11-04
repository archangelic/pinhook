import pinhook.plugin


@pinhook.plugin.command('!karma', help_text='give someone karma')
def karma(msg):
    scores = msg.store.setdefault('scores', {})
    scores[msg.arg] = scores.get(msg.arg, 0) + 1
    label = msg.config.get('label', 'karma')
    return pinhook.plugin.message('{} has {} {}'.format(msg.arg, scores[msg.arg], label))
