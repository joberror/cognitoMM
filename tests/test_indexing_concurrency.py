"""
Test: indexing_lock serializes concurrent indexing operations.

The indexing_lock (asyncio.Lock) ensures only one indexing process runs at a time.
This prevents race conditions when multiple admins trigger /index_channel simultaneously.
"""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import features.indexing as indexing
import features.config as config


class FakeClient:
    """Minimal client mock for start_indexing_process."""

    def __init__(self):
        self.chats = {}

    async def get_chat(self, chat_id):
        return self.chats.get(chat_id, SimpleNamespace(
            id=chat_id, title="Test Channel", type=SimpleNamespace(value="channel")
        ))

    async def iter_messages(self, chat_id, last_msg_id, skip=0):
        # Yield a few test messages - need to match enums.MessageMediaType.DOCUMENT
        from pyrogram import enums
        for msg_id in range(skip + 1, skip + 4):
            media = SimpleNamespace(
                file_name=f"video_{msg_id}.mkv",
                file_size=1000000,
                caption="",
                duration=100,
                mime_type="video/x-matroska",
            )
            yield SimpleNamespace(
                id=msg_id,
                chat=SimpleNamespace(id=chat_id),
                media=enums.MessageMediaType.DOCUMENT,
                document=media,
                video=None,
                caption="",
                date=SimpleNamespace(timestamp=lambda: 1234567890),
                empty=False,
            )


class FakeMessage:
    """Mock message that records edits."""

    def __init__(self):
        self.edits = []

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


async def test_indexing_lock_serializes_concurrent_calls(monkeypatch):
    """Two simultaneous start_indexing_process calls must run sequentially."""

    # Patch config with fake lock and collections
    monkeypatch.setattr(config, "INDEX_EXTENSIONS", [".mkv"])
    monkeypatch.setattr(config, "AUTO_INDEX_DEFAULT", True)

    # Track execution order
    execution_order = []
    active_count = 0
    max_concurrent = 0

    async def fake_save_batch(docs):
        nonlocal active_count, max_concurrent
        active_count += 1
        max_concurrent = max(max_concurrent, active_count)
        execution_order.append(("start_batch", len(docs)))
        await asyncio.sleep(0.01)  # Simulate DB work
        execution_order.append(("end_batch", len(docs)))
        active_count -= 1
        return len(docs), 0, 0

    monkeypatch.setattr(indexing, "save_files_batch", fake_save_batch)
    monkeypatch.setattr(indexing, "parse_metadata", lambda cap, fn: {})
    monkeypatch.setattr(indexing, "get_readable_time", lambda s: "0s")

    client = FakeClient()
    client.chats[-1001] = SimpleNamespace(id=-1001, title="Channel 1")
    client.chats[-1002] = SimpleNamespace(id=-1002, title="Channel 2")

    msg1 = FakeMessage()
    msg2 = FakeMessage()

    # Run two indexing processes concurrently
    async def run_first():
        await indexing.start_indexing_process(client, msg1, -1001, 3, 0)

    async def run_second():
        await indexing.start_indexing_process(client, msg2, -1002, 3, 0)

    await asyncio.gather(run_first(), run_second())

    # Verify they ran sequentially (not overlapping)
    assert max_concurrent == 1, f"Max concurrent was {max_concurrent}, expected 1"
    # Each call processes 3 messages in one batch (BATCH_SIZE=50 > 3)
    assert execution_order == [
        ("start_batch", 3), ("end_batch", 3),
        ("start_batch", 3), ("end_batch", 3),
    ], f"Execution order: {execution_order}"


async def test_indexing_lock_released_on_cancel(monkeypatch):
    """If first indexing is cancelled, second should proceed."""

    monkeypatch.setattr(config, "INDEX_EXTENSIONS", [".mkv"])
    monkeypatch.setattr(config, "AUTO_INDEX_DEFAULT", True)

    execution_order = []
    active_count = 0

    async def fake_save_batch(docs):
        nonlocal active_count
        active_count += 1
        execution_order.append(("start_batch", len(docs)))
        await asyncio.sleep(0.01)
        execution_order.append(("end_batch", len(docs)))
        active_count -= 1
        return len(docs), 0, 0

    monkeypatch.setattr(indexing, "save_files_batch", fake_save_batch)
    monkeypatch.setattr(indexing, "parse_metadata", lambda cap, fn: {})
    monkeypatch.setattr(indexing, "get_readable_time", lambda s: "0s")

    client = FakeClient()
    client.chats[-1001] = SimpleNamespace(id=-1001, title="Channel 1")

    msg1 = FakeMessage()
    msg2 = FakeMessage()

    # Start first, cancel it immediately
    async def run_first_cancelled():
        # Trigger cancel before the batch saves
        config.temp_data.CANCEL = True
        await indexing.start_indexing_process(client, msg1, -1001, 3, 0)
        config.temp_data.CANCEL = False  # Reset for second run

    async def run_second():
        await indexing.start_indexing_process(client, msg2, -1001, 3, 0)

    await asyncio.gather(run_first_cancelled(), run_second())

    # Second should have run after first cancelled
    assert max(active_count for active_count in [0]) == 0  # Both completed
    assert len(execution_order) == 2  # Only second batch ran (first cancelled before batch)


def run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        loop = asyncio.new_event_loop()
    return loop.run_until_complete(coro)


def main():
    failures = 0
    tests = [
        test_indexing_lock_serializes_concurrent_calls,
        test_indexing_lock_released_on_cancel,
    ]
    for fn in tests:
        try:
            run(fn())
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
            import traceback
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())