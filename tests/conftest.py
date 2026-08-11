"""
Shared pytest configuration.

pyroblack (this bot's Telegram library, installed as the `pyrogram` package)
does NOT install the uvloop event-loop policy at import time, but older
Pyrogram forks (e.g. hydrogram) did: hydrogram/__init__.py called
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy()). Under
pytest-asyncio's per-test event loops such a policy intermittently raises
``RuntimeError: Event loop is closed`` (uvloop loops are not designed to be
created/closed rapidly across tests).

This module is imported by pytest BEFORE any test module, so we intercept
``asyncio.set_event_loop_policy`` here and refuse uvloop policies: the
standard asyncio policy stays active for the whole test session. uvloop is a
runtime performance optimisation for the bot and is not needed by the tests,
so the guard is kept as a safety net regardless.
"""

import asyncio

_original_set_event_loop_policy = asyncio.set_event_loop_policy


def _no_uvloop_policy(policy):
    """Refuse uvloop event-loop policies (safety net; uvloop is runtime-only)."""
    if policy.__class__.__module__.split(".")[0] == "uvloop":
        return
    _original_set_event_loop_policy(policy)


asyncio.set_event_loop_policy = _no_uvloop_policy
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
