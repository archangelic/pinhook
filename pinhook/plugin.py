cmds = []

class Output:
    def __init__(self, msg_type, msg):
        self.msg_type = msg_type
        self.msg = msg


def action(msg):
    return Output('action', msg)


def message(msg):
    return Output('message', msg)


def add_plugin(command, func):
    cmds.append({'cmd': command, 'func': func})

