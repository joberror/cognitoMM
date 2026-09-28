#!/usr/bin/env python3
"""
Test: /queue ops command (features/commands.py).

Pins the cluster-6 ops-visibility command:

1. Renders queue depth vs the deque cap, with a near-capacity warning.
2. Renders processor liveness by reading config.queue_processor_task (via
   the module - indexing.py rebinds the global, so the command must NOT
   from-import it).
3. Surfaces prune_stats + auto-indexing + per-channel rescan cursors.
4. Admin-gated.

All DB/Telegram access runs against injected fakes - no live services.
"""

import asyncio
import os
import sys
from collections import deque
from types import SimpleNamespace

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import features.commands as commands
import features.config as config


class FakeMessage:
    def __init__(self, user_id=1, text="/queue"):
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(id=user_id)
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))
        return SimpleNamespace(id=1)


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    async def to_list(self, length=None):
        return self._docs[:length] if length else list(self._docs)


class FakeSettingsCol:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    async def find_one(self, query, **kwargs):
        for d in self.docs:
            if d.get("k") == query.get("k"):
                return dict(d)
        return None

    def find(self, query):
        import re
        pat = (query.get("k") or {}).get("$regex")
        if pat:
            rx = re.compile(pat)
            return FakeCursor([d for d in self.docs if rx.search(str(d.get("k")))])
        return FakeCursor(self.docs)


class FakeChannelsCol:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, query):
        return FakeCursor(self.docs)


class RunningTask:
    def done(self):
        return False

    def cancelled(self):
        return False


class StoppedTask:
    def done(self):
        return True

    def cancelled(self):
        return False

    def exception(self):
        return RuntimeError("boom")


def _install(settings=None, channels=None, task=None, admin=True):
    """Swap command-module collaborators for fakes; returns restore fn."""
    saved = (commands.settings_col, commands.channels_col, commands.is_admin,
             commands.log_action, config.queue_processor_task)
    commands.settings_col = settings or FakeSettingsCol()
    commands.channels_col = channels or FakeChannelsCol()
    config.queue_processor_task = task

    async def _admin(uid):
        return admin

    async def _log(*a, **k):
        return None

    commands.is_admin = _admin
    commands.log_action = _log
    return saved


def _restore(saved):
    (commands.settings_col, commands.channels_col, commands.is_admin,
     commands.log_action, config.queue_processor_task) = saved


def run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        loop = asyncio.new_event_loop()
    return loop.run_until_complete(coro)


def test_queue_reports_running_processor_and_cursors():
    settings = FakeSettingsCol([
        {"k": "auto_indexing", "v": True},
        {"k": "scan_cursor:-100123", "v": 4321},
    ])
    channels = FakeChannelsCol([{"channel_id": -100123, "channel_title": "Cinema"}])
    saved = _install(settings=settings, channels=channels, task=RunningTask())
    msg = FakeMessage()
    try:
        run(commands.cmd_queue(None, msg))
    finally:
        _restore(saved)
    text = msg.replies[0][0]
    assert "QUEUE & BACKGROUND OPS" in text, text
    assert "Processor: running" in text, text
    assert "Auto-indexing: ON" in text, text
    assert "Cinema: msg 4321" in text, text
    assert "Orphan prune:" in text, text


def test_queue_warns_near_capacity():
    settings = FakeSettingsCol([{"k": "auto_indexing", "v": False}])
    saved = _install(settings=settings, task=RunningTask())
    msg = FakeMessage()
    # Fill the real queue to 80% (cap is 100).
    saved_queue = commands.message_queue
    try:
        commands.message_queue = deque(range(80), maxlen=100)
        run(commands.cmd_queue(None, msg))
    finally:
        commands.message_queue = saved_queue
        _restore(saved)
    text = msg.replies[0][0]
    assert "80/100 pending" in text, text
    assert "NEAR CAPACITY" in text, text
    assert "Auto-indexing: OFF" in text, text


def test_queue_reports_stopped_processor():
    saved = _install(task=StoppedTask())
    msg = FakeMessage()
    try:
        run(commands.cmd_queue(None, msg))
    finally:
        _restore(saved)
    text = msg.replies[0][0]
    assert "Processor: STOPPED" in text, text
    assert "boom" in text, text


def test_queue_not_started_processor():
    saved = _install(task=None)
    msg = FakeMessage()
    try:
        run(commands.cmd_queue(None, msg))
    finally:
        _restore(saved)
    text = msg.replies[0][0]
    assert "not started" in text, text


def test_queue_admin_gated():
    saved = _install(admin=False)
    msg = FakeMessage(user_id=999)
    try:
        run(commands.cmd_queue(None, msg))
    finally:
        _restore(saved)
    assert msg.replies[0][0] == "🚫 Admins only.", msg.replies


_TESTS = [
    test_queue_reports_running_processor_and_cursors,
    test_queue_warns_near_capacity,
    test_queue_reports_stopped_processor,
    test_queue_not_started_processor,
    test_queue_admin_gated,
]


def main() -> int:
    failures = 0
    for fn in _TESTS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
            import traceback
            traceback.print_exc()
    print(f"\n{len(_TESTS) - failures}/{len(_TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
