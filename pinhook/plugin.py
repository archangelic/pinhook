cmds = []
lstnrs = []


class Output:
    def __init__(self, msg_type, msg):
        self.msg_type = msg_type
        self.msg = self.sanitize(msg)

    def sanitize(self, msg):
        try:
            return msg.splitlines()
        except AttributeError:
            return msg


def action(msg):
    return Output('action', msg)


def message(msg):
    return Output('message', msg)


def add_plugin(command, func):
    cmds.append({'cmd': command, 'func': func})


def clear_plugins():
    cmds.clear()
    lstnrs.clear()


def add_listener(name, func):
    lstnrs.append({'lstn': name, 'func': func})


def register(command):
    def register_for_command(func):
        add_plugin(command, func)
        return func
    return register_for_command


def listener(name):
    def register_as_listener(func):
        add_listener(name, func)
        return func
    return register_as_listener
