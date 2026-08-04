#!/usr/bin/env python3
"""
Test: prune_stats tracking in prune_orphaned_index_entries

Verifies the runtime statistics dict (features/statistics_store.py.prune_stats)
is populated correctly by prune_orphaned_index_entries():

- Success path: runs / last_run / last_duration / last_verified /
  last_deleted / last_skipped_access / total_deleted / total_skipped_access
  are recorded, and cumulative totals accumulate across runs.
- FloodWait path: last_paused is True and the scan stops at the flood entry.
- Error path: last_error is recorded and incomplete runs are NOT counted.
- Client-not-ready path: no run is recorded at all.

Uses the same fake in-memory collection / client technique as test_orphan_prune.py
so no real MongoDB or Telegram access is needed.
"""

import asyncio
import sys
import os
from datetime import datetime, timezone
from types import SimpleNamespace

# Ensure project root on path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from features import indexing  # features/indexing.py
from features import config     # features/config.py

# Real hydrogram error classes used to simulate channel access loss / flooding
from hydrogram.errors import ChannelPrivate, FloodWait

# ---------------------------
# Fake Async Mongo Collection
# ---------------------------

class FakeCursor:
    """Chainable cursor: sort() -> limit() -> async iteration."""

    def __init__(self, docs):
        self._docs = docs
        self._limit = None

    def sort(self, key, direction):
        # Only care about "indexed_at" desc (-1) for test fidelity
        if key == "indexed_at" and direction == -1:
            self._docs = sorted(self._docs, key=lambda d: d.get("indexed_at", datetime.min), reverse=True)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def __aiter__(self):
        docs = self._docs if self._limit is None else self._docs[:self._limit]

        async def gen():
            for d in docs:
                yield d

        return gen()


class FakeMoviesCollection:
    """Minimal async collection implementing find() and delete_one()."""

    def __init__(self, initial_docs):
        self.docs = {d["_id"]: d for d in initial_docs}
        self.deleted_ids = []

    def find(self, filter_query, projection):
        return FakeCursor(list(self.docs.values()))

    async def delete_one(self, filter_query):
        _id = filter_query.get("_id")
        if _id in self.docs:
            del self.docs[_id]
            self.deleted_ids.append(_id)
        return SimpleNamespace(deleted_count=1 if _id in self.deleted_ids else 0)


class FailingCollection:
    """find() raises - simulates a database error before any message fetch."""

    def find(self, filter_query, projection):
        raise RuntimeError("simulated db failure")

    async def delete_one(self, filter_query):
        return SimpleNamespace(deleted_count=0)


# ---------------------------
# Fake Client with get_messages
# ---------------------------

class FakeMessage:
    def __init__(self, empty=False):
        self.empty = empty


class FakeClient:
    """
    get_messages behavior:
    - flood_ids -> raise FloodWait (rate limited) -> PAUSE
    - access_errors -> raise the mapped access error -> SKIP
    - missing_ids -> raise generic Exception (deleted)
    - empty_ids -> return FakeMessage(empty=True)
    - otherwise return a non-empty message object
    """

    def __init__(self, missing_ids=None, empty_ids=None, access_errors=None, flood_ids=None):
        self.missing_ids = set(missing_ids or [])
        self.empty_ids = set(empty_ids or [])
        self.access_errors = access_errors or {}  # message_id -> exception class
        self.flood_ids = set(flood_ids or [])

    async def get_messages(self, channel_id, message_id):
        if message_id in self.flood_ids:
            raise FloodWait(5)
        if message_id in self.access_errors:
            raise self.access_errors[message_id]()
        if message_id in self.missing_ids:
            raise Exception("Message not found (deleted)")
        if message_id in self.empty_ids:
            return FakeMessage(empty=True)
        return FakeMessage(empty=False)


# ---------------------------
# Helpers
# ---------------------------

def reset_prune_stats():
    """Reset prune_stats to defaults so scenarios are independent."""
    indexing.prune_stats.update({
        "runs": 0,
        "total_deleted": 0,
        "total_skipped_access": 0,
        "last_run": None,
        "last_duration": 0,
        "last_verified": 0,
        "last_deleted": 0,
        "last_skipped_access": 0,
        "last_paused": False,
        "last_error": None,
    })


def make_docs(now, prefix, n):
    """Build n well-formed indexed docs sharing the same indexed_at timestamp."""
    return [
        {
            "_id": f"{prefix}_{i}",
            "channel_id": -100111111,
            "message_id": i,
            "title": f"Doc {i}",
            "indexed_at": now,
        }
        for i in range(1, n + 1)
    ]


# ---------------------------
# Scenarios
# ---------------------------

async def run_success_path_stats():
    """Mixed outcomes: deleted, skipped, malformed - all recorded in stats."""
    reset_prune_stats()
    now = datetime.now(timezone.utc)

    docs = make_docs(now, "a", 4) + [
        {"_id": "a_5", "message_id": 5, "title": "Malformed", "indexed_at": now},  # missing channel_id
    ]
    indexing.movies_col = FakeMoviesCollection(docs)
    config.client = FakeClient(
        missing_ids={2},             # message_id 2 -> generic exception -> deleted
        empty_ids={4},               # message_id 4 -> empty stub -> deleted
        access_errors={3: ChannelPrivate},  # message_id 3 -> access lost -> skipped
    )

    deleted = await indexing.prune_orphaned_index_entries(limit=10)

    # a_1 valid remains; a_2 (missing), a_4 (empty), a_5 (malformed) deleted; a_3 skipped
    assert deleted == 3, f"expected 3 deletions, got {deleted}"
    s = indexing.prune_stats
    assert s["runs"] == 1
    assert s["last_verified"] == 5
    assert s["last_deleted"] == 3
    assert s["last_skipped_access"] == 1
    assert s["last_paused"] is False
    assert s["last_error"] is None
    assert s["last_run"] is not None, "last_run should be set after a run"
    assert isinstance(s["last_duration"], (int, float)) and s["last_duration"] >= 0
    assert s["total_deleted"] == 3
    assert s["total_skipped_access"] == 1

    # Cumulative counters: run again on a fresh identical dataset
    indexing.movies_col = FakeMoviesCollection(docs)
    config.client = FakeClient(missing_ids={2}, empty_ids={4}, access_errors={3: ChannelPrivate})
    await indexing.prune_orphaned_index_entries(limit=10)

    assert indexing.prune_stats["runs"] == 2
    assert indexing.prune_stats["total_deleted"] == 6
    assert indexing.prune_stats["total_skipped_access"] == 2


async def run_flood_pause_stats():
    """FloodWait pauses the run: last_paused=True, scan stops at flood entry."""
    reset_prune_stats()
    now = datetime.now(timezone.utc)

    docs = make_docs(now, "b", 3)
    indexing.movies_col = FakeMoviesCollection(docs)
    config.client = FakeClient(flood_ids={2})  # message_id 2 -> FloodWait

    deleted = await indexing.prune_orphaned_index_entries(limit=10)

    s = indexing.prune_stats
    assert deleted == 0
    assert s["last_paused"] is True, "run should be marked as paused on FloodWait"
    assert s["last_verified"] == 2, "scan should stop at the flood entry"
    assert s["last_deleted"] == 0
    assert s["last_run"] is not None
    assert s["runs"] == 1
    # Entries after the flood entry must be untouched
    assert "b_3" in indexing.movies_col.docs, "entry after FloodWait must remain"


async def run_error_path_stats():
    """DB error mid-run: last_error recorded, runs NOT incremented."""
    reset_prune_stats()
    indexing.movies_col = FailingCollection()
    config.client = FakeClient()  # client present, but find() fails first

    deleted = await indexing.prune_orphaned_index_entries(limit=10)

    s = indexing.prune_stats
    assert deleted == 0
    assert s["last_error"] is not None
    assert "simulated" in s["last_error"]
    assert s["last_run"] is not None, "last_run should be set even on failure"
    assert s["runs"] == 0, "incomplete runs must not be counted"


async def run_no_client_no_stats():
    """Client not ready: prune is skipped and NO run is recorded."""
    reset_prune_stats()
    indexing.movies_col = FakeMoviesCollection([])
    config.client = None

    deleted = await indexing.prune_orphaned_index_entries(limit=10)

    assert deleted == 0
    assert indexing.prune_stats["runs"] == 0
    assert indexing.prune_stats["last_run"] is None
    assert indexing.prune_stats["last_error"] is None


async def run_all():
    await run_success_path_stats()
    await run_flood_pause_stats()
    await run_error_path_stats()
    await run_no_client_no_stats()
    print("✅ prune_stats tracking tests passed")
    print("   - success: runs / last_* / totals recorded, cumulative counters")
    print("   - flood: last_paused=True, scan stopped at the flood entry")
    print("   - error: last_error recorded, runs not incremented")
    print("   - no client: no run recorded at all")


def main():
    asyncio.run(run_all())


if __name__ == "__main__":
    main()
