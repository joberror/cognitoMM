"""
Tests for the new feature set:

- Quality dedup: quality_rank / pick_best_quality / group_duplicate_copies
  (utils.py) - best-quality copy wins in search; duplicates get a chooser.
- TMDb enrichment: cache round-trip + miss, format_enrichment_line
  (tmdb_integration.py).
- Watchlist: add/remove/get/notify with fake collections (user_management.py).
- Scheduled rescan: scan-cursor persistence + incremental_rescan window
  (database_scan.py).
- /logs rendering and the new command routing (commands.py).
"""

import asyncio
import os
import sys
from types import SimpleNamespace

# Ensure project root is on the path so the features package is importable
# when this file is run standalone (python tests/test_new_features.py).
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from pyrogram.enums import ChatType

import features.commands as commands
import features.database_scan as dbs
import features.user_management as um
from features.tmdb_integration import format_enrichment_line, get_cached_enrichment, set_cached_enrichment
from features.utils import group_duplicate_copies, pick_best_quality, quality_rank


# ------------------------------------------------------------------ #
#  Quality dedup                                                     #
# ------------------------------------------------------------------ #


def test_quality_rank_ordering():
    assert quality_rank("1080p") > quality_rank("720p") > quality_rank("480p")
    assert quality_rank("4K UHD") == quality_rank("2160p")
    assert quality_rank("1080p HEVC") == quality_rank("1080p")
    assert quality_rank(None) == 0
    assert quality_rank("") == 0


def test_pick_best_quality_returns_highest_copy():
    e720 = {"title": "T", "quality": "720p"}
    e1080 = {"title": "T", "quality": "1080p"}
    e4k = {"title": "T", "quality": "4K"}

    best, others = pick_best_quality([e720, e1080])
    assert best is e1080
    assert others == [e720]

    best, others = pick_best_quality([e4k, e720, e1080])
    assert best is e4k
    assert others == [e720, e1080]


def test_group_duplicate_copies_groups_by_title_year_type():
    entries = [
        {"title": "Avatar", "year": 2009, "type": "Movie"},
        {"title": "avatar", "year": 2009, "type": "Movie"},
        {"title": "Avatar", "year": 2009, "type": "Series"},
        {"title": "Other", "year": 2000, "type": "Movie"},
    ]
    groups = group_duplicate_copies(entries)

    assert len(groups) == 3
    assert len(groups[0]) == 2  # the two Movie copies


# ------------------------------------------------------------------ #
#  TMDb enrichment                                                   #
# ------------------------------------------------------------------ #


def test_enrichment_cache_roundtrip_and_miss():
    assert get_cached_enrichment("Interstellar Enrich", 2014, "Movie") is None
    set_cached_enrichment("Interstellar Enrich", 2014, "Movie", {"rating": 8.7})
    assert get_cached_enrichment("Interstellar Enrich", 2014, "Movie") == {"rating": 8.7}
    # Case/whitespace normalized key
    assert get_cached_enrichment("  interstellar enrich ", 2014, "movie") == {"rating": 8.7}


def test_format_enrichment_line():
    assert format_enrichment_line(None) == ""
    line = format_enrichment_line({
        "rating": 8.1, "genres": ["Action", "Drama"], "imdb_id": "tt0499549",
    })
    assert "⭐ 8.1" in line
    assert "Action" in line
    assert "imdb.com/title/tt0499549" in line
    # No rating -> no star segment
    assert "⭐" not in format_enrichment_line({"genres": ["Drama"]})


# ------------------------------------------------------------------ #
#  Watchlist                                                         #
# ------------------------------------------------------------------ #


class FakeUsersCollection:
    """Emulates the users_col operations used by the watchlist helpers."""

    def __init__(self):
        self.docs = []

    def _user(self, uid):
        for d in self.docs:
            if d["user_id"] == uid:
                return d
        doc = {"user_id": uid, "watchlist": []}
        self.docs.append(doc)
        return doc

    async def update_one(self, filt, update, upsert=False):
        uid = filt["user_id"]
        doc = self._user(uid)
        if update.get("$push"):
            entry = update["$push"]["watchlist"]
            if any(e.get("title_key") == entry["title_key"] for e in doc["watchlist"]):
                return SimpleNamespace(modified_count=0)
            doc["watchlist"].append(entry)
            return SimpleNamespace(modified_count=1)
        if update.get("$pull"):
            before = len(doc["watchlist"])
            key = update["$pull"]["watchlist"]["title_key"]
            doc["watchlist"] = [e for e in doc["watchlist"] if e.get("title_key") != key]
            return SimpleNamespace(modified_count=1 if len(doc["watchlist"]) < before else 0)
        return SimpleNamespace(modified_count=0)

    async def find_one(self, filt, projection=None):
        return next((d for d in self.docs if d["user_id"] == filt["user_id"]), None)

    def find(self, filt, **kwargs):
        # Motor's find() is SYNC and returns a cursor whose to_list() is async
        key = filt.get("watchlist.title_key")
        matches = [d for d in self.docs if any(e.get("title_key") == key for e in d.get("watchlist", []))]

        class _Cursor:
            async def to_list(self, length=None):
                return matches

        return _Cursor()


async def test_watchlist_add_remove_get(monkeypatch):
    monkeypatch.setattr(um, "users_col", FakeUsersCollection())

    assert await um.add_to_watchlist(1, "Avatar") is True
    assert await um.add_to_watchlist(1, "Avatar") is False  # idempotent

    wl = await um.get_watchlist(1)
    assert len(wl) == 1 and wl[0]["title"] == "Avatar" and wl[0]["title_key"] == "avatar"

    assert await um.remove_from_watchlist(1, "AVATAR") is True  # key-normalized
    assert await um.get_watchlist(1) == []
    assert await um.remove_from_watchlist(1, "Avatar") is False  # already gone


async def test_notify_watchlist_dms_matching_users(monkeypatch):
    class FakeClient:
        def __init__(self):
            self.messages = []

        async def send_message(self, chat_id, text, reply_markup=None):
            self.messages.append((chat_id, text))

    monkeypatch.setattr(um, "users_col", FakeUsersCollection())
    # Seed two users watching "avatar" (helpers now use the patched collection)
    await um.add_to_watchlist(1, "Avatar")
    await um.add_to_watchlist(2, "avatar")
    await um.add_to_watchlist(3, "Other Title")

    import features.config as cfg
    client = FakeClient()
    monkeypatch.setattr(cfg, "client", client)

    notified = await um.notify_watchlist({
        "title": "Avatar", "channel_id": -100, "message_id": 7,
    })

    assert notified == 2
    assert len(client.messages) == 2
    assert all("Avatar" in text for _, text in client.messages)


# ------------------------------------------------------------------ #
#  Scheduled rescan (database_scan)                                  #
# ------------------------------------------------------------------ #


async def test_scan_cursor_roundtrip(monkeypatch):
    store = {}

    class FakeSettings:
        async def find_one(self, filt):
            return {"v": store[filt["k"]]} if filt["k"] in store else None

        async def update_one(self, filt, update, upsert=False):
            store[filt["k"]] = update["$set"]["v"]

    fs = FakeSettings()
    assert await dbs.get_channel_scan_cursor(-100, fs) is None
    await dbs.set_channel_scan_cursor(-100, 500, fs)
    assert await dbs.get_channel_scan_cursor(-100, fs) == 500


async def test_incremental_rescan_window_and_cursor(monkeypatch):
    store = {}

    class FakeSettings:
        async def find_one(self, filt):
            return {"v": store[filt["k"]]} if filt["k"] in store else None

        async def update_one(self, filt, update, upsert=False):
            store[filt["k"]] = update["$set"]["v"]

    class FakeClient:
        async def get_chat_history(self, chat_id, limit=1):
            return [SimpleNamespace(id=1000)]

    scan_calls = []

    async def fake_scan(client, channel_id, start_id, end_id, **kwargs):
        scan_calls.append((channel_id, start_id, end_id))
        return {"scanned": end_id - start_id + 1, "new_indexed": 1, "orphans_removed": 0,
                "already_indexed": 0, "skipped_no_media": 0, "errors": 0, "paused": False}

    fs = FakeSettings()
    ch = {"channel_id": -100, "channel_title": "Movies"}

    # First run: no baseline -> bounded recent window (last 1000 msgs)
    result = await dbs.incremental_rescan(FakeClient(), ch, settings_col_ref=fs, scan_ref=fake_scan)
    assert scan_calls == [(-100, 1, 1000)]
    assert store["scan_cursor:-100"] == 1000
    assert result["scanned"] == 1000

    # Second run: cursor at latest -> up-to-date, no scan
    result2 = await dbs.incremental_rescan(FakeClient(), ch, settings_col_ref=fs, scan_ref=fake_scan)
    assert result2 == {"channel_id": -100, "scanned": 0, "status": "up-to-date"}
    assert scan_calls == [(-100, 1, 1000)]


# ------------------------------------------------------------------ #
#  /logs rendering + command routing                                 #
# ------------------------------------------------------------------ #


class FakeMessage:
    def __init__(self, text, user_id=42):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(type=ChatType.PRIVATE, id=1000)
        self.replies = []

    async def reply_text(self, *args, **kwargs):
        self.replies.append((args, kwargs))


async def test_cmd_logs_renders_recent_entries(monkeypatch):
    msg = FakeMessage("/logs")

    async def _is_admin(uid):
        return True

    monkeypatch.setattr(commands, "is_admin", _is_admin)

    class FakeLogs:
        def __init__(self):
            self.docs = [
                {"action": "indexed_message", "by": 1, "target": 2,
                 "extra": {"title": "Avatar"}, "ts": __import__("datetime").datetime(2026, 8, 13, 12, 0)},
                {"action": "ban_user", "by": 1, "target": 9, "extra": {}, "ts": None},
            ]

        def find(self, *a, **k):
            return self

        def sort(self, *a, **k):
            return self

        def limit(self, n):
            return self

        async def to_list(self, length=None):
            return self.docs

    monkeypatch.setattr(commands, "logs_col", FakeLogs())
    await commands.cmd_logs(None, msg)

    text = msg.replies[0][0][0]
    assert "Recent Logs" in text
    assert "indexed_message" in text and "ban_user" in text
    assert "Avatar" in text


async def test_cmd_enrich_status_renders_counts(monkeypatch):
    msg = FakeMessage("/enrich_status")

    async def _is_admin(uid):
        return True

    monkeypatch.setattr(commands, "is_admin", _is_admin)

    class FakeMovies:
        def __init__(self):
            self.counts = [1000, 300, 50]  # total, pending, no_match

        async def count_documents(self, filt):
            return self.counts.pop(0)

    monkeypatch.setattr(commands, "movies_col", FakeMovies())
    await commands.cmd_enrich_status(None, msg)

    text = msg.replies[0][0][0]
    assert "TMDb Enrichment Status" in text
    assert "Total indexed: <b>1000</b>" in text
    assert "Enriched: <b>650</b>" in text  # 1000 - 300 - 50
    assert "Pending: <b>300</b>" in text
    assert "No TMDb match: <b>50</b>" in text
    assert "65.0%" in text


async def test_new_commands_are_routed(monkeypatch):
    calls = []

    async def recorder(name):
        async def _fn(client, message):
            calls.append(name)
        return _fn

    for name in ("cmd_random", "cmd_genres", "cmd_watch", "cmd_unwatch",
                 "cmd_watchlist", "cmd_logs", "cmd_enrich", "cmd_enrich_status"):
        monkeypatch.setattr(commands, name, await recorder(name))

    async def _yes(m):
        return True

    async def _no(m):
        return False

    monkeypatch.setattr(commands, "should_process_command", _yes)
    monkeypatch.setattr(commands, "check_banned", _no)
    monkeypatch.setattr(commands, "check_terms_acceptance", _yes)

    for cmd in ("/random", "/genres", "/genres Action", "/watch Avatar",
                "/unwatch Avatar", "/watchlist", "/logs", "/enrich", "/enrich_status"):
        msg = FakeMessage(cmd)
        await commands.handle_command(None, msg)

    assert calls == ["cmd_random", "cmd_genres", "cmd_genres", "cmd_watch",
                     "cmd_unwatch", "cmd_watchlist", "cmd_logs", "cmd_enrich",
                     "cmd_enrich_status"]


# ------------------------------------------------------------------ #
#  Standalone runner                                                 #
# ------------------------------------------------------------------ #


def main():
    """Run the whole file under pytest (fixtures like monkeypatch needed)."""
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


if __name__ == "__main__":
    main()
