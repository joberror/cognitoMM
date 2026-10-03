#!/usr/bin/env python3
"""
Test: tier-based download retention + "Get All" pack delivery.

Pins cluster 3:

1. Retention config/helpers (features/premium_management.py):
   - get_retention_minutes: free vs premium, single vs bulk, never < 1
   - retention_warn_minutes: lead time scaled down for short retention
2. Auto-delete tracking (features/file_deletion.py):
   - track_file_for_deletion stores duration/warn and a matching delete_at
   - the monitor uses the stored warn_minutes in the warning text
3. Pick-view pack (features/search.py + features/callbacks.py):
   - build_pick_view adds a "Get All" button for /search pick views (>1 copy)
     with a getpack: callback carrying season/resolution
   - the getpack: callback delivers the title's copies via the shared bulk
     helper (tracking each for auto-deletion + quota)

All DB/Telegram access runs against injected fakes - no live services.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import features.config as config
import features.callbacks as callbacks_module
import features.file_deletion as file_deletion
import features.premium_management as premium_management
from features.search import build_pick_view


def run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        loop = asyncio.new_event_loop()
    return loop.run_until_complete(coro)


class FakeClient:
    def __init__(self):
        self.messages = []
        self.cached = []
        self._ids = iter(range(1000, 2000))

    async def send_message(self, uid, text, **kwargs):
        self.messages.append({"uid": uid, "text": text})
        return SimpleNamespace(id=next(self._ids))

    async def get_messages(self, channel_id, message_id):
        return SimpleNamespace(
            video=SimpleNamespace(file_id=f"file{message_id}", file_size=100),
            document=None, caption="cap")

    async def send_cached_media(self, chat_id, file_id, caption=None, parse_mode=None):
        self.cached.append({"chat_id": chat_id, "file_id": file_id})
        return SimpleNamespace(id=next(self._ids))


class FakeCallbackMsg:
    def __init__(self):
        self.text = "original"
        self.reply_markup = None
        self.edits = []

    async def edit_text(self, text, **kwargs):
        self.edits.append(text)


class FakeCallbackQuery:
    def __init__(self, data, user_id=42):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id, first_name="Tester")
        self.message = FakeCallbackMsg()
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


# ------------------------------------------------------------------ #
# 1. Retention helpers                                                #
# ------------------------------------------------------------------ #

def test_get_retention_minutes_by_tier():
    saved = premium_management.is_premium_user
    try:
        premium_management.is_premium_user = AsyncMock(return_value=False)
        assert run(premium_management.get_retention_minutes(1)) == config.FILE_DELETION_MINUTES
        assert run(premium_management.get_retention_minutes(1, bulk=True)) == config.BULK_FILE_DELETION_MINUTES
        premium_management.is_premium_user = AsyncMock(return_value=True)
        assert run(premium_management.get_retention_minutes(1)) == config.PREMIUM_FILE_DELETION_MINUTES
        assert run(premium_management.get_retention_minutes(1, bulk=True)) == config.PREMIUM_BULK_FILE_DELETION_MINUTES
        # explicit premium avoids the lookup entirely
        premium_management.is_premium_user = AsyncMock(side_effect=AssertionError("no lookup"))
        assert run(premium_management.get_retention_minutes(1, premium=True)) == config.PREMIUM_FILE_DELETION_MINUTES
    finally:
        premium_management.is_premium_user = saved


def test_retention_warn_scaling():
    # Normal retention -> configured lead time (2)
    assert premium_management.retention_warn_minutes(30) == 2
    assert premium_management.retention_warn_minutes(5) == 2
    # Short retention -> at least 1, never more than half
    assert premium_management.retention_warn_minutes(1) == 1
    assert premium_management.retention_warn_minutes(0) == 1


# ------------------------------------------------------------------ #
# 2. track + warning                                                  #
# ------------------------------------------------------------------ #

def test_track_stores_duration_and_warn():
    file_deletion.file_deletions.clear()
    before = datetime.now(timezone.utc)
    fid = run(file_deletion.track_file_for_deletion(7, 99, duration_minutes=30))
    rec = file_deletion.file_deletions[fid]
    assert rec["duration_minutes"] == 30, rec
    assert rec["warn_minutes"] == 2, rec
    delta = (rec["delete_at"] - before).total_seconds()
    assert 29 * 60 <= delta <= 31 * 60, delta
    file_deletion.file_deletions.clear()


def test_monitor_uses_stored_warn_minutes():
    saved_client = config.client
    config.client = FakeClient()
    file_deletion.file_deletions.clear()
    # A record already inside the warning window but not yet due.
    file_deletion.file_deletions["x1"] = {
        "user_id": 5, "message_id": 10,
        "sent_at": datetime.now(timezone.utc) - timedelta(minutes=25),
        "delete_at": datetime.now(timezone.utc) + timedelta(minutes=1),
        "duration_minutes": 30, "warn_minutes": 7,
        "notified": False, "retry_count": 0,
    }
    try:
        run(file_deletion.check_files_for_deletion())
        texts = [m["text"] for m in config.client.messages]
        assert any("7-Minute Warning" in t for t in texts), texts
    finally:
        file_deletion.file_deletions.clear()
        config.client = saved_client


# ------------------------------------------------------------------ #
# 3. Pick-view pack                                                   #
# ------------------------------------------------------------------ #

def test_pick_view_has_get_all_button():
    copies = [
        {"_id": 1, "title": "Dune", "year": 2021, "quality": "1080p",
         "type": "Movie", "channel_id": -100, "message_id": 1},
        {"_id": 2, "title": "Dune", "year": 2021, "quality": "2160p",
         "type": "Movie", "channel_id": -100, "message_id": 2},
    ]
    text, kb = build_pick_view("sid123", 0, copies, prefix="choose")
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "getpack:sid123:0::" in datas, datas
    # /genres pick views (prefix != choose) do not offer the pack button
    _, kb2 = build_pick_view("sid123", 0, copies, prefix="genre_pick",
                             back_prefix="genre_back")
    datas2 = [b.callback_data for row in kb2.inline_keyboard for b in row]
    assert not any(d.startswith("getpack:") for d in datas2), datas2


def test_getpack_delivers_copies():
    client = FakeClient()
    q = FakeCallbackQuery("getpack:sid123:0::", user_id=42)
    config.bulk_downloads["sid123"] = {
        "user_id": 42,
        "groups": [[
            {"title": "Dune", "channel_id": -100, "message_id": 1},
            {"title": "Dune", "channel_id": -100, "message_id": 2},
        ]],
    }
    saved = (callbacks_module.should_process_command_for_user,
             callbacks_module.has_accepted_terms,
             callbacks_module.users_col,
             callbacks_module.movies_col,
             callbacks_module.track_file_for_deletion,
             premium_management.check_download_quota,
             premium_management.record_download,
             premium_management.get_retention_minutes)
    try:
        callbacks_module.should_process_command_for_user = AsyncMock(return_value=True)
        callbacks_module.has_accepted_terms = AsyncMock(return_value=True)
        callbacks_module.users_col = AsyncMock()
        callbacks_module.movies_col = AsyncMock()
        callbacks_module.movies_col.find_one = AsyncMock(return_value=None)
        track = AsyncMock()
        callbacks_module.track_file_for_deletion = track
        premium_management.check_download_quota = AsyncMock(return_value=(True, 10, 10, None))
        premium_management.record_download = AsyncMock(return_value=1)
        premium_management.get_retention_minutes = AsyncMock(return_value=15)

        run(callbacks_module.callback_handler(client, q))
    finally:
        (callbacks_module.should_process_command_for_user,
         callbacks_module.has_accepted_terms,
         callbacks_module.users_col,
         callbacks_module.movies_col,
         callbacks_module.track_file_for_deletion,
         premium_management.check_download_quota,
         premium_management.record_download,
         premium_management.get_retention_minutes) = saved
        config.bulk_downloads.pop("sid123", None)

    assert len(client.cached) == 2, client.cached
    assert track.call_count == 2, track.call_args_list
    for c in track.call_args_list:
        assert c.kwargs.get("duration_minutes") == 15, c.kwargs


_TESTS = [
    test_get_retention_minutes_by_tier,
    test_retention_warn_scaling,
    test_track_stores_duration_and_warn,
    test_monitor_uses_stored_warn_minutes,
    test_pick_view_has_get_all_button,
    test_getpack_delivers_copies,
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
