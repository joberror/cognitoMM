#!/usr/bin/env python3
"""
Test: Orphaned Index Reconciliation

This test validates the new orphan pruning logic added in:
- features/indexing.py.prune_orphaned_index_entries()
It simulates indexed DB entries whose source channel messages were deleted or inaccessible,
and ensures they are removed from the movies collection.

We avoid real MongoDB usage by injecting a fake in-memory collection that mimics the async
interface (find / delete_one) used by prune_orphaned_index_entries.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

# Import the indexing module directly
import sys
import os

# Ensure project root on path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from features import indexing  # features/indexing.py
from features import config     # features/config.py

# ---------------------------
# Fake Async Mongo Collection
# ---------------------------

class FakeCursor:
    """
    Chainable cursor object supporting:
    - sort()
    - limit()
    - async iteration (__aiter__)
    """
    def __init__(self, docs):
        self._docs = docs
        self._sorted = False
        self._limit = None

    def sort(self, key, direction):
        # Only care about "indexed_at" desc (-1) for test fidelity
        if key == "indexed_at" and direction == -1:
            self._docs = sorted(self._docs, key=lambda d: d.get("indexed_at", datetime.min), reverse=True)
        self._sorted = True
        return self

    def limit(self, n):
        self._limit = n
        return self

    def __aiter__(self):
        # Apply limit late
        docs = self._docs if self._limit is None else self._docs[:self._limit]
        async def gen():
            for d in docs:
                yield d
        return gen()


class FakeMoviesCollection:
    """
    Minimal async collection implementing:
    - find()
    - delete_one()
    Records deletions for assertions.
    """
    def __init__(self, initial_docs):
        # Store docs by _id
        self.docs = {d["_id"]: d for d in initial_docs}
        self.deleted_ids = []

    def find(self, filter_query, projection):
        # Ignore filter_query & projection specifics for test; return all docs
        # Convert internal dict to list
        return FakeCursor(list(self.docs.values()))

    async def delete_one(self, filter_query):
        _id = filter_query.get("_id")
        if _id in self.docs:
            del self.docs[_id]
            self.deleted_ids.append(_id)
        # Simulate motor result object with deleted_count
        return SimpleNamespace(deleted_count=1 if _id in self.deleted_ids else 0)


# ---------------------------
# Fake Client with get_messages
# ---------------------------

class FakeMessage:
    def __init__(self, empty=False):
        self.empty = empty

class FakeClient:
    """
    get_messages behavior:
    - For message_id in self.missing_ids: raise Exception (simulates inaccessible/deleted)
    - For message_id in self.empty_ids: return FakeMessage(empty=True)
    - Otherwise return a non-empty message object
    """
    def __init__(self, missing_ids=None, empty_ids=None):
        self.missing_ids = set(missing_ids or [])
        self.empty_ids = set(empty_ids or [])

    async def get_messages(self, channel_id, message_id):
        if message_id in self.missing_ids:
            raise Exception("Message not found (deleted)")
        if message_id in self.empty_ids:
            return FakeMessage(empty=True)
        return FakeMessage(empty=False)


# ---------------------------
# Test Scenario Setup
# ---------------------------

async def run_test():
    """
    Scenario:
      We insert 5 fake indexed docs:
        1. Valid message -> should remain
        2. Missing message (raises) -> should be deleted
        3. Empty message object -> should be deleted
        4. Malformed (missing channel_id) -> should be deleted
        5. Malformed (missing message_id) -> should be deleted
    """
    now = datetime.now(timezone.utc)

    initial_docs = [
        {
            "_id": "chatA_100",
            "channel_id": -100111111,
            "message_id": 100,
            "title": "Valid Entry",
            "indexed_at": now
        },
        {
            "_id": "chatA_101",
            "channel_id": -100111111,
            "message_id": 101,
            "title": "Missing Source",
            "indexed_at": now
        },
        {
            "_id": "chatA_102",
            "channel_id": -100111111,
            "message_id": 102,
            "title": "Empty Source",
            "indexed_at": now
        },
        {
            "_id": "chatA_103",
            # Missing channel_id
            "message_id": 103,
            "title": "Malformed Missing Channel",
            "indexed_at": now
        },
        {
            "_id": "chatA_104",
            "channel_id": -100111111,
            # Missing message_id
            "title": "Malformed Missing Message",
            "indexed_at": now
        }
    ]

    # Inject fake movies collection
    fake_collection = FakeMoviesCollection(initial_docs)
    indexing.movies_col = fake_collection  # Monkey patch in module namespace

    # Configure fake client
    fake_client = FakeClient(
        missing_ids={101},     # simulate deleted message
        empty_ids={102}        # simulate empty message object
    )
    config.client = fake_client  # Provide to prune function via config

    # Run prune (limit larger than doc set)
    await indexing.prune_orphaned_index_entries(limit=50)

    # Assertions
    remaining_ids = set(fake_collection.docs.keys())
    deleted_ids = set(fake_collection.deleted_ids)

    # Expect valid entry remains
    assert "chatA_100" in remaining_ids, "Valid entry should remain"
    # Expect orphaned or malformed removed
    for orphan in ["chatA_101", "chatA_102", "chatA_103", "chatA_104"]:
        assert orphan in deleted_ids, f"Orphan/malformed entry {orphan} should be deleted"

    print("✅ Orphan prune test passed")
    print(f"Remaining IDs: {remaining_ids}")
    print(f"Deleted IDs: {deleted_ids}")


def main():
    asyncio.run(run_test())


if __name__ == "__main__":
    main()