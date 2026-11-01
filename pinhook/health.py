"""The health endpoint, for container and service manager probes.

/healthz answers 200 while the process runs. /readyz answers 200 once the bot is
connected and in every channel it was told to join, and 503 with the reason before
then, and while it quits. Off unless health_port is set.
"""
import asyncio
import functools

REQUEST_TIMEOUT = 5
STATUS = {200: 'OK', 404: 'Not Found', 405: 'Method Not Allowed', 503: 'Service Unavailable'}


def readiness(bot):
    """Whether the bot is ready, and if not, why."""
    if bot.stopping:
        return False, 'quitting'
    if not bot.online:
        return False, 'not connected'
    fold = bot.transport.casefold
    joined = {fold(channel) for channel in bot.transport.joined()}
    missing = [channel.split()[0] for channel in bot.chanlist
               if fold(channel.split()[0]) not in joined]
    if missing:
        return False, 'not in ' + ', '.join(missing)
    return True, 'ready'


def respond(bot, method, path):
    """The status and body for a request."""
    if path not in ('/healthz', '/readyz'):
        return 404, 'not found'
    if method not in ('GET', 'HEAD'):
        return 405, 'GET only'
    if path == '/healthz':
        return 200, 'ok'
    ready, why = readiness(bot)
    return (200 if ready else 503), why


async def answer(bot, reader, writer):
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            request = (await reader.readline()).decode('latin-1').split()
            while (await reader.readline()) not in (b'\r\n', b'\n', b''):
                pass
        method, path = (request[0], request[1].split('?')[0]) if len(request) >= 2 else ('', '')
        status, body = respond(bot, method, path)
        data = (body + '\n').encode()
        head = ('HTTP/1.1 {} {}\r\nContent-Type: text/plain; charset=utf-8\r\n'
                'Content-Length: {}\r\nConnection: close\r\n\r\n'.format(
                    status, STATUS[status], len(data)))
        writer.write(head.encode() + (b'' if method == 'HEAD' else data))
        await writer.drain()
    except (TimeoutError, ConnectionError):
        pass
    finally:
        writer.close()


async def serve(bot, host, port):
    """Serve the health endpoint until cancelled. A port that can't be used is logged, and
    the bot runs on without it."""
    try:
        server = await asyncio.start_server(functools.partial(answer, bot), host, port)
    except OSError as e:
        bot.logger.error("the health endpoint can't listen on {}:{}: {}".format(host, port, e))
        return
    bot.logger.info('health endpoint on http://{}:{}/healthz and /readyz'.format(host, port))
    async with server:
        await server.serve_forever()
