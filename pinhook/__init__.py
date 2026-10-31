"""pinhook, a python irc bot framework.

    from pinhook import Plugin, command, on, every
"""
from .api import Plugin, command, every, on
from .context import Context

__all__ = ['Plugin', 'command', 'on', 'every', 'Context']
