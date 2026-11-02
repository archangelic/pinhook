"""Check that pinhook's type hints catch mistakes in a plugin, as the docs promise.

Runs mypy on a plugin that uses the API correctly, which has to pass, and on one
with the mistakes the docs name, like ctx.reply(42) and ctx.acount, which have to
be caught.

    python tools/check_plugin_types.py
"""
import sys
import tempfile
import textwrap
from pathlib import Path

from mypy import api

GOOD = '''
from pinhook import Context, Plugin, command, every, on


class Dice(Plugin):
    def setup(self, previous: 'Dice | None') -> None:
        self.rolls: int = previous.rolls if previous else 0

    @command('roll', help='roll a die', aliases=['r'])
    async def roll(self, ctx: Context, sides: int = 6) -> None:
        self.rolls += 1
        ctx.store['rolls'] = self.rolls
        await ctx.reply(f'{ctx.nick} rolled {sides}', thread=True)
        await ctx.action('rolls a die')
        await ctx.notice(ctx.nick or '', 'good luck')
        member = ctx.member('ana')
        if member is not None and member.is_chanop:
            await ctx.send('#log', ['ana', 'is an op'])


@on('join')
async def welcome(ctx: Context) -> None:
    for entry in ctx.history(5):
        ctx.logger.info(entry.text)


@every(minutes=30)
async def remind(ctx: Context) -> None:
    await ctx.send('#games', 'game night is friday')
'''

BAD = '''
from pinhook import Context, command


@command('roll')
async def roll(ctx: Context) -> None:
    await ctx.reply(42)
    print(ctx.acount)
'''

# what mypy has to say about BAD
CAUGHT = ['Argument 1 to "reply" of "Context" has incompatible type "int"',
          '"Context" has no attribute "acount"']


def check(source):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'plugin.py'
        path.write_text(textwrap.dedent(source))
        # pinhook's own modules are read for their types, and only the plugin is reported,
        # as for a plugin author with pinhook installed
        out, err, status = api.run(['--no-incremental', '--strict', '--follow-imports=silent',
                                    str(path)])
    return out + err, status


def main():
    out, status = check(GOOD)
    if status != 0:
        print('a correct plugin fails type checking:\n' + out)
        return 1
    out, status = check(BAD)
    missed = [message for message in CAUGHT if message not in out]
    if status == 0 or missed:
        print('type checking misses mistakes in a plugin: {}\n{}'.format(missed, out))
        return 1
    print('type hints catch the mistakes and pass a correct plugin')
    return 0


if __name__ == '__main__':
    sys.exit(main())
