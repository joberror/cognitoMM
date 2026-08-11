#!/usr/bin/env python3
"""
Test: critical bug fixes

Covers three fixes:

1. should_process_command access control (features/user_management.py):
   - private chats always allowed (pyrogram ChatType enum, not string)
   - admins allowed anywhere
   - groups/supergroups/channels only when registered & enabled in channels_col
   - random groups are rejected (no unconditional group-command bypass)

2. resolve_chat_ref (features/commands.py): the broken local copy that used an
   undefined `client` was removed; commands now uses the utils.py version and
   passes the client explicitly (verified via /add_channel end-to-end).

3. cleanup_expired_bulk_downloads (features/utils.py): single implementation
   accepting an optional dict (defaults to the shared config.bulk_downloads);
   file_deletion.py re-exports it so both call styles work.
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from pyrogram.enums import ChatType

from features import user_management, utils, commands, file_deletion
from features.config import bulk_downloads


# ---------------------------
# Fakes
# ---------------------------

class FakeChannelsCol:
    """channels_col fake: only the given channel ids are registered+enabled."""

    def __init__(self, enabled_ids):
        self.enabled_ids = set(enabled_ids)

    async def find_one(self, query):
        cid = query.get("channel_id")
        if cid in self.enabled_ids:
            return {"channel_id": cid, "enabled": True}
        return None


def make_message(chat_type, chat_id, user_id, text="/start"):
    """Build a minimal pyrogram-style message object."""
    return SimpleNamespace(
        chat=SimpleNamespace(type=chat_type, id=chat_id),
        from_user=SimpleNamespace(id=user_id),
        text=text,
    )


def run_should_process(chat_type, chat_id, user_id, admin_ids=(), enabled_ids=()):
    """Run should_process_command with patched deps; return the bool result."""
    async def _is_admin(uid):
        return uid in admin_ids

    user_management.is_admin = _is_admin
    user_management.channels_col = FakeChannelsCol(enabled_ids)
    return asyncio.run(user_management.should_process_command(
        make_message(chat_type, chat_id, user_id)
    ))


# ---------------------------
# 1. should_process_command
# ---------------------------

def test_private_chat_always_allowed():
    assert run_should_process(ChatType.PRIVATE, 100, 1) is True


def test_admin_allowed_in_random_group():
    assert run_should_process(ChatType.GROUP, -100, 999, admin_ids={999}) is True


def test_random_group_rejected():
    """Non-admin in a non-monitored group must be rejected (no bypass)."""
    assert run_should_process(ChatType.GROUP, -100, 1) is False


def test_monitored_group_allowed():
    assert run_should_process(ChatType.SUPERGROUP, -100123, 1, enabled_ids={-100123}) is True


def test_monitored_channel_allowed():
    assert run_should_process(ChatType.CHANNEL, -100456, 1, enabled_ids={-100456}) is True


def test_non_monitored_channel_rejected():
    assert run_should_process(ChatType.CHANNEL, -100456, 1) is False


def test_disabled_channel_rejected():
    """A registered but disabled channel must not be a valid context."""
    async def _is_admin(uid):
        return False

    async def _find_one(query):
        return {"channel_id": query.get("channel_id"), "enabled": False}

    user_management.is_admin = _is_admin
    user_management.channels_col = SimpleNamespace(find_one=_find_one)
    result = asyncio.run(user_management.should_process_command(
        make_message(ChatType.CHANNEL, -100456, 1)
    ))
    assert result is False


# ---------------------------
# 2. resolve_chat_ref
# ---------------------------

def test_access_control_not_duplicated_in_utils():
    """utils.py must re-export the fixed user_management implementation, not a divergent copy."""
    assert utils.should_process_command is user_management.should_process_command
    assert utils.require_not_banned is user_management.require_not_banned
    assert utils.should_process_command_for_user is user_management.should_process_command_for_user


def test_commands_uses_utils_resolve_chat_ref():
    """The broken commands.py copy is gone; both names are the same function."""
    assert commands.resolve_chat_ref is utils.resolve_chat_ref


def test_resolve_chat_ref_numeric_and_username():
    class FakeClient:
        def __init__(self):
            self.calls = []

        async def get_chat(self, ref):
            self.calls.append(ref)
            return SimpleNamespace(id=-100123, title="Test Channel")

    client = FakeClient()

    asyncio.run(commands.resolve_chat_ref("-100123", client))
    asyncio.run(commands.resolve_chat_ref("t.me/somechannel", client))

    assert client.calls == [-100123, "somechannel"]


def test_add_channel_end_to_end():
    """cmd_add_channel resolves via the fixed resolve_chat_ref (no NameError)."""

    class FakeClient:
        async def get_chat(self, ref):
            return SimpleNamespace(id=-100123, title="Test Channel")

    class FakeChannels:
        def __init__(self):
            self.upserted = []

        async def update_one(self, query, update, upsert=False):
            self.upserted.append((query, update["$set"]))

    class FakeMessage:
        def __init__(self):
            self.from_user = SimpleNamespace(id=999)
            self.text = "/add_channel t.me/testchannel"
            self.replies = []

        async def reply_text(self, text, **kwargs):
            self.replies.append(text)

    channels = FakeChannels()
    logs = []

    async def _is_admin(uid):
        return True

    async def _log_action(action, by=None, target=None, extra=None):
        logs.append({"action": action, "target": target})

    commands.is_admin = _is_admin
    commands.channels_col = channels
    commands.log_action = _log_action

    msg = FakeMessage()
    asyncio.run(commands.cmd_add_channel(FakeClient(), msg))

    assert channels.upserted, "channel must have been upserted"
    assert channels.upserted[0][1]["channel_id"] == -100123
    assert logs and logs[0]["action"] == "add_channel"
    assert any("Channel added" in r for r in msg.replies), msg.replies


# ---------------------------
# 3. cleanup_expired_bulk_downloads
# ---------------------------

def test_cleanup_bulk_with_explicit_dict():
    now = datetime.now(timezone.utc)
    data = {
        "old": {"created_at": now - timedelta(hours=2)},
        "fresh": {"created_at": now - timedelta(minutes=5)},
    }
    asyncio.run(utils.cleanup_expired_bulk_downloads(data))
    assert "old" not in data
    assert "fresh" in data


def test_cleanup_bulk_without_arg_uses_shared_dict():
    saved = dict(bulk_downloads)
    try:
        bulk_downloads.clear()
        now = datetime.now(timezone.utc)
        bulk_downloads["old"] = {"created_at": now - timedelta(hours=3)}
        asyncio.run(utils.cleanup_expired_bulk_downloads())
        assert "old" not in bulk_downloads
    finally:
        bulk_downloads.clear()
        bulk_downloads.update(saved)


def test_file_deletion_reexports_same_function():
    """file_deletion.py re-exports the canonical implementation (search.py imports it from there)."""
    assert file_deletion.cleanup_expired_bulk_downloads is utils.cleanup_expired_bulk_downloads


def main():
    test_private_chat_always_allowed()
    test_admin_allowed_in_random_group()
    test_random_group_rejected()
    test_monitored_group_allowed()
    test_monitored_channel_allowed()
    test_non_monitored_channel_rejected()
    test_disabled_channel_rejected()
    test_access_control_not_duplicated_in_utils()
    test_commands_uses_utils_resolve_chat_ref()
    test_resolve_chat_ref_numeric_and_username()
    test_add_channel_end_to_end()
    test_cleanup_bulk_with_explicit_dict()
    test_cleanup_bulk_without_arg_uses_shared_dict()
    test_file_deletion_reexports_same_function()
    print("✅ critical fixes tests passed")
    print("   - access control: private/admins allowed, random groups/channels rejected")
    print("   - resolve_chat_ref: commands uses utils version, /add_channel works")
    print("   - cleanup_expired_bulk_downloads: both call styles work")


if __name__ == "__main__":
    main()
