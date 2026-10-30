"""pinhook, a python irc bot framework.

    from pinhook import Plugin, command, on
"""
from .api import Plugin, command, on
from .context import Context

__all__ = ['Plugin', 'command', 'on', 'Context']
