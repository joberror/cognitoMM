#!/usr/bin/env python3
"""
Test: TMDb-ID identity for watchlist/requests + request voting + auto-fulfill.

Pins the cluster-2/4 upgrade:

1. Indexing persists ``tmdb_id`` (canonical identity) - covered indirectly
   via the matchers below which read ``entry["tmdb_id"]``.
2. Watchlist (features/user_management.py):
   - add_to_watchlist resolves + stores tmdb_id, idempotent on either key
   - notify_watchlist matches by tmdb_id across spellings, title fallback
3. Requests (features/request_management.py):
   - check_duplicate_request: tmdb match beats spelling, year compare is
     str-tolerant, backward compatible without tmdb_id
   - upvote_request: idempotent per user, accumulates across users
   - fulfill_matching_requests: tmdb-first match, marks completed, DMs
     requester + voters with a Get button
   - request_priority_key: votes desc, then oldest first

All DB/Telegram access runs against injected fakes - no live services.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

# Ensure project root on path so `features` is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import features.config as config
import features.request_management as request_management
import features.tmdb_integration as tmdb_integration
import features.user_management as user_management


# ------------------------------------------------------------------ #
# Fakes                                                               #
# ------------------------------------------------------------------ #

def _watch_doc_matches(doc, filt):
    for k, cond in (filt or {}).items():
        if k == "$or":
            if not any(_watch_doc_matches(doc, branch) for branch in cond):
                return False
            continue
        if k == "user_id":
            if doc.get("user_id") != cond:
                return False
            continue
        if k.startswith("watchlist."):
            field = k.split(".", 1)[1]
            entries = doc.get("watchlist") or []
            if isinstance(cond, dict) and "$ne" in cond:
                if any(e.get(field) == cond["$ne"] for e in entries):
                    return False
            elif not any(e.get(field) == cond for e in entries):
                return False
            continue
        if doc.get(k) != cond:
            return False
    return True


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return [dict(d) for d in self._docs[:length]] if length else [dict(d) for d in self._docs]


class FakeUsersCol:
    """users_col stand-in supporting the watchlist query/update shapes."""

    def __init__(self):
        self.docs = []

    def _find(self, filt):
        return [d for d in self.docs if _watch_doc_matches(d, filt)]

    async def find_one(self, filt, projection=None):
        found = self._find(filt)
        return dict(found[0]) if found else None

    def find(self, filt):
        return FakeCursor(self._find(filt))

    async def update_one(self, filt, update, upsert=False):
        found = self._find(filt)
        if found:
            doc = found[0]
            for field, value in (update.get("$push") or {}).items():
                doc.setdefault(field, []).append(dict(value))
            for field, value in (update.get("$pull") or {}).items():
                if field == "watchlist":
                    cond = value or {}
                    doc[field] = [e for e in doc.get(field, [])
                                  if not all(e.get(k) == v for k, v in cond.items())]
            return SimpleNamespace(matched_count=1, modified_count=1)
        if upsert:
            doc = dict((update.get("$setOnInsert") or {}))
            doc.setdefault("watchlist", [])
            self.docs.append(doc)
            return SimpleNamespace(matched_count=0, modified_count=0)
        return SimpleNamespace(matched_count=0, modified_count=0)


class FakeRequestsCol:
    """requests_col stand-in (equality filters + $set updates)."""

    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]

    @staticmethod
    def _matches(doc, query):
        for key, expected in (query or {}).items():
            if doc.get(key) != expected:
                return False
        return True

    def find(self, query):
        return FakeCursor([d for d in self.docs if self._matches(d, query)])

    async def find_one(self, query, **kwargs):
        for doc in self.docs:
            if self._matches(doc, query):
                return dict(doc)
        return None

    async def count_documents(self, query):
        return sum(1 for d in self.docs if self._matches(d, query))

    async def insert_one(self, doc):
        new_doc = dict(doc)
        new_doc.setdefault("_id", len(self.docs) + 1)
        self.docs.append(new_doc)
        return SimpleNamespace(inserted_id=new_doc["_id"])

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if self._matches(doc, query):
                for field, value in (update.get("$set") or {}).items():
                    doc[field] = value
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)


class FakeClient:
    """config.client stand-in - records send_message calls."""

    def __init__(self):
        self.sent = []

    async def send_message(self, uid, text, reply_markup=None, **kwargs):
        self.sent.append({"uid": uid, "text": text, "markup": reply_markup})
        return SimpleNamespace(id=1)


def _install(users=None, requests=None, client=None, enrich=None):
    """Swap module attrs for fakes. Returns (users, requests, client)."""
    users = users if users is not None else FakeUsersCol()
    requests = requests if requests is not None else FakeRequestsCol()
    client = client if client is not None else FakeClient()
    user_management.users_col = users
    request_management.requests_col = requests
    config.client = client
    if enrich is not None:
        tmdb_integration.enrich_title = enrich
    return users, requests, client


def _restore(real_users, real_requests, real_client, real_enrich):
    user_management.users_col = real_users
    request_management.requests_col = real_requests
    config.client = real_client
    tmdb_integration.enrich_title = real_enrich


def run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        loop = asyncio.new_event_loop()
    return loop.run_until_complete(coro)


async def _tmdb_999(title, year=None, content_type="Movie", use_cache=True):
    return {"tmdb_id": 999, "rating": 8.0, "genres": ["Sci-Fi"],
            "poster_url": None, "overview": "", "imdb_id": "tt1234567"}


# ------------------------------------------------------------------ #
# Watchlist                                                           #
# ------------------------------------------------------------------ #

async def test_watch_add_stores_tmdb_and_dedups():
    real = (user_management.users_col, request_management.requests_col,
            config.client, tmdb_integration.enrich_title)
    _install(enrich=_tmdb_999)
    try:
        added = await user_management.add_to_watchlist(1, "Dune")
        assert added is True
        doc = await user_management.users_col.find_one({"user_id": 1})
        assert doc["watchlist"][0]["tmdb_id"] == 999, doc
        # Same title, different case -> already watched (no duplicate).
        added_again = await user_management.add_to_watchlist(1, "dune")
        assert added_again is False
        doc = await user_management.users_col.find_one({"user_id": 1})
        assert len(doc["watchlist"]) == 1, doc
    finally:
        _restore(*real)


async def test_watch_notify_matches_tmdb_across_spellings():
    real = (user_management.users_col, request_management.requests_col,
            config.client, tmdb_integration.enrich_title)
    users, _, client = _install(enrich=_tmdb_999)
    try:
        await user_management.add_to_watchlist(11, "Dune")          # tmdb 999
        await user_management.add_to_watchlist(22, "Doon", tmdb_id=999)  # same film
        await user_management.add_to_watchlist(33, "Unrelated")     # other film
        for d in users.docs:  # "Unrelated" resolved to 999 via the stub; fix it
            if d["user_id"] == 33:
                d["watchlist"][0]["tmdb_id"] = 111
        notified = await user_management.notify_watchlist(
            {"title": "Dune: Part Two", "year": 2024, "tmdb_id": 999,
             "channel_id": -100, "message_id": 7})
        assert notified == 2, client.sent
        assert sorted(s["uid"] for s in client.sent) == [11, 22]
        # Get button points at the fresh copy.
        assert "get_file:-100:7" in str(client.sent[0]["markup"])
    finally:
        _restore(*real)


async def test_watch_notify_title_fallback_without_tmdb():
    real = (user_management.users_col, request_management.requests_col,
            config.client, tmdb_integration.enrich_title)
    _, _, client = _install(enrich=AsyncMock(return_value=None))
    try:
        await user_management.add_to_watchlist(44, "Lucky")
        notified = await user_management.notify_watchlist(
            {"title": "Lucky", "channel_id": -100, "message_id": 9})
        assert notified == 1, client.sent
        assert client.sent[0]["uid"] == 44
    finally:
        _restore(*real)


# ------------------------------------------------------------------ #
# Requests                                                            #
# ------------------------------------------------------------------ #

async def test_duplicate_tmdb_beats_spelling():
    reqs = FakeRequestsCol([{
        "_id": 1, "user_id": 5, "title": "Dune", "year": "2021",
        "tmdb_id": 555, "status": "pending",
        "request_date": datetime.now(timezone.utc),
    }])
    real = (user_management.users_col, request_management.requests_col,
            config.client, tmdb_integration.enrich_title)
    _install(requests=reqs)
    try:
        dup, match = await request_management.check_duplicate_request(
            "Doon", "2021", 5, tmdb_id=555)
        assert dup is True and match["_id"] == 1, (dup, match)
        dup, _ = await request_management.check_duplicate_request(
            "Doon", "2021", 5, tmdb_id=777)
        assert dup is False, dup  # different film, low title similarity
        # Backward compatible: no tmdb_id -> fuzzy title + year as before.
        dup, _ = await request_management.check_duplicate_request("Dune", "2021", 5)
        assert dup is True
        dup, _ = await request_management.check_duplicate_request("Dune", "1984", 5)
        assert dup is False
    finally:
        _restore(*real)


async def test_upvote_idempotent_and_accumulates():
    reqs = FakeRequestsCol([{
        "_id": 10, "user_id": 5, "title": "Dune", "year": "2021",
        "tmdb_id": 555, "status": "pending", "votes": 0, "voters": [],
        "request_date": datetime.now(timezone.utc),
    }])
    real = (user_management.users_col, request_management.requests_col,
            config.client, tmdb_integration.enrich_title)
    _install(requests=reqs)
    try:
        ok, votes = await request_management.upvote_request(10, 6)
        assert (ok, votes) == (True, 1), (ok, votes)
        ok, votes = await request_management.upvote_request(10, 6)
        assert (ok, votes) == (True, 1), (ok, votes)  # no double count
        ok, votes = await request_management.upvote_request(10, 7)
        assert (ok, votes) == (True, 2), (ok, votes)
        ok, _ = await request_management.upvote_request(999, 7)
        assert ok is False
    finally:
        _restore(*real)


async def test_fulfill_by_tmdb_notifies_requester_and_voters():
    now = datetime.now(timezone.utc)
    reqs = FakeRequestsCol([
        {"_id": 20, "user_id": 5, "title": "Doon", "year": "2021",
         "tmdb_id": 555, "status": "pending", "votes": 2, "voters": [6, 7],
         "request_date": now},
        {"_id": 21, "user_id": 8, "title": "Other Film", "year": "2020",
         "tmdb_id": 888, "status": "pending", "votes": 0, "voters": [],
         "request_date": now},
    ])
    real = (user_management.users_col, request_management.requests_col,
            config.client, tmdb_integration.enrich_title)
    _, _, client = _install(requests=reqs)
    try:
        n = await request_management.fulfill_matching_requests(
            {"title": "Dune", "year": 2021, "tmdb_id": 555,
             "channel_id": -100, "message_id": 42})
        assert n == 1, n
        done = await reqs.find_one({"_id": 20})
        assert done["status"] == "completed", done
        assert done["completed_by"] == "auto_index", done
        still = await reqs.find_one({"_id": 21})
        assert still["status"] == "pending", still
        assert sorted(s["uid"] for s in client.sent) == [5, 6, 7], client.sent
    finally:
        _restore(*real)


async def test_fulfill_title_year_fallback_without_tmdb():
    reqs = FakeRequestsCol([{
        "_id": 30, "user_id": 5, "title": "Lucky", "year": "2025",
        "tmdb_id": None, "status": "pending", "votes": 0, "voters": [],
        "request_date": datetime.now(timezone.utc),
    }])
    real = (user_management.users_col, request_management.requests_col,
            config.client, tmdb_integration.enrich_title)
    _, _, client = _install(requests=reqs)
    try:
        n = await request_management.fulfill_matching_requests(
            {"title": "lucky", "year": 2025, "channel_id": -100, "message_id": 3})
        assert n == 1, n
        assert [s["uid"] for s in client.sent] == [5]
    finally:
        _restore(*real)


async def test_priority_key_votes_then_oldest():
    base = datetime.now(timezone.utc)
    reqs = [
        {"title": "B", "votes": 0, "request_date": base - timedelta(days=2)},
        {"title": "A", "votes": 5, "request_date": base},
        {"title": "C", "votes": 5, "request_date": base - timedelta(days=1)},
        {"title": "D", "request_date": base - timedelta(days=3)},  # legacy, no votes
    ]
    ordered = sorted(reqs, key=request_management.request_priority_key)
    # 5-vote pair first (older C before A), then 0-vote pair oldest-first
    # (legacy D has no votes key but the oldest date, so it leads B).
    assert [r["title"] for r in ordered] == ["C", "A", "D", "B"], ordered


async def test_global_match_skips_own_requests():
    now = datetime.now(timezone.utc)
    reqs = FakeRequestsCol([
        {"_id": 40, "user_id": 5, "title": "Dune", "year": "2021",
         "tmdb_id": 555, "status": "pending", "votes": 0, "voters": [],
         "request_date": now},
    ])
    real = (user_management.users_col, request_management.requests_col,
            config.client, tmdb_integration.enrich_title)
    _install(requests=reqs)
    try:
        match = await request_management.find_global_match("Dune", "2021", 555,
                                                           exclude_user_id=5)
        assert match is None, match
        match = await request_management.find_global_match("Dune", "2021", 555,
                                                           exclude_user_id=6)
        assert match is not None and match["_id"] == 40, match
    finally:
        _restore(*real)


# ------------------------------------------------------------------ #
# Standalone runner (python tests/test_tmdb_identity_requests.py)     #
# ------------------------------------------------------------------ #

_TESTS = [
    test_watch_add_stores_tmdb_and_dedups,
    test_watch_notify_matches_tmdb_across_spellings,
    test_watch_notify_title_fallback_without_tmdb,
    test_duplicate_tmdb_beats_spelling,
    test_upvote_idempotent_and_accumulates,
    test_fulfill_by_tmdb_notifies_requester_and_voters,
    test_fulfill_title_year_fallback_without_tmdb,
    test_priority_key_votes_then_oldest,
    test_global_match_skips_own_requests,
]


def main() -> int:
    failures = 0
    for fn in _TESTS:
        try:
            run(fn())
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
