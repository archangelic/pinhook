from conftest import event


PING_PLUGIN = (
    "import pinhook.plugin as p\n"
    "@p.command('!ping')\n"
    "def ping(msg): return p.message('pong')\n"
)


def test_private_message_gets_reply(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('ping', PING_PLUGIN))
    b.process_event(conn, event('mal', 'pinbot', '!ping', type='privmsg'))
    conn.privmsg.assert_called_once_with('mal', 'pong')


def test_private_message_after_nick_change(make_bot, plugin_dir, conn):
    # e.g. services forced a nick change while connected
    b = make_bot(plugin_dir('ping', PING_PLUGIN))
    b.process_event(conn, event('mal', 'pinbot_', '!ping', type='privmsg'))
    conn.privmsg.assert_called_once_with('mal', 'pong')


def test_banned_user_cannot_use_plugins(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('ping', PING_PLUGIN), banned_users=['troll'])
    b.process_event(conn, event('troll', '#test', '!ping'))
    conn.privmsg.assert_not_called()


def test_banned_user_cannot_use_internal_commands(make_bot, conn):
    b = make_bot(banned_users=['troll'])
    b.process_event(conn, event('troll', '#test', '!banlist'))
    conn.privmsg.assert_not_called()


def test_ban_command_blocks_user(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('ping', PING_PLUGIN), ops=['mal'])
    b.process_event(conn, event('mal', '#test', '!ban troll'))
    conn.reset_mock()
    b.process_event(conn, event('troll', '#test', '!ping'))
    conn.privmsg.assert_not_called()


def test_unbanned_user_can_use_plugins(make_bot, plugin_dir, conn):
    b = make_bot(plugin_dir('ping', PING_PLUGIN), ops=['mal'], banned_users=['troll'])
    b.process_event(conn, event('mal', '#test', '!unban troll'))
    conn.reset_mock()
    b.process_event(conn, event('troll', '#test', '!ping'))
    conn.privmsg.assert_called_once_with('#test', 'pong')
