#!/usr/bin/env python3
"""
Test: /update_db access-error and FloodWait guards

Verifies features/commands.py cmd_update_db() protects the index against
channel access loss and rate limiting, mirroring the orphan prune safety
(see features/indexing.py.prune_orphaned_index_entries):

- Generic fetch errors still delete the orphaned DB entry (message deleted).
- Access errors (ChannelPrivate etc.) are SKIPPED - the entry is kept and
  the scan continues, so a single /update_db run cannot wipe a channel's
  entire index.
- FloodWait pauses the scan (paused=True) - nothing is deleted and the run
  reports itself as paused.

cmd_update_db is interactive (channel selection -> range -> CONFIRM), so we
inject fake DB collections, a fake client, canned user input and a no-op
log_action by monkeypatching the commands module namespace - the same
technique used by test_orphan_prune.py. No real DB or Telegram access is
needed.
"""

import asyncio
import sys
import os
from types import SimpleNamespace

# Ensure project root on path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from features import commands  # features/commands.py

# Real hydrogram error classes used to simulate channel access loss / flooding
from hydrogram.errors import ChannelPrivate, FloodWait

# ---------------------------
# Fakes
# ---------------------------

class FakeCursor:
    """Object with an async to_list(), returned by find()/aggregate()."""

    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return self._docs


class FakeChannelsCol:
    """One registered channel so the interactive selection succeeds."""

    def find(self, filter_query):
        return FakeCursor([
            {"channel_id": -100123, "channel_title": "Test Channel", "enabled": True}
        ])


class FakeMoviesCol:
    """Records which indexed entries were deleted by the scan."""

    def __init__(self, existing):
        self.existing = existing
        self.deleted_ids = []

    def find(self, filter_query, projection=None):
        return FakeCursor(self.existing)

    def aggregate(self, pipeline):
        return FakeCursor([])

    async def delete_one(self, filter_query):
        _id = filter_query.get("_id")
        if _id not in self.deleted_ids:
            self.deleted_ids.append(_id)
        return SimpleNamespace(deleted_count=1)


class FakeMsg:
    """A non-empty message without media (avoids the indexing branch)."""

    def __init__(self, empty=False):
        self.empty = empty


class FakeClient:
    """get_messages raises per message id, mimicking channel state."""

    def __init__(self, missing_ids=None, access_ids=None, flood_ids=None, empty_ids=None):
        self.missing_ids = set(missing_ids or [])
        self.access_ids = set(access_ids or [])
        self.flood_ids = set(flood_ids or [])
        self.empty_ids = set(empty_ids or [])

    async def get_messages(self, channel_id, msg_id):
        if msg_id in self.flood_ids:
            raise FloodWait(7)
        if msg_id in self.access_ids:
            raise ChannelPrivate("caused by " + str(msg_id))
        if msg_id in self.missing_ids:
            raise Exception("Message not found (deleted)")
        if msg_id in self.empty_ids:
            return FakeMsg(empty=True)
        return FakeMsg(empty=False)


class FakeSent:
    """Returned by reply_text(); records edit_text() calls (final status)."""

    def __init__(self):
        self.edits = []

    async def delete(self):
        pass

    async def edit_text(self, text, **kwargs):
        self.edits.append(text)


class FakeMessage:
    def __init__(self):
        self.from_user = SimpleNamespace(id=999)
        self.chat = SimpleNamespace(id=-100)
        self.sent = FakeSent()

    async def reply_text(self, text, **kwargs):
        return self.sent


class FakeUserInput:
    def __init__(self, text):
        self.text = text


async def _is_admin(uid):
    return True


def make_input_sequence(*texts):
    """wait_for_user_input returns the next canned response each call."""
    queue = list(texts)

    async def fake_wait(chat_id, uid, timeout=None):
        return FakeUserInput(queue.pop(0)) if queue else FakeUserInput("CANCEL")

    return fake_wait


def existing_docs(n):
    """Build n indexed entries (message_id 1..n) for the scanned range."""
    return [
        {"_id": f"doc_{i}", "message_id": i, "title": f"Title {i}"}
        for i in range(1, n + 1)
    ]


def run_update_db(client, input_texts, existing):
    """
    Patch the commands module namespace, run cmd_update_db end-to-end, and
    return (fake_message, fake_movies_col, log_records).
    """
    message = FakeMessage()

    commands.is_admin = _is_admin
    commands.wait_for_user_input = make_input_sequence(*input_texts)

    log_records = []

    async def _log_action(action, by=None, target=None, extra=None):
        log_records.append({"action": action, "extra": extra or {}})

    commands.log_action = _log_action
    commands.channels_col = FakeChannelsCol()
    movies = FakeMoviesCol(existing)
    commands.movies_col = movies

    asyncio.run(commands.cmd_update_db(client, message))
    return message, movies, log_records


# ---------------------------
# Test Cases
# ---------------------------

def test_access_error_guard():
    """
    Range 1-3 with all three messages indexed:
    - msg 1 raises a generic Exception -> orphan REMOVED (deleted message)
    - msg 2 raises ChannelPrivate (access lost) -> entry KEPT
    - msg 3 raises a generic Exception -> orphan REMOVED (proves the scan
      CONTINUES past the access error instead of aborting/breaking)
    """
    client = FakeClient(missing_ids={1, 3}, access_ids={2})
    msg, movies, logs = run_update_db(client, ["1", "1 3", "CONFIRM"], existing_docs(3))

    # Only generic-error orphans are deleted; the access-error entry survives
    assert sorted(movies.deleted_ids) == ["doc_1", "doc_3"], \
        f"expected only generic-error orphans deleted, got {movies.deleted_ids}"
    assert "doc_2" not in movies.deleted_ids, "access-error entry must be kept"

    # The run completed normally (not paused) with accurate counters
    assert logs and logs[-1]["action"] == "update_db"
    extra = logs[-1]["extra"]
    assert extra["paused"] is False
    assert extra["scanned"] == 3
    assert extra["orphans_removed"] == 2

    # Final status is NOT a pause message
    assert not any("Paused (FloodWait)" in e for e in msg.sent.edits), \
        "run without FloodWait must not report a pause"


def test_flood_wait_guard():
    """
    Range 1-4 with all messages indexed; msg 1 immediately raises FloodWait:
    - Nothing is deleted (rate limiting is not proof of deletion)
    - The scan pauses at the flood entry (scanned == 1)
    - The final status reports the pause
    """
    client = FakeClient(flood_ids={1})
    msg, movies, logs = run_update_db(client, ["1", "1 4", "CONFIRM"], existing_docs(4))

    assert movies.deleted_ids == [], "nothing must be deleted on FloodWait"
    assert logs and logs[-1]["action"] == "update_db"
    extra = logs[-1]["extra"]
    assert extra["paused"] is True, "run must be marked paused on FloodWait"
    assert extra["scanned"] == 1, "scan must stop at the flood entry"
    assert extra["orphans_removed"] == 0

    # The final status reports the pause
    assert any("Paused (FloodWait)" in e for e in msg.sent.edits), \
        "final status must report the FloodWait pause"


def test_empty_stub_removes_orphan():
    """
    The PRIMARY deletion path for /update_db: a deleted channel message comes
    back as an empty stub (get_messages -> empty=True) and its indexed entry
    is removed. Also confirms a non-indexed, non-media message is merely
    skipped and the scan completes normally.
    """
    client = FakeClient(empty_ids={1})
    msg, movies, logs = run_update_db(client, ["1", "1 2", "CONFIRM"], existing_docs(1))

    assert movies.deleted_ids == ["doc_1"], \
        f"empty stub must remove its orphan entry, got {movies.deleted_ids}"
    assert logs and logs[-1]["action"] == "update_db"
    extra = logs[-1]["extra"]
    assert extra["paused"] is False
    assert extra["scanned"] == 2
    assert extra["orphans_removed"] == 1
    assert extra["skipped_no_media"] == 1
    assert not any("Paused (FloodWait)" in e for e in msg.sent.edits)


def main():
    test_access_error_guard()
    test_flood_wait_guard()
    test_empty_stub_removes_orphan()
    print("✅ /update_db guard tests passed")
    print("   - access error: entry kept, scan continues, only generic orphans removed")
    print("   - flood wait: nothing deleted, paused=True, final status reports pause")
    print("   - empty stub: primary orphan-removal path works and scan completes")


if __name__ == "__main__":
    main()
