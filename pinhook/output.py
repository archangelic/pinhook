"""The output queue, which everything the bot sends waits in so it never floods.

Each target, a channel or a nick, has its own line of messages, sent in order.
Targets take turns, so one long reply doesn't hold up other channels, and the
transport's Limits decide how fast lines go out.
"""
import asyncio
from collections import deque
import time

from .transport.base import MessageTooLong


class OutputQueue:
    """Messages waiting to be sent, and the rate limit they're sent at.

    Args:
        send: the transport's send.
        limits: the transport's Limits.
        logger: the bot's logger.
        clock, sleep: what time it is and how to wait, so tests can fake them.
    """

    def __init__(self, send, limits, logger, clock=time.monotonic, sleep=asyncio.sleep):
        self.send = send
        self.limits = limits
        self.logger = logger
        self.clock = clock
        self.sleep = sleep
        # each target's waiting messages, in the order they take turns
        self.targets = {}
        # targets past their backlog, so the drop is logged once until they catch up
        self.dropping = set()
        self.tokens = float(limits.burst)
        self.refilled = None
        self.sending = False
        self.ready = asyncio.Event()

    def put(self, message):
        """Queue a message to send. Returns False if its target was full and it was dropped."""
        waiting = self.targets.setdefault(message.target, deque())
        if len(waiting) >= self.limits.backlog:
            if message.target not in self.dropping:
                self.dropping.add(message.target)
                self.logger.warning('{} lines are already waiting to go to {}, dropping new ones '
                                    'until they are sent'.format(self.limits.backlog,
                                                                 message.target))
            return False
        waiting.append(message)
        self.ready.set()
        return True

    def waiting(self):
        """How many messages are waiting to be sent."""
        return sum(len(w) for w in self.targets.values())

    def clear(self):
        """Forget every waiting message. Returns how many there were."""
        count = self.waiting()
        self.targets.clear()
        self.dropping.clear()
        return count

    async def run(self):
        """Send messages as they arrive, forever."""
        while True:
            await self.ready.wait()
            await self.send_next()

    async def flush(self):
        """Send everything waiting, at the rate limit, and return once it's sent."""
        while await self.send_next():
            pass

    async def drain(self):
        """Wait until everything waiting has been sent by run()."""
        while self.targets or self.sending:
            await asyncio.sleep(0.05)

    async def send_next(self):
        """Send the next message, once the rate limit allows. False if nothing is waiting."""
        if not self.targets:
            self.ready.clear()
            return False
        self.sending = True
        try:
            await self.wait_for_turn()
            if not self.targets:
                # cleared while waiting
                return False
            target = next(iter(self.targets))
            waiting = self.targets.pop(target)
            message = waiting.popleft()
            if waiting:
                # to the back, so the other targets get a turn first
                self.targets[target] = waiting
            else:
                self.dropping.discard(target)
            try:
                await self.send(message)
            except MessageTooLong:
                self.logger.error('output message too long: {}'.format(message.text))
            except Exception:
                self.logger.exception('could not send to {}'.format(message.target))
            return True
        finally:
            self.sending = False

    async def wait_for_turn(self):
        # a token bucket: burst tokens, one more every interval, one per line
        now = self.clock()
        if self.refilled is not None:
            earned = (now - self.refilled) / self.limits.interval
            self.tokens = min(float(self.limits.burst), self.tokens + earned)
        self.refilled = now
        if self.tokens < 1:
            await self.sleep((1 - self.tokens) * self.limits.interval)
            self.tokens = 1.0
            self.refilled = self.clock()
        self.tokens -= 1
