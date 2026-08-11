#!/usr/bin/env python3
"""
Test: scan_message_range() - the standalone /update_db scan loop

Verifies features/database_scan.py scan_message_range(), the message-range
reconciliation scan extracted from cmd_update_db so it can be unit-tested
without the interactive command flow (channel selection -> range -> CONFIRM):

- Generic fetch errors / empty stubs remove the orphaned DB entry.
- Access errors (ChannelPrivate etc.) are SKIPPED - entries are kept and the
  scan continues, so a single run cannot wipe a channel's whole index.
- FloodWait pauses the scan (paused=True); nothing is deleted.
- Media messages not yet indexed are indexed via the injected index_message.
- Existing media messages are counted as already-indexed.
- Non-media messages are skipped (any stale indexed entry removed).
- Indexing failures are counted as errors (duplicate key -> already-indexed).
- The optional progress_cb receives state snapshots.

The helper accepts movies_col_ref / index_message_ref / progress_cb as
parameters, so tests inject fakes directly - no monkeypatching needed.
"""

import asyncio
import sys
import os
from types import SimpleNamespace

# Ensure project root on path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from features.database_scan import scan_message_range

# Real pyrogram error classes used to simulate channel access loss / flooding
from pyrogram.errors import ChannelPrivate, FloodWait

# ---------------------------
# Fakes
# ---------------------------

class FakeCursor:
    """Object with an async to_list(), returned by find()."""

    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return self._docs


class FakeMoviesCol:
    """Records which indexed entries were deleted by the scan."""

    def __init__(self, existing):
        self.existing = existing
        self.deleted_ids = []

    def find(self, filter_query, projection=None):
        return FakeCursor(self.existing)

    async def delete_one(self, filter_query):
        _id = filter_query.get("_id")
        if _id not in self.deleted_ids:
            self.deleted_ids.append(_id)
        return SimpleNamespace(deleted_count=1)


class FakeMedia:
    def __init__(self, file_name="Movie.mkv", mime_type=""):
        self.file_name = file_name
        self.mime_type = mime_type


class FakeMsg:
    def __init__(self, empty=False, has_video=False, has_doc=False):
        self.empty = empty
        self.video = FakeMedia() if has_video else None
        self.document = FakeMedia(
            file_name="Doc.mkv", mime_type="video/mp4"
        ) if has_doc else None


class FakeClient:
    """get_messages returns/raises per message id, mimicking channel state."""

    def __init__(self, missing_ids=None, access_ids=None, flood_ids=None,
                 empty_ids=None, media_ids=None, doc_ids=None,
                 non_media_ids=None):
        self.missing_ids = set(missing_ids or [])
        self.access_ids = set(access_ids or [])
        self.flood_ids = set(flood_ids or [])
        self.empty_ids = set(empty_ids or [])
        self.media_ids = set(media_ids or [])
        self.doc_ids = set(doc_ids or [])
        self.non_media_ids = set(non_media_ids or [])

    async def get_messages(self, channel_id, msg_id):
        if msg_id in self.flood_ids:
            raise FloodWait(7)
        if msg_id in self.access_ids:
            raise ChannelPrivate("caused by " + str(msg_id))
        if msg_id in self.missing_ids:
            raise Exception("Message not found (deleted)")
        if msg_id in self.empty_ids:
            return FakeMsg(empty=True)
        if msg_id in self.media_ids:
            return FakeMsg(has_video=True)
        if msg_id in self.doc_ids:
            return FakeMsg(has_doc=True)
        if msg_id in self.non_media_ids:
            return FakeMsg()  # exists but has no media
        # Anything not explicitly configured behaves as a deleted stub
        return FakeMsg(empty=True)


def existing_docs(n):
    """Build n indexed entries (message_id 1..n) for the scanned range."""
    return [
        {"_id": f"doc_{i}", "message_id": i, "title": f"Title {i}"}
        for i in range(1, n + 1)
    ]


def run_scan(client, start, end, existing, index_message=None, progress_cb=None):
    """Run scan_message_range with fakes; return (movies_col, result dict)."""
    movies = FakeMoviesCol(existing)
    result = asyncio.run(scan_message_range(
        client,
        -100123,
        start,
        end,
        movies_col_ref=movies,
        index_message_ref=index_message,
        progress_cb=progress_cb,
    ))
    return movies, result


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
    movies, res = run_scan(client, 1, 3, existing_docs(3))

    assert sorted(movies.deleted_ids) == ["doc_1", "doc_3"], \
        f"expected only generic-error orphans deleted, got {movies.deleted_ids}"
    assert "doc_2" not in movies.deleted_ids, "access-error entry must be kept"

    assert res["scanned"] == 3
    assert res["orphans_removed"] == 2
    assert res["paused"] is False


def test_flood_wait_guard():
    """
    Range 1-4 with all messages indexed; msg 1 immediately raises FloodWait:
    - Nothing is deleted (rate limiting is not proof of deletion)
    - The scan pauses at the flood entry (scanned == 1)
    """
    client = FakeClient(flood_ids={1})
    movies, res = run_scan(client, 1, 4, existing_docs(4))

    assert movies.deleted_ids == [], "nothing must be deleted on FloodWait"
    assert res["paused"] is True, "run must be marked paused on FloodWait"
    assert res["scanned"] == 1, "scan must stop at the flood entry"
    assert res["orphans_removed"] == 0


def test_empty_stub_removes_orphan():
    """
    The PRIMARY deletion path: a deleted channel message comes back as an
    empty stub (get_messages -> empty=True) and its indexed entry is removed.
    Also confirms a non-indexed, non-media message is merely skipped.
    """
    client = FakeClient(empty_ids={1}, non_media_ids={2})
    movies, res = run_scan(client, 1, 2, existing_docs(1))

    assert movies.deleted_ids == ["doc_1"], \
        f"empty stub must remove its orphan entry, got {movies.deleted_ids}"
    assert res["scanned"] == 2
    assert res["orphans_removed"] == 1
    assert res["skipped_no_media"] == 1
    assert res["paused"] is False


def test_non_media_stale_entry_removed():
    """
    A message that still exists but no longer carries media: its stale indexed
    entry is removed (safety check), even though the message is not 'deleted'.
    """
    client = FakeClient(non_media_ids={1})
    movies, res = run_scan(client, 1, 2, existing_docs(1))

    assert movies.deleted_ids == ["doc_1"]
    assert res["orphans_removed"] == 1
    assert res["skipped_no_media"] == 1
    assert res["scanned"] == 2


def test_new_media_indexed():
    """A media message not in the DB is indexed via the injected index_message."""
    calls = []

    async def fake_index(msg):
        calls.append(msg.video.file_name)

    client = FakeClient(media_ids={1}, empty_ids={2})
    movies, res = run_scan(client, 1, 2, existing_docs(0), index_message=fake_index)

    assert calls == ["Movie.mkv"]
    assert res["new_indexed"] == 1
    assert res["scanned"] == 2
    assert movies.deleted_ids == []
    assert res["errors"] == 0


def test_document_with_video_mime_indexed():
    """A document with a video mime_type hits the has_doc index branch."""
    calls = []

    async def fake_index(msg):
        calls.append(msg.document.file_name)

    client = FakeClient(doc_ids={1}, empty_ids={2})
    movies, res = run_scan(client, 1, 2, existing_docs(0), index_message=fake_index)

    assert calls == ["Doc.mkv"]
    assert res["new_indexed"] == 1
    assert res["scanned"] == 2
    assert res["errors"] == 0
    assert movies.deleted_ids == []


def test_media_already_indexed_counts_as_duplicate():
    """Existing media message: index_message NOT called, counted as already."""
    calls = []

    async def fake_index(msg):
        calls.append(msg)

    client = FakeClient(media_ids={1})
    movies, res = run_scan(client, 1, 1, existing_docs(1), index_message=fake_index)

    assert calls == []
    assert res["already_indexed"] == 1
    assert res["new_indexed"] == 0
    assert movies.deleted_ids == []


def test_duplicate_key_error_counts_as_already_indexed():
    """Index race condition: duplicate-key error -> already_indexed, not error."""

    async def fake_index(msg):
        raise Exception("duplicate key error: E11000")

    client = FakeClient(media_ids={1})
    movies, res = run_scan(client, 1, 1, existing_docs(0), index_message=fake_index)

    assert res["already_indexed"] == 1
    assert res["errors"] == 0
    assert res["new_indexed"] == 0


def test_index_error_counts_as_error():
    """Any other indexing failure increments errors."""

    async def fake_index(msg):
        raise Exception("insert failed")

    client = FakeClient(media_ids={1})
    movies, res = run_scan(client, 1, 1, existing_docs(0), index_message=fake_index)

    assert res["errors"] == 1
    assert res["new_indexed"] == 0
    assert res["already_indexed"] == 0


def test_progress_callback_receives_state():
    """progress_cb fires (first message, since last_update starts at 0) with a full state dict."""
    snapshots = []

    async def cb(state):
        snapshots.append(state)

    client = FakeClient(empty_ids={1})
    movies, res = run_scan(client, 1, 2, existing_docs(1), progress_cb=cb)

    assert snapshots, "progress callback should fire at least once"
    s = snapshots[0]
    for key in ("scanned", "total_range", "progress_pct", "eta_str", "bar",
                "orphans_removed", "new_indexed", "already_indexed",
                "skipped_no_media", "errors"):
        assert key in s, f"progress state missing key {key}"
    assert s["total_range"] == 2
    assert s["scanned"] == 1


def main():
    test_access_error_guard()
    test_flood_wait_guard()
    test_empty_stub_removes_orphan()
    test_non_media_stale_entry_removed()
    test_new_media_indexed()
    test_document_with_video_mime_indexed()
    test_media_already_indexed_counts_as_duplicate()
    test_duplicate_key_error_counts_as_already_indexed()
    test_index_error_counts_as_error()
    test_progress_callback_receives_state()
    print("✅ scan_message_range (features/database_scan.py) tests passed")
    print("   - access error: entry kept, scan continues, only generic orphans removed")
    print("   - flood wait: nothing deleted, paused=True")
    print("   - empty stub / non-media: orphan removal paths work")
    print("   - new media indexed (video + document); already-indexed / duplicate-key / error counting")
    print("   - progress callback receives state snapshots")


if __name__ == "__main__":
    main()
