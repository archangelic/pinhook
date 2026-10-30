"""The output queue: its rate limit, targets taking turns, and the backlog cap."""
import asyncio
import logging

from pinhook.output import OutputQueue
from pinhook.transport.base import Limits, MessageTooLong, Outgoing


class Clock:
    # time only moves when the queue waits

    def __init__(self):
        self.now = 0.0
        self.pauses = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.pauses.append(seconds)
        self.now += seconds


def make_queue(limits=Limits(), too_long=None):
    sent = []
    clock = Clock()

    async def send(message):
        if message.text == too_long:
            raise MessageTooLong(message.text)
        sent.append(message.text)
    queue = OutputQueue(send, limits, logging.getLogger('test'), clock=clock, sleep=clock.sleep)
    return queue, sent, clock


def put(queue, target, *texts):
    return [queue.put(Outgoing('privmsg', target, text)) for text in texts]


def test_a_burst_goes_out_at_once_then_one_every_interval():
    queue, sent, clock = make_queue()
    put(queue, '#a', *'123456')
    asyncio.run(queue.flush())
    assert sent == list('123456')
    assert clock.pauses == [2, 2]


def test_the_burst_comes_back_over_time():
    queue, sent, clock = make_queue()
    put(queue, '#a', *'1234')
    asyncio.run(queue.flush())
    clock.now += 8
    put(queue, '#a', *'5678')
    asyncio.run(queue.flush())
    assert clock.pauses == []


def test_part_of_the_burst_comes_back():
    queue, sent, clock = make_queue()
    put(queue, '#a', *'1234')
    asyncio.run(queue.flush())
    # one and a half lines' worth
    clock.now += 3
    put(queue, '#a', *'567')
    asyncio.run(queue.flush())
    assert clock.pauses == [1, 2]


def test_targets_take_turns():
    queue, sent, clock = make_queue()
    put(queue, '#a', 'a1', 'a2', 'a3')
    put(queue, '#b', 'b1')
    asyncio.run(queue.flush())
    assert sent == ['a1', 'b1', 'a2', 'a3']


def test_a_full_target_drops_new_lines_and_says_so_once(caplog):
    queue, sent, clock = make_queue(Limits(backlog=3))
    assert put(queue, '#a', *'12345') == [True, True, True, False, False]
    # other targets still have room
    assert put(queue, '#b', 'b') == [True]
    assert caplog.text.count('3 lines are already waiting to go to #a') == 1
    asyncio.run(queue.flush())
    assert sent == ['1', 'b', '2', '3']


def test_a_target_that_caught_up_takes_lines_again(caplog):
    queue, sent, clock = make_queue(Limits(backlog=1))
    put(queue, '#a', '1', 'dropped')
    asyncio.run(queue.flush())
    assert put(queue, '#a', '2', 'dropped too') == [True, False]
    asyncio.run(queue.flush())
    assert sent == ['1', '2']
    assert caplog.text.count('dropping new ones') == 2


def test_clear_forgets_everything_waiting():
    queue, sent, clock = make_queue()
    put(queue, '#a', *'123')
    put(queue, '#b', '4')
    assert queue.clear() == 4
    asyncio.run(queue.flush())
    assert sent == []


def test_a_line_too_long_is_logged_and_the_rest_still_go(caplog):
    queue, sent, clock = make_queue(too_long='2')
    put(queue, '#a', *'123')
    asyncio.run(queue.flush())
    assert sent == ['1', '3']
    assert 'output message too long: 2' in caplog.text


def test_run_sends_messages_as_they_arrive():
    async def main():
        queue, sent, clock = make_queue()
        sender = asyncio.create_task(queue.run())
        put(queue, '#a', 'hi')
        await queue.drain()
        put(queue, '#a', 'again')
        await queue.drain()
        sender.cancel()
        return sent
    assert asyncio.run(main()) == ['hi', 'again']
