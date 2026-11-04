import asyncio
import functools

from pinhook import health
from pinhook.testing import TestBot


def test_ready_once_connected_and_in_every_channel():
    bot = TestBot(channels=('#test', '#Games'))
    assert health.readiness(bot) == (True, 'ready')
    del bot.channels['#Games']
    assert health.readiness(bot) == (False, 'not in #Games')
    bot.online = False
    assert health.readiness(bot) == (False, 'not connected')
    bot.stopping = True
    assert health.readiness(bot) == (False, 'quitting')


def test_channels_match_whatever_their_case():
    bot = TestBot(channels=('#Games',))
    bot.channels['#games'] = bot.channels.pop('#Games')
    assert health.readiness(bot) == (True, 'ready')


def get(bot, request):
    async def go():
        server = await asyncio.start_server(functools.partial(health.answer, bot),
                                            '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            reader, writer = await asyncio.open_connection('127.0.0.1', port)
            writer.write(request.encode())
            response = await reader.read()
            writer.close()
            return response.decode()
    return asyncio.run(go())


def test_healthz_answers_while_the_process_runs():
    bot = TestBot()
    bot.online = False
    response = get(bot, 'GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n')
    assert response.startswith('HTTP/1.1 200 OK\r\n')
    assert response.endswith('\r\n\r\nok\n')


def test_readyz_says_why_not():
    bot = TestBot()
    assert get(bot, 'GET /readyz HTTP/1.1\r\n\r\n').endswith('\r\n\r\nready\n')
    bot.online = False
    response = get(bot, 'GET /readyz?verbose HTTP/1.1\r\n\r\n')
    assert response.startswith('HTTP/1.1 503 Service Unavailable\r\n')
    assert 'Content-Length: 14\r\n' in response
    assert response.endswith('not connected\n')


def test_other_paths_and_methods():
    bot = TestBot()
    assert get(bot, 'GET / HTTP/1.1\r\n\r\n').startswith('HTTP/1.1 404 ')
    assert get(bot, 'POST /readyz HTTP/1.1\r\n\r\n').startswith('HTTP/1.1 405 ')
    head = get(bot, 'HEAD /healthz HTTP/1.1\r\n\r\n')
    assert head.startswith('HTTP/1.1 200 OK\r\n') and head.endswith('\r\n\r\n')


def test_a_port_in_use_is_logged_and_the_bot_runs_on(caplog):
    async def go():
        taken = await asyncio.start_server(lambda r, w: None, '127.0.0.1', 0)
        port = taken.sockets[0].getsockname()[1]
        async with taken:
            await health.serve(TestBot(), '127.0.0.1', port)
        return port
    port = asyncio.run(go())
    assert "the health endpoint can't listen on 127.0.0.1:{}".format(port) in caplog.text
