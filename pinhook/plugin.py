cmds = {}
lstnrs = {}


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


def _add_plugin(command, func):
    cmds[command] = func


def _add_listener(name, func):
    lstnrs[name] = func


def clear_plugins():
    cmds.clear()
    lstnrs.clear()


def register(command):
    def register_for_command(func):
        _add_plugin(command, func)
        return func
    return register_for_command


def listener(name):
    def register_as_listener(func):
        _add_listener(name, func)
        return func
    return register_as_listener
