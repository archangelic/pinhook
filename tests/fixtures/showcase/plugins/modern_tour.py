"""Every 2.0 plugin feature, in one plugin."""
import asyncio
from collections import deque
from typing import Annotated, Literal, Optional

from pinhook import Context, Plugin, command, every, on


class Tour(Plugin):
    """A class plugin, whose state carries across !reload."""

    def setup(self, previous: 'Tour | None') -> None:
        self.reloads: int = previous.reloads + 1 if previous else 0
        # only the last few, for !events, so a busy channel never grows it
        self.events: deque[str] = previous.events if previous else deque(maxlen=5)

    def teardown(self) -> None:
        self.events.append('teardown')

    # typed commands

    @command('roll', help='roll dice, like roll 2 20', aliases=['r'])
    async def roll(self, ctx: Context, count: int = 1, sides: int = 6) -> None:
        await ctx.reply(f'{ctx.nick} rolled {count}d{sides}')

    @command('types')
    async def types(self, ctx: Context, word: str, number: int, ratio: float, loud: bool,
                    mode: Literal['a', 'b'] = 'a', extra: Optional[int] = None,
                    rest: Annotated[str, 'everything after'] = '') -> None:
        await ctx.reply(f'{word} {number} {ratio} {loud} {mode} {extra} {rest}')

    @command('reloads')
    async def show_reloads(self, ctx: Context) -> None:
        await ctx.reply(f'reloaded {self.reloads} times')

    # what a plugin keeps and reads

    @command('count')
    async def count(self, ctx: Context) -> None:
        ctx.store['count'] = ctx.store.get('count', 0) + 1
        await ctx.reply(f"counted {ctx.store['count']} with {ctx.config.get('word')}")

    @command('history')
    async def history(self, ctx: Context) -> None:
        await ctx.reply(' | '.join(f'{e.nick}:{e.text}' for e in ctx.history(3)) or 'none')

    # answering

    @command('thread')
    async def thread(self, ctx: Context) -> None:
        await ctx.reply('a threaded reply', thread=True)

    @command('private')
    async def private(self, ctx: Context) -> None:
        await ctx.reply('just for you', private=True)

    @command('say')
    async def say(self, ctx: Context) -> None:
        await ctx.action('waves')
        await ctx.notice('a notice for you')
        channel = ctx.config.shared['channel']
        await ctx.send(channel, [f'sent to {channel}', 'on two lines'])

    @command('slow')
    async def slow(self, ctx: Context) -> None:
        async with ctx.typing():
            await asyncio.sleep(0.01)
        await ctx.reply('done slowly')

    # who's there

    @command('who')
    async def who(self, ctx: Context) -> None:
        await ctx.reply(f'nick={ctx.nick} account={ctx.account} op={ctx.is_op} '
                        f'chanop={ctx.is_chanop} private={ctx.is_private} '
                        f'addressed={ctx.addressed} bot={ctx.bot.nick}')

    @command('members')
    async def members(self, ctx: Context) -> None:
        me = ctx.member(ctx.nick or '')
        await ctx.reply(f'{len(ctx.members())} here, me={me.nick if me else None}')

    @command('whois')
    async def whois(self, ctx: Context, nick: str) -> None:
        found = await ctx.whois(nick)
        await ctx.reply(f'{found.nick} account={found.account}' if found else 'nobody')

    @command('supports')
    async def supports(self, ctx: Context) -> None:
        await ctx.reply(' '.join(f'{f}={ctx.supports(f)}'
                                 for f in ('typing', 'reply', 'private', 'notice')))

    # access, failures and limits

    @command('secret', restricted=True, denied_msg='ask an op')
    async def secret(self, ctx: Context) -> None:
        await ctx.reply('the secret')

    @command('admin', ops=True)
    async def admin(self, ctx: Context) -> None:
        await ctx.reply('admin things')

    @command('broken', error_msg='that went wrong')
    async def broken(self, ctx: Context) -> None:
        raise RuntimeError('broken on purpose')

    @command('sleepy', timeout=0.05)
    async def sleepy(self, ctx: Context) -> None:
        # the timeout stops it first, so this is never said
        await asyncio.sleep(1)
        await ctx.reply('woke up')

    @command('hidden', hide=True)
    async def hidden(self, ctx: Context) -> None:
        await ctx.reply('found the hidden one')

    @command('events')
    async def show_events(self, ctx: Context) -> None:
        await ctx.reply(', '.join(self.events) or 'none')

    # events, recorded so !events shows them

    @on('join')
    async def joined(self, ctx: Context) -> None:
        self.events.append(f'join {ctx.nick}')
        # handlers never see the bot's own joins, so this never welcomes the bot
        await ctx.reply(f'welcome, {ctx.nick}')

    @on('part')
    async def parted(self, ctx: Context) -> None:
        self.events.append(f'part {ctx.nick}')

    @on('kick')
    async def kicked(self, ctx: Context) -> None:
        self.events.append(f'kick {ctx.kicked}')

    @on('quit')
    async def quit(self, ctx: Context) -> None:
        self.events.append(f'quit {ctx.nick}')

    @on('nick')
    async def renamed(self, ctx: Context) -> None:
        self.events.append(f'nick {ctx.nick}>{ctx.new_nick}')

    @on('topic')
    async def topic(self, ctx: Context) -> None:
        self.events.append(f'topic {ctx.text}')

    @on('invite')
    async def invited(self, ctx: Context) -> None:
        self.events.append(f'invite {ctx.invited}')

    @on('mode')
    async def mode(self, ctx: Context) -> None:
        self.events.append(f"mode {' '.join(ctx.modes)}")

    @on('netsplit')
    async def netsplit(self, ctx: Context) -> None:
        self.events.append(f'netsplit {len(ctx.nicks)}')

    @on('netjoin')
    async def netjoin(self, ctx: Context) -> None:
        self.events.append(f'netjoin {len(ctx.nicks)}')

    @on('notice')
    async def notice(self, ctx: Context) -> None:
        self.events.append(f'notice {ctx.text}')

    @on('message')
    async def message(self, ctx: Context) -> None:
        if ctx.addressed and ctx.text.endswith('hello'):
            await ctx.reply(f'hello {ctx.nick}, you addressed me')

    @on('connected')
    async def connected(self, ctx: Context) -> None:
        self.events.append('connected')

    @on('disconnected')
    async def disconnected(self, ctx: Context) -> None:
        self.events.append('disconnected')

    @every(minutes=30)
    async def remind(self, ctx: Context) -> None:
        await ctx.send(ctx.config.shared['channel'], 'the timer fired')
