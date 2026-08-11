"""
Shared pytest configuration.

Two guards run for the whole test session:

1. uvloop policy guard: pyroblack (this bot's Telegram library, installed as
   the `pyrogram` package) does NOT install the uvloop event-loop policy at
   import time, but older Pyrogram forks (e.g. hydrogram) did:
   hydrogram/__init__.py called asyncio.set_event_loop_policy(uvloop.EventLoopPolicy()).
   Under pytest-asyncio's per-test event loops such a policy intermittently
   raises ``RuntimeError: Event loop is closed`` (uvloop loops are not
   designed to be created/closed rapidly across tests). We intercept
   ``asyncio.set_event_loop_policy`` here and refuse uvloop policies: the
   standard asyncio policy stays active for the whole test session. uvloop is
   a runtime performance optimisation for the bot and is not needed by the
   tests, so the guard is kept as a safety net regardless.

2. pyroblack deprecation guard: pyroblack announces API deprecations
   ("This property is deprecated. Please use ... instead") via
   ``log.warning`` on its per-module loggers - NOT via Python warnings - so
   pytest's ``filterwarnings`` (see pyproject.toml) cannot see them. Logging
   *filters* only run on the logger that emits a record, but *handler*
   filters run on every record that propagates to an ancestor handler.
   Attaching a handler to the ``pyrogram`` root logger therefore catches
   deprecated-API log records from any pyrogram/pyroblack submodule, and the
   exception raised inside ``Handler.filter`` propagates back through the
   logging call into the test code, failing the test. This is what turns a
   future ``disable_web_page_preview``-style regression into a CI failure.

   Known limitation: the raised exception propagates through the logging
   call, so a broad ``except Exception`` in app code around a deprecated
   call would swallow it and the test would still pass. That is accepted for
   the common case; the bulletproof alternative (record matches and fail in
   ``pytest_sessionfinish``) is deliberately not used to keep this minimal.

This module is imported by pytest BEFORE any test module, so both guards are
installed before any test code imports pyrogram or runs.
"""

import asyncio
import logging

_original_set_event_loop_policy = asyncio.set_event_loop_policy


def _no_uvloop_policy(policy):
    """Refuse uvloop event-loop policies (safety net; uvloop is runtime-only)."""
    if policy.__class__.__module__.split(".")[0] == "uvloop":
        return
    _original_set_event_loop_policy(policy)


asyncio.set_event_loop_policy = _no_uvloop_policy
asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())


class _PyrogramDeprecationGuard(logging.Handler):
    """
    Fail any test that triggers a pyroblack deprecated-API log warning.

    Raised inside ``filter()`` (not ``emit()``): logging catches exceptions
    raised during ``emit`` and merely prints them, whereas an exception in
    ``Handler.handle`` -> ``filter`` propagates up through the logging call
    into the calling test code.
    """

    def __init__(self):
        super().__init__(level=logging.WARNING)

    def filter(self, record):
        message = record.getMessage()
        # Match the actual deprecation phrasing (every pyroblack deprecation
        # message reads "... is deprecated ...") rather than the bare word
        # "deprecated", so an unrelated future library log mentioning the
        # word cannot cause spurious failures.
        if "is deprecated" in message.lower():
            raise AssertionError(
                f"pyroblack deprecated API used during tests: "
                f"{record.name}: {message}"
            )
        return True

    def emit(self, record):
        pass  # matching records never reach emit (filter raises first)


def _install_pyrogram_deprecation_guard():
    pyrogram_logger = logging.getLogger("pyrogram")
    if not any(
        isinstance(h, _PyrogramDeprecationGuard) for h in pyrogram_logger.handlers
    ):
        pyrogram_logger.addHandler(_PyrogramDeprecationGuard())


_install_pyrogram_deprecation_guard()
