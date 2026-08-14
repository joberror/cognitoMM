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
import re
import sys
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Ensure project root is on the path so the features package is importable
# when this file is run standalone (python tests/test_new_features.py).
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from pyrogram.enums import ChatType

import features.callbacks as callbacks
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
        # Matches pyrogram/pyroblack: get_chat_history returns an ASYNC
        # GENERATOR, not a coroutine - awaiting it directly raises
        # "object async_generator can't be used in 'await' expression".
        async def get_chat_history(self, chat_id, limit=1):
            for m in [SimpleNamespace(id=1000)]:
                yield m

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


async def test_incremental_rescan_empty_history_returns_none():
    """A channel with no messages (empty generator) must yield None, not crash."""

    class EmptyHistoryClient:
        async def get_chat_history(self, chat_id, limit=1):
            if False:
                yield None  # async generator body; yields nothing

    class EmptySettings:
        async def find_one(self, filt):
            return None

    fs = EmptySettings()

    ch = {"channel_id": -100, "channel_title": "Empty"}
    result = await dbs.incremental_rescan(EmptyHistoryClient(), ch, settings_col_ref=fs)
    assert result is None


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
#  /random caption + /my_history bracket listing                     #
# ------------------------------------------------------------------ #


async def test_cmd_random_caption_uses_bracket_style(monkeypatch):
    """/random caption shows the /search-style bracket info."""
    msg = FakeMessage("/random")

    async def _no(m):
        return False

    monkeypatch.setattr(commands, "check_banned", _no)

    class FakeMovies:
        async def count_documents(self, filt):
            return 1

        async def find_one(self, filt=None, skip=None):
            return {"title": "The Matrix", "year": 1999, "quality": "1080p",
                    "rip": "BluRay", "type": "Movie", "channel_id": -1001,
                    "message_id": 1, "tmdb_poster": None}

    monkeypatch.setattr(commands, "movies_col", FakeMovies())

    await commands.cmd_random(None, msg)

    assert msg.replies
    text = msg.replies[0][0][0]
    assert "🎬 <b>The Matrix</b> [1080p.1999.Blu] · Movie" in text
    assert "🎞️ Quality:" not in text  # folded into the bracket info


async def test_cmd_my_history_bracket_listing(monkeypatch):
    """/my_history lists queries as numbered bracket lines in a code block."""
    msg = FakeMessage("/my_history")

    class FakeUsers:
        async def find_one(self, filt, projection=None):
            return {"user_id": 42, "search_history": [
                {"q": "The Matrix", "ts": datetime(2026, 8, 14, 14, 15, tzinfo=timezone.utc)},
                {"q": "Inception", "ts": datetime(2026, 8, 14, 10, 10, tzinfo=timezone.utc)},
                {"q": "Interstellar", "ts": datetime(2026, 8, 13, 11, 50, tzinfo=timezone.utc)},
            ]}

    monkeypatch.setattr(commands, "users_col", FakeUsers())

    await commands.cmd_my_history(None, msg)

    assert msg.replies
    text = msg.replies[0][0][0]
    assert text.startswith("```")
    assert "SEARCH HISTORY" in text
    assert "Total: 3 | Unique: 3" in text
    assert "1. Interstellar [11:50AM]" in text
    assert "2. Inception [10:10AM]" in text
    assert "3. The Matrix [02:15PM]" in text
    assert "Re-search with /f title" in text


# ------------------------------------------------------------------ #
#  /watchlist bracket listing                                        #
# ------------------------------------------------------------------ #


async def test_cmd_watchlist_renders_bracket_lines(monkeypatch):
    """/watchlist lists entries in the /search bracket style inside a code block."""
    msg = FakeMessage("/watchlist")

    async def _fake_watchlist(uid):
        return [
            {"title": "Inception", "year": 2010, "type": "Movie"},
            {"title": "Breaking Bad", "year": 2008, "type": "Series"},
            {"title": "No Year", "type": "Movie"},
        ]

    monkeypatch.setattr(um, "get_watchlist", _fake_watchlist)
    await commands.cmd_watchlist(None, msg)

    assert msg.replies
    text = msg.replies[0][0][0]
    assert text.startswith("👁️ Your Watchlist")
    assert "```" in text
    assert "1. Inception [2010.Movie]" in text
    assert "2. Breaking Bad [2008.Series]" in text
    assert "3. No Year [Movie]" in text
    assert "Remove with /unwatch title" in text


# ------------------------------------------------------------------ #
#  /genres <name> pagination                                         #
# ------------------------------------------------------------------ #


class FakeGenreMovies:
    """movies_col fake that executes the genre aggregation pipelines.

    Supports the two pipeline shapes used by the genre browse: distinct-title
    pages ($match/$group/$sort/$skip/$limit) and the distinct-title count
    ($match/$group/$count). Records the last $sort spec so tests can pin the
    query side of the sort toggle."""

    def __init__(self, docs):
        self.docs = list(docs)
        self.last_sort_spec = None

    def aggregate(self, pipeline):
        self.last_sort_spec = next((s["$sort"] for s in pipeline if "$sort" in s), None)
        docs = list(self.docs)

        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if self._match(d, stage["$match"])]
            elif "$group" in stage:
                docs = self._group(docs, stage["$group"])
            elif "$sort" in stage:
                docs = self._sort(docs, stage["$sort"])
            elif "$skip" in stage:
                docs = docs[stage["$skip"]:]
            elif "$limit" in stage:
                docs = docs[:stage["$limit"]]
            elif "$count" in stage:
                docs = [{"n": len(docs)}] if docs else []

        class _Agg:
            def __init__(self, result):
                self.result = result

            async def to_list(self, length=None):
                return self.result

        return _Agg(docs)

    def _match(self, d, filt):
        for key, cond in filt.items():
            if key == "title" and "$in" in cond and d.get("title") not in cond["$in"]:
                return False
            if key == "tmdb_genres" and "$regex" in cond:
                rx = re.compile(cond["$regex"], re.IGNORECASE)
                if not any(rx.match(g or "") for g in (d.get("tmdb_genres") or [])):
                    return False
        return True

    def _group(self, docs, group):
        key = group["_id"].lstrip("$")
        buckets, order = {}, []
        for d in docs:
            k = d.get(key)
            if k not in buckets:
                buckets[k] = []
                order.append(k)
            buckets[k].append(d)

        out = []
        for k in order:
            gd = {"_id": k}
            for field, expr in group.items():
                if field == "_id":
                    continue
                if "$first" in expr:
                    gd[field] = buckets[k][0].get(expr["$first"].lstrip("$"))
                elif "$sum" in expr:
                    gd[field] = len(buckets[k])
                elif "$addToSet" in expr:
                    sub = expr["$addToSet"]
                    if isinstance(sub, dict):
                        # dict exprs map output key -> $field path
                        gd[field] = [{k: d.get(v.lstrip("$")) for k, v in sub.items()}
                                     for d in buckets[k]]
                    else:
                        gd[field] = list({d.get(sub.lstrip("$")) for d in buckets[k]})
                elif "$max" in expr:
                    # MongoDB $max ignores missing/None values - mimic that
                    # (max(None, None) would raise TypeError otherwise).
                    gd[field] = max(
                        (d.get(expr["$max"].lstrip("$")) for d in buckets[k]
                         if d.get(expr["$max"].lstrip("$")) is not None),
                        default=None,
                    )
                elif "$push" in expr:
                    sub = expr["$push"]
                    if isinstance(sub, dict):
                        # dict exprs map output key -> $field path
                        gd[field] = [{k: d.get(v.lstrip("$")) for k, v in sub.items()}
                                     for d in buckets[k]]
                    else:
                        gd[field] = [d.get(sub.lstrip("$")) for d in buckets[k]]
            out.append(gd)
        return out

    def _sort(self, docs, spec):
        ordered = list(docs)
        for k, direction in reversed(list(spec.items())):
            field = k.lstrip("$")
            ordered.sort(
                key=lambda d, f=field: (d.get(f) is None, d.get(f)),
                reverse=(direction == -1),
            )
        return ordered


def _genre_doc(n, genre="Action"):
    # Zero-padded titles so the aggregation's string sort == numeric order.
    return {"_id": n, "title": f"Movie {n:02d}", "year": 2000 + n % 20,
            "quality": "1080p", "channel_id": -1001, "message_id": n,
            "type": "Movie", "tmdb_genres": [genre], "tmdb_rating": 7.5}


class _FakeGenreCbq:
    """callback_query: records answer() + message.edit_text()."""

    def __init__(self, data, user_id=42):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []

        class _Msg:
            def __init__(self):
                self.edits = []

            async def edit_text(self, text, **kwargs):
                self.edits.append((text, kwargs))

        self.message = _Msg()

    async def answer(self, text, show_alert=False):
        self.answers.append((text, show_alert))


def _flat(kb):
    return {b.text: b.callback_data for row in kb.inline_keyboard for b in row}


async def test_cmd_genres_browse_paginates(monkeypatch):
    """/genres <name> shows the total count + first page with Next nav."""
    msg = FakeMessage("/genres Action")

    async def _no(m):
        return False

    monkeypatch.setattr(commands, "check_banned", _no)
    monkeypatch.setattr(commands, "movies_col", FakeGenreMovies([_genre_doc(i) for i in range(1, 26)]))
    monkeypatch.setattr(commands, "enrich_title", AsyncMock(return_value=None))
    cached = {}
    monkeypatch.setattr(commands, "bulk_downloads", cached)

    await commands.cmd_genres(None, msg)

    assert msg.replies
    text = msg.replies[0][0][0]
    kwargs = msg.replies[0][1]
    assert "Total Results: 25 | Page 1/3" in text
    # one deduped line per title, movie style: "N. Title - N files"
    assert "1. Movie 01 - 1 file" in text
    assert "Movie 12 - 1 file" in text
    assert "Movie 13" not in text
    buttons = _flat(kwargs["reply_markup"])
    assert buttons.get("Get [1]") == "get_file:-1001:1"
    assert buttons.get("Get [12]") == "get_file:-1001:12"
    assert buttons["Next →"].startswith("genre_page:") and buttons["Next →"].endswith(":2:az")
    assert "← Prev" not in buttons
    assert buttons.get("🔤 A–Z ✓") is not None and buttons.get("🆕 Newest") is not None
    assert len(cached) == 1  # pagination state stored for the callback
    assert cached[list(cached)[0]]["sort"] == "az"


async def test_cmd_genres_series_deduped_with_real_counts(monkeypatch):
    """Each title appears ONCE with DB aggregates + real TMDb counts in brackets.

    Series: ``3 seasons [5], 20 eps [35], 20 files`` (bracket = real TMDb
    totals). DB counts use distinct seasons and distinct episode pairs so
    duplicate-quality copies don't inflate them."""
    docs = [
        # Breaking Bad: 4 copies, 2 distinct seasons, 3 distinct episodes
        {"_id": 1, "title": "Breaking Bad", "year": 2008, "quality": "1080p",
         "type": "Series", "season": 1, "episode": 1,
         "channel_id": -1002, "message_id": 2, "tmdb_genres": ["Action"]},
        {"_id": 2, "title": "Breaking Bad", "year": 2008, "quality": "720p",
         "type": "Series", "season": 1, "episode": 2,
         "channel_id": -1002, "message_id": 3, "tmdb_genres": ["Action"]},
        # duplicate quality of S01E01 must NOT inflate the episode count
        {"_id": 3, "title": "Breaking Bad", "year": 2008, "quality": "2160p",
         "type": "Series", "season": 1, "episode": 1,
         "channel_id": -1002, "message_id": 4, "tmdb_genres": ["Action"]},
        {"_id": 4, "title": "Breaking Bad", "year": 2008, "quality": "1080p",
         "type": "Series", "season": 2, "episode": 5,
         "channel_id": -1002, "message_id": 5, "tmdb_genres": ["Action"]},
        # Die Hard: single movie copy
        {"_id": 5, "title": "Die Hard", "year": 1988, "quality": "1080p",
         "type": "Movie", "channel_id": -1001, "message_id": 1, "tmdb_genres": ["Action"]},
    ]
    msg = FakeMessage("/genres Action")

    async def _no(m):
        return False

    monkeypatch.setattr(commands, "check_banned", _no)
    monkeypatch.setattr(commands, "movies_col", FakeGenreMovies(docs))
    monkeypatch.setattr(commands, "bulk_downloads", {})

    async def fake_enrich(title, year=None, content_type="Movie"):
        if title == "Breaking Bad":
            return {"rating": 8.9, "seasons": 5, "episodes": 35}
        return {"rating": 7.6}

    monkeypatch.setattr(commands, "enrich_title", fake_enrich)

    await commands.cmd_genres(None, msg)

    text = msg.replies[0][0][0]
    # Breaking Bad appears exactly ONCE, with DB counts + real [5]/[35]
    assert text.count("Breaking Bad") == 1
    assert "1. Breaking Bad - 2 seasons [5], 3 eps [35], 4 files ⭐8.9" in text
    # movies: minimal "Title - N files" line (no seasons/episodes)
    assert "2. Die Hard - 1 file ⭐7.6" in text
    # the Get button for a multi-copy series points at the BEST-quality copy
    buttons = _flat(msg.replies[0][1]["reply_markup"])
    assert buttons.get("Get [1]") == "get_file:-1002:4"  # 2160p copy


async def test_cmd_genres_browse_empty_genre(monkeypatch):
    """A genre with zero titles still gets the friendly no-results reply."""
    msg = FakeMessage("/genres Action")

    async def _no(m):
        return False

    monkeypatch.setattr(commands, "check_banned", _no)
    monkeypatch.setattr(commands, "movies_col", FakeGenreMovies([]))

    await commands.cmd_genres(None, msg)

    assert msg.replies
    assert "No indexed titles found in genre <b>Action</b>" in msg.replies[0][0][0]


async def test_genre_page_callback_paginates(monkeypatch):
    """genre_page: re-renders the stored browse on the requested page."""
    monkeypatch.setattr(commands, "movies_col", FakeGenreMovies([_genre_doc(i) for i in range(1, 26)]))
    cached = {"gid1234": {"type": "genre_list", "genre": "Action", "total": 25,
                          "user_id": 42, "created_at": datetime.now(timezone.utc)}}
    cbq = _FakeGenreCbq(data="genre_page:gid1234:2", user_id=42)

    with ExitStack() as stack:
        stack.enter_context(patch.object(callbacks, "bulk_downloads", cached))
        stack.enter_context(patch.object(callbacks, "has_accepted_terms", AsyncMock(return_value=True)))
        stack.enter_context(patch.object(callbacks, "should_process_command_for_user", AsyncMock(return_value=True)))
        stack.enter_context(patch.object(commands, "enrich_title", AsyncMock(return_value=None)))
        await callbacks.callback_handler(None, cbq)

    assert cbq.message.edits
    text, kwargs = cbq.message.edits[0]
    assert "Page 2/3" in text
    assert "Movie 13" in text and "Movie 24" in text
    assert "Movie 25" not in text
    buttons = _flat(kwargs["reply_markup"])
    assert buttons.get("Get [13]") == "get_file:-1001:13"
    assert buttons.get("← Prev") == "genre_page:gid1234:1:az"
    assert buttons.get("Next →") == "genre_page:gid1234:3:az"
    assert any(a[0] == "📄 Page 2" for a in cbq.answers)


async def test_genre_page_callback_ownership_guard(monkeypatch):
    """Another user's genre browse is rejected without re-rendering."""
    cached = {"gid1234": {"type": "genre_list", "genre": "Action", "total": 25,
                          "user_id": 42, "created_at": datetime.now(timezone.utc)}}
    cbq = _FakeGenreCbq(data="genre_page:gid1234:2", user_id=99)  # not the owner

    with ExitStack() as stack:
        stack.enter_context(patch.object(callbacks, "bulk_downloads", cached))
        stack.enter_context(patch.object(callbacks, "has_accepted_terms", AsyncMock(return_value=True)))
        stack.enter_context(patch.object(callbacks, "should_process_command_for_user", AsyncMock(return_value=True)))
        await callbacks.callback_handler(None, cbq)

    assert not cbq.message.edits
    assert cbq.answers and "own genre lists" in cbq.answers[0][0]


async def test_genre_page_callback_sort_toggle(monkeypatch):
    """4-part data switches the sort to newest-first and keeps it in state."""
    movies = FakeGenreMovies([_genre_doc(i) for i in range(1, 26)])
    monkeypatch.setattr(commands, "movies_col", movies)
    cached = {"gid1234": {"type": "genre_list", "genre": "Action", "total": 25,
                          "sort": "az", "user_id": 42,
                          "created_at": datetime.now(timezone.utc)}}
    cbq = _FakeGenreCbq(data="genre_page:gid1234:1:new", user_id=42)

    with ExitStack() as stack:
        stack.enter_context(patch.object(callbacks, "bulk_downloads", cached))
        stack.enter_context(patch.object(callbacks, "has_accepted_terms", AsyncMock(return_value=True)))
        stack.enter_context(patch.object(callbacks, "should_process_command_for_user", AsyncMock(return_value=True)))
        stack.enter_context(patch.object(commands, "enrich_title", AsyncMock(return_value=None)))
        await callbacks.callback_handler(None, cbq)

    assert cbq.message.edits
    text, kwargs = cbq.message.edits[0]
    assert "Page 1/3" in text
    buttons = _flat(kwargs["reply_markup"])
    assert buttons.get("🆕 Newest ✓") is not None
    assert buttons.get("🔤 A–Z") is not None
    # Query side: the aggregation sorts by max indexed_at desc.
    assert movies.last_sort_spec == {"max_indexed_at": -1, "_id": -1}
    # Nav + toggle buttons carry the new sort; state stays in sync.
    assert buttons["Next →"].endswith(":2:new")
    assert cached["gid1234"]["sort"] == "new"


async def test_genre_page_callback_legacy_3_part_uses_stored_sort(monkeypatch):
    """Pre-deploy 3-part data re-renders with the stored sort, not az."""
    movies = FakeGenreMovies([_genre_doc(i) for i in range(1, 26)])
    monkeypatch.setattr(commands, "movies_col", movies)
    cached = {"gid1234": {"type": "genre_list", "genre": "Action", "total": 25,
                          "sort": "new", "user_id": 42,
                          "created_at": datetime.now(timezone.utc)}}
    cbq = _FakeGenreCbq(data="genre_page:gid1234:2", user_id=42)  # legacy 3-part

    with ExitStack() as stack:
        stack.enter_context(patch.object(callbacks, "bulk_downloads", cached))
        stack.enter_context(patch.object(callbacks, "has_accepted_terms", AsyncMock(return_value=True)))
        stack.enter_context(patch.object(callbacks, "should_process_command_for_user", AsyncMock(return_value=True)))
        stack.enter_context(patch.object(commands, "enrich_title", AsyncMock(return_value=None)))
        await callbacks.callback_handler(None, cbq)

    assert cbq.message.edits
    _, kwargs = cbq.message.edits[0]
    buttons = _flat(kwargs["reply_markup"])
    assert buttons.get("🆕 Newest ✓") is not None
    assert movies.last_sort_spec == {"max_indexed_at": -1, "_id": -1}


async def test_genre_page_callback_rating_sort(monkeypatch):
    """4-part :rate data sorts by tmdb_rating desc and marks Top Rated active."""
    movies = FakeGenreMovies([_genre_doc(i) for i in range(1, 26)])
    monkeypatch.setattr(commands, "movies_col", movies)
    cached = {"gid1234": {"type": "genre_list", "genre": "Action", "total": 25,
                          "sort": "az", "user_id": 42,
                          "created_at": datetime.now(timezone.utc)}}
    cbq = _FakeGenreCbq(data="genre_page:gid1234:1:rate", user_id=42)

    with ExitStack() as stack:
        stack.enter_context(patch.object(callbacks, "bulk_downloads", cached))
        stack.enter_context(patch.object(callbacks, "has_accepted_terms", AsyncMock(return_value=True)))
        stack.enter_context(patch.object(callbacks, "should_process_command_for_user", AsyncMock(return_value=True)))
        stack.enter_context(patch.object(commands, "enrich_title", AsyncMock(return_value=None)))
        await callbacks.callback_handler(None, cbq)

    assert cbq.message.edits
    _, kwargs = cbq.message.edits[0]
    buttons = _flat(kwargs["reply_markup"])
    assert buttons.get("⭐ Top Rated ✓") is not None
    assert buttons.get("🔤 A–Z") is not None
    assert movies.last_sort_spec == {"max_rating": -1, "_id": 1}
    assert buttons["Next →"].endswith(":2:rate")
    assert cached["gid1234"]["sort"] == "rate"


async def test_genre_page_callback_unknown_sort_normalizes_to_az(monkeypatch):
    """A malformed sort value falls back to A–Z instead of erroring."""
    movies = FakeGenreMovies([_genre_doc(i) for i in range(1, 26)])
    monkeypatch.setattr(commands, "movies_col", movies)
    cached = {"gid1234": {"type": "genre_list", "genre": "Action", "total": 25,
                          "sort": "az", "user_id": 42,
                          "created_at": datetime.now(timezone.utc)}}
    cbq = _FakeGenreCbq(data="genre_page:gid1234:1:bogus", user_id=42)

    with ExitStack() as stack:
        stack.enter_context(patch.object(callbacks, "bulk_downloads", cached))
        stack.enter_context(patch.object(callbacks, "has_accepted_terms", AsyncMock(return_value=True)))
        stack.enter_context(patch.object(callbacks, "should_process_command_for_user", AsyncMock(return_value=True)))
        stack.enter_context(patch.object(commands, "enrich_title", AsyncMock(return_value=None)))
        await callbacks.callback_handler(None, cbq)

    assert cbq.message.edits
    _, kwargs = cbq.message.edits[0]
    buttons = _flat(kwargs["reply_markup"])
    assert buttons.get("🔤 A–Z ✓") is not None
    assert movies.last_sort_spec == {"_id": 1}


# ------------------------------------------------------------------ #
#  Standalone runner                                                 #
# ------------------------------------------------------------------ #


def main():
    """Run the whole file under pytest (fixtures like monkeypatch needed)."""
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


if __name__ == "__main__":
    main()
