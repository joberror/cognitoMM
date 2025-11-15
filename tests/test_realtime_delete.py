"""
Test: Real-time deletion handler removes indexed DB entries immediately.

We simulate a RawUpdate deletion-like update received from Hydrogram and ensure:
- Documents with (channel_id, message_id) matching update.message_ids are deleted.
- Non-listed message IDs remain.
- Handler is resilient and logs via log_action without raising.

No actual Hydrogram dependency; we fabricate the update object and lightweight collection stubs.
"""

import asyncio
from types import SimpleNamespace
import pytest

# Import the module under test
import features.deletion_events as deletion_events


class FakeMoviesCollection:
    def __init__(self, docs):
        # Store by composite key _id or dedicate keys
        self.docs = {d["_id"]: d for d in docs}
        self.deleted_ids = []

    async def delete_one(self, filter_query):
        # Match by channel_id + message_id
        channel_id = filter_query.get("channel_id")
        message_id = filter_query.get("message_id")
        # Find matching doc
        target_id = None
        for _id, d in list(self.docs.items()):
            if d.get("channel_id") == channel_id and d.get("message_id") == message_id:
                target_id = _id
                break
        if target_id:
            del self.docs[target_id]
            self.deleted_ids.append(target_id)
            return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


class FakeChannelsCollection:
    def __init__(self, enabled_ids):
        self.enabled_ids = enabled_ids

    async def find_one(self, query):
        cid = query.get("channel_id")
        if cid in self.enabled_ids:
            return {"channel_id": cid, "enabled": True, "channel_title": f"Channel {cid}"}
        return None


# Stub log_action to avoid external dependencies
async def stub_log_action(action, **kwargs):
    # Collect actions for assertion if needed (optional extension)
    pass


@pytest.mark.asyncio
async def test_handle_raw_update_deletes_indexed_entries():
    channel_id = 777777
    # Prepare initial documents (some will be deleted, one should remain)
    initial_docs = [
        {"_id": f"{channel_id}_10", "channel_id": channel_id, "message_id": 10, "title": "Movie A"},
        {"_id": f"{channel_id}_11", "channel_id": channel_id, "message_id": 11, "title": "Movie B"},
        {"_id": f"{channel_id}_12", "channel_id": channel_id, "message_id": 12, "title": "Movie C"},
        {"_id": f"{channel_id}_13", "channel_id": channel_id, "message_id": 13, "title": "Movie D (should remain)"},
    ]

    fake_movies = FakeMoviesCollection(initial_docs)
    fake_channels = FakeChannelsCollection({channel_id})

    # Patch module globals
    deletion_events.movies_col = fake_movies
    deletion_events.channels_col = fake_channels
    deletion_events.log_action = stub_log_action

    # Fabricate a deletion-like raw update object
    class FakeDeletionUpdate:
        def __init__(self, channel_id, message_ids):
            self.channel_id = channel_id
            self.message_ids = message_ids

    update = FakeDeletionUpdate(channel_id, [10, 11, 12])  # message 13 should remain

    # Invoke handler
    await deletion_events.handle_raw_update(None, update, None, None)

    # Assertions
    # Deleted docs
    assert f"{channel_id}_10" in fake_movies.deleted_ids, "Message 10 should be deleted"
    assert f"{channel_id}_11" in fake_movies.deleted_ids, "Message 11 should be deleted"
    assert f"{channel_id}_12" in fake_movies.deleted_ids, "Message 12 should be deleted"

    # Remaining doc
    assert f"{channel_id}_13" not in fake_movies.deleted_ids, "Message 13 should not be deleted"
    assert f"{channel_id}_13" in fake_movies.docs, "Message 13 document should remain in collection"

    # Ensure no accidental deletion counts beyond expected
    assert len(fake_movies.deleted_ids) == 3, "Exactly three documents should be deleted"


@pytest.mark.asyncio
async def test_handle_raw_update_ignores_non_registered_channel():
    # Channel not enabled/registered
    channel_id = 888888
    initial_docs = [
        {"_id": f"{channel_id}_5", "channel_id": channel_id, "message_id": 5, "title": "Unregistered Movie"},
    ]
    fake_movies = FakeMoviesCollection(initial_docs)
    fake_channels = FakeChannelsCollection(set())  # empty set means no enabled channels

    deletion_events.movies_col = fake_movies
    deletion_events.channels_col = fake_channels
    deletion_events.log_action = stub_log_action

    class FakeDeletionUpdate:
        def __init__(self, channel_id, message_ids):
            self.channel_id = channel_id
            self.message_ids = message_ids

    update = FakeDeletionUpdate(channel_id, [5])

    await deletion_events.handle_raw_update(None, update, None, None)

    # Should ignore deletion: channel not registered
    assert f"{channel_id}_5" not in fake_movies.deleted_ids, "Unregistered channel deletion should be ignored"
    assert f"{channel_id}_5" in fake_movies.docs, "Document should remain"


@pytest.mark.asyncio
async def test_handle_raw_update_no_message_ids_no_action():
    # Valid channel but empty message_ids -> no deletion
    channel_id = 999999
    initial_docs = [
        {"_id": f"{channel_id}_1", "channel_id": channel_id, "message_id": 1, "title": "Movie X"},
    ]
    fake_movies = FakeMoviesCollection(initial_docs)
    fake_channels = FakeChannelsCollection({channel_id})

    deletion_events.movies_col = fake_movies
    deletion_events.channels_col = fake_channels
    deletion_events.log_action = stub_log_action

    class FakeOtherUpdate:
        def __init__(self, channel_id):
            self.channel_id = channel_id
            # No message_ids attribute -> should be ignored

    update = FakeOtherUpdate(channel_id)

    await deletion_events.handle_raw_update(None, update, None, None)

    assert not fake_movies.deleted_ids, "No deletions should occur without message_ids"
    assert f"{channel_id}_1" in fake_movies.docs, "Document should remain untouched"


@pytest.mark.asyncio
async def test_handle_raw_update_handles_exceptions_gracefully():
    # Force an exception inside delete_one to ensure handler catches it
    channel_id = 123123
    initial_docs = [
        {"_id": f"{channel_id}_2", "channel_id": channel_id, "message_id": 2, "title": "Movie Err"},
    ]

    class FaultyMoviesCollection(FakeMoviesCollection):
        async def delete_one(self, filter_query):
            raise RuntimeError("Simulated deletion failure")

    fake_movies = FaultyMoviesCollection(initial_docs)
    fake_channels = FakeChannelsCollection({channel_id})

    deletion_events.movies_col = fake_movies
    deletion_events.channels_col = fake_channels
    deletion_events.log_action = stub_log_action

    class FakeDeletionUpdate:
        def __init__(self, channel_id, message_ids):
            self.channel_id = channel_id
            self.message_ids = message_ids

    update = FakeDeletionUpdate(channel_id, [2])

    # Should not raise despite internal error
    await deletion_events.handle_raw_update(None, update, None, None)

    # Document remains (since deletion failed)
    assert f"{channel_id}_2" in fake_movies.docs, "Document should remain after simulated failure"


if __name__ == "__main__":
    # Allow running this test file directly for quick manual validation
    asyncio.run(test_handle_raw_update_deletes_indexed_entries())
    asyncio.run(test_handle_raw_update_ignores_non_registered_channel())
    asyncio.run(test_handle_raw_update_no_message_ids_no_action())
    asyncio.run(test_handle_raw_update_handles_exceptions_gracefully())
    print("Manual test run complete.")