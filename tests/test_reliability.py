#!/usr/bin/env python3
"""
Test: reliability helpers (FloodWait-aware retry + structured logging).

Pins cluster 7 (features/reliability.py):

- flood_wait_seconds / is_flood_wait extraction
- compute_delay exponential cap + add_jitter bounds
- retry_on_flood: retries FloodWait the reported duration, exhausts, passes
  through unrelated errors, retries `retry_on` types with backoff
- struct_log formatting (sorted keys, None skipped)
- scan_message_range wires flood_retries through (fetch survives a FloodWait)

No real Telegram or sleeping - sleep/rng are injected.
"""

import asyncio
import io
import os
import random
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from pyrogram.errors import FloodWait

from features.reliability import (
    add_jitter,
    compute_delay,
    flood_wait_seconds,
    is_flood_wait,
    jittered_sleep,
    retry_on_flood,
    struct_log,
)


def run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        loop = asyncio.new_event_loop()
    return loop.run_until_complete(coro)


class Recorder:
    def __init__(self):
        self.delays = []

    async def __call__(self, delay):
        self.delays.append(delay)


# ------------------------------------------------------------------ #
# Primitives                                                          #
# ------------------------------------------------------------------ #

def test_flood_wait_seconds_and_detection():
    assert flood_wait_seconds(FloodWait(7)) == 7.0
    assert flood_wait_seconds(SimpleNamespace(value=4)) == 4.0
    assert flood_wait_seconds(SimpleNamespace(x=3)) == 3.0
    assert flood_wait_seconds(ValueError("no"), default=9) == 9.0
    assert flood_wait_seconds(ValueError("no")) is None
    assert is_flood_wait(FloodWait(1)) is True
    assert is_flood_wait(ValueError("x")) is False

    class FloodWaitError(Exception):
        pass

    assert is_flood_wait(FloodWaitError()) is True


def test_compute_delay_and_jitter():
    assert compute_delay(1, 1.0, 60) == 1.0
    assert compute_delay(2, 1.0, 60) == 2.0
    assert compute_delay(3, 1.0, 60) == 4.0
    assert compute_delay(10, 1.0, 60) == 60.0  # capped
    rng = random.Random(0)
    d = add_jitter(10.0, 0.25, rng)
    assert 10.0 <= d <= 12.5, d
    assert add_jitter(10.0, 0.0, rng) == 10.0


def test_jittered_sleep_records():
    rec = Recorder()
    # jittered_sleep uses asyncio.sleep; just assert it returns a sane delay
    delay = run(jittered_sleep(0, jitter=0.25, rng=random.Random(0)))
    assert delay == 0.0


# ------------------------------------------------------------------ #
# retry_on_flood                                                      #
# ------------------------------------------------------------------ #

def test_retry_on_flood_recovers():
    rec = Recorder()
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        if calls["n"] < 3:
            raise FloodWait(5)
        return "ok"

    result = run(retry_on_flood(factory, max_retries=3, sleep=rec, rng=random.Random(0)))
    assert result == "ok" and calls["n"] == 3
    assert len(rec.delays) == 2, rec.delays
    # wait = max(5, base 1) capped at 60, plus <=25% jitter
    for d in rec.delays:
        assert 5.0 <= d <= 6.25, d


def test_retry_on_flood_exhausts():
    rec = Recorder()

    async def factory():
        raise FloodWait(2)

    raised = False
    try:
        run(retry_on_flood(factory, max_retries=2, sleep=rec, rng=random.Random(0)))
    except FloodWait:
        raised = True
    assert raised and len(rec.delays) == 2


def test_retry_passes_through_unrelated_error():
    rec = Recorder()

    async def factory():
        raise ValueError("nope")

    raised = False
    try:
        run(retry_on_flood(factory, max_retries=3, sleep=rec, rng=random.Random(0)))
    except ValueError:
        raised = True
    assert raised and rec.delays == []


def test_retry_on_transient_types():
    rec = Recorder()
    calls = {"n": 0}

    async def factory():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("net")
        return "ok"

    result = run(retry_on_flood(factory, max_retries=3, base_delay=1.0,
                                retry_on=(ConnectionError,), sleep=rec,
                                rng=random.Random(0)))
    assert result == "ok" and calls["n"] == 3
    # exponential: 1.0 then 2.0 (+jitter)
    assert 1.0 <= rec.delays[0] <= 1.25, rec.delays
    assert 2.0 <= rec.delays[1] <= 2.5, rec.delays


# ------------------------------------------------------------------ #
# struct_log                                                          #
# ------------------------------------------------------------------ #

def test_struct_log_format():
    buf = io.StringIO()
    with redirect_stdout(buf):
        line = struct_log("file_delivered", user_id=1, action="get_file", empty=None)
    assert line == "[EVENT] file_delivered action=get_file user_id=1", line
    assert buf.getvalue().strip() == line


# ------------------------------------------------------------------ #
# scan_message_range wiring                                           #
# ------------------------------------------------------------------ #

class FakeMoviesCol:
    def find(self, query, projection=None):
        class Cur:
            async def to_list(self, length=None):
                return []
        return Cur()

    async def delete_one(self, query):
        return None


class ScanClient:
    def __init__(self):
        self.calls = 0

    async def get_messages(self, channel_id, msg_id):
        self.calls += 1
        if self.calls == 1:
            raise FloodWait(2)
        return SimpleNamespace(empty=False, video=None, document=None)


def test_scan_uses_flood_retries():
    from features.database_scan import scan_message_range

    async def no_sleep(delay):
        return None

    client = ScanClient()
    result = run(scan_message_range(
        client, -100, 1, 1, movies_col_ref=FakeMoviesCol(),
        flood_retries=1, retry_sleep=no_sleep))
    assert client.calls == 2, client.calls  # FloodWait then success
    assert result["paused"] is False, result
    assert result["scanned"] == 1, result


_TESTS = [
    test_flood_wait_seconds_and_detection,
    test_compute_delay_and_jitter,
    test_jittered_sleep_records,
    test_retry_on_flood_recovers,
    test_retry_on_flood_exhausts,
    test_retry_passes_through_unrelated_error,
    test_retry_on_transient_types,
    test_struct_log_format,
    test_scan_uses_flood_retries,
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
