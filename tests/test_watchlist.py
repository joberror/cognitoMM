#!/usr/bin/env python3
"""
Test: the TMDb-verified watchlist (/watch, /unwatch, /watchlist, UPDATE).

Pins the cluster-10 watchlist rebuild:

1. Status derivation (tmdb_integration.py) — movie Released / Upcoming /
   In Cinemas, series Continuing / Ended, plus the partial-payload fallbacks.
2. Ambiguity detection — remakes and movie-vs-show collisions go to the
   picker; a unique exact movie match is auto-picked.
3. Storage (user_management.py) — the extended entry shape, the free/premium
   capacity gate, and the per-entry status patch used by UPDATE.
4. Floodgate (notify_watchlist) — a burst of copies for one title DMs the
   watcher once; a second title in the same burst still notifies.
5. Rendering (watchlist.py) — the `Title: M / 2026 / Released · IMDb` line,
   the UPDATE keyboard, and callback-data ownership.
6. UPDATE — status re-fetch patches the entry and the cooldown blocks spam.
7. Callback routing — the picker and UPDATE buttons work through the real
   `callback_handler` (pick/cancel/expired, ownership, ownership of a
   forwarded UPDATE button, and a guard that both prefixes stay routed).

Run standalone (`python tests/test_watchlist.py`) or under pytest. An autouse
fixture restores every module-level fake this file swaps, so it is
order-independent and safe to run beside the rest of the suite.

All DB/Telegram/TMDb access runs against injected fakes - no live services.
"""

import asyncio
import os
import sys
import time
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import features.config as config
import features.premium_management as pm
import features.tmdb_integration as tmdb
import features.user_management as um
import features.watchlist as wl

# Captured before any stub so _install/_restore can put the real one back
# (pytest runs this module alongside others in one process).
_REAL_IS_PREMIUM_USER = pm.is_premium_user
_REAL_ENRICH_TITLE = tmdb.enrich_title


# ------------------------------------------------------------------ #
#  Fakes                                                              #
# ------------------------------------------------------------------ #

def _positional_match(filt):
    """Extract ``(field, cond)`` from the watchlist filter a positional $set targets.

    ``{"user_id": 1, "watchlist.title_key": "silo"}`` with a
    ``watchlist.$.status`` update means "the element where title_key ==
    'silo'".
    """
    for k, cond in (filt or {}).items():
        if k.startswith("watchlist.") and "." not in k.split(".", 1)[1]:
            return k.split(".", 1)[1], cond
    return None, None


def _element_matches(entry, field, cond):
    """True when one watchlist element satisfies a scalar/equality condition."""
    if field is None:
        return True
    if isinstance(cond, dict) and "$ne" in cond:
        return entry.get(field) != cond["$ne"]
    if isinstance(cond, dict):
        return all(entry.get(k) == v for k, v in cond.items())
    return entry.get(field) == cond


def _array_field_matches(doc, field, cond):
    """Mongo-ish semantics for a `watchlist.<field>: <cond>` filter.

    An array field matches if ANY element satisfies the condition. A `$ne`
    condition is special: it is satisfied only when NO element equals the
    value, so an empty array matches.
    """
    entries = doc.get("watchlist") or []
    if isinstance(cond, dict) and "$ne" in cond:
        return not any(e.get(field) == cond["$ne"] for e in entries)
    if isinstance(cond, dict):
        return any(all(e.get(k) == v for k, v in cond.items()) for e in entries)
    return any(e.get(field) == cond for e in entries)


def _doc_matches(doc, filt):
    for k, cond in (filt or {}).items():
        if k == "$or":
            if not any(_doc_matches(doc, b) for b in cond):
                return False
        elif k == "user_id":
            if doc.get("user_id") != cond:
                return False
        elif k.startswith("watchlist."):
            field = k.split(".", 1)[1]
            if not _array_field_matches(doc, field, cond):
                return False
        elif doc.get(k) != cond:
            return False
    return True


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return [dict(d) for d in (self._docs[:length] if length else self._docs)]


class FakeUsersCol:
    """users_col stand-in covering watchlist push/pull/$set-on-match."""

    def __init__(self):
        self.docs = []

    def _find(self, filt):
        return [d for d in self.docs if _doc_matches(d, filt)]

    async def find_one(self, filt, projection=None):
        found = self._find(filt)
        return dict(found[0]) if found else None

    def find(self, filt):
        return FakeCursor(self._find(filt))

    async def update_one(self, filt, update, upsert=False):
        found = self._find(filt)
        if found:
            doc = found[0]
            changed = False
            for field, value in (update.get("$push") or {}).items():
                # A $push whose filter already proved "no existing element
                # matches" (the $ne idempotency guard) appends.
                entries = doc.setdefault(field, [])
                entries.append(dict(value))
                changed = True
            for field, value in (update.get("$pull") or {}).items():
                cond = value or {}
                before = len(doc.get(field) or [])
                doc[field] = [e for e in doc.get(field, [])
                              if not all(e.get(k) == v for k, v in cond.items())]
                changed = changed or len(doc[field]) != before
            # $set with the positional `$` operator patches the first element
            # that satisfies the filter's matching watchlist.<field>.
            for path, value in (update.get("$set") or {}).items():
                if not path.startswith("watchlist.$."):
                    continue
                field = path.split(".$.", 1)[1]
                match_field, match_cond = _positional_match(filt)
                for e in doc.get("watchlist") or []:
                    if _element_matches(e, match_field, match_cond):
                        if e.get(field) != value:
                            changed = True
                        e[field] = value
                        break
            return SimpleNamespace(matched_count=1, modified_count=1 if changed else 0)
        if upsert:
            # A Mongo upsert inserts when the filter matches nothing; the
            # $setOnInsert fields seed the new document. Duplicate pushes are
            # caught by the $ne filters above, so this is the create path.
            doc = dict(update.get("$setOnInsert") or {})
            doc.setdefault("watchlist", [])
            self.docs.append(doc)
            return SimpleNamespace(matched_count=0, modified_count=0)
        return SimpleNamespace(matched_count=0, modified_count=0)


class FakeMessage:
    def __init__(self, user_id=1, text=""):
        self.from_user = SimpleNamespace(id=user_id, first_name="U", username="u")
        self.text = text
        self.chat = SimpleNamespace(id=user_id)
        self.replies = []
        self.edits = []

    async def reply_text(self, text, **kwargs):
        # Returns SELF so a test can watch the "Checking…" reply be edited
        # in place (the flow under test edits the message it just sent).
        self.replies.append({"text": text, **kwargs})
        return self

    async def edit_text(self, text, **kwargs):
        self.edits.append({"text": text, **kwargs})
        return self


class FakeQuery:
    """CallbackQuery stand-in. ``data`` is the callback payload (as sent)."""

    def __init__(self, user_id, message=None, data=""):
        self.from_user = SimpleNamespace(id=user_id)
        self.message = message or FakeMessage(user_id)
        self.data = data
        self.answers = []

    async def answer(self, text="", show_alert=False, **kwargs):
        self.answers.append(text)
        return None


class FakeClient:
    def __init__(self):
        self.sent = []

    async def send_message(self, uid, text, reply_markup=None, **kwargs):
        self.sent.append({"uid": uid, "text": text, "markup": reply_markup})
        return SimpleNamespace(id=1)


def _install(users=None, client=None, premium=False):
    """Install fakes. Also stubs the premium check so the DB is never touched.

    Every async helper here runs in its own throwaway event loop, and the real
    ``is_premium_user`` would query a motor collection bound to a closed loop —
    so the tier is injected instead, and no test depends on a live database.
    """
    users = users if users is not None else FakeUsersCol()
    client = client if client is not None else FakeClient()
    um.users_col = users
    config.client = client
    um.reset_notify_cooldowns()
    wl.reset_refresh_state()

    pm.is_premium_user = AsyncMock(return_value=premium)
    # add_to_watchlist falls back to enrich_title() to resolve a TMDb ID when
    # the caller doesn't pass one; stub it so no test reaches the network.
    tmdb.enrich_title = AsyncMock(return_value=None)
    return users, client


def _restore_premium():
    """Undo the fakes installed by :func:`_install`."""
    pm.is_premium_user = _REAL_IS_PREMIUM_USER
    tmdb.enrich_title = _REAL_ENRICH_TITLE


def run(coro):
    """Run one async test body to completion.

    A fresh loop per test (they share module-level fakes, so they must not
    share a loop) and a hard timeout: a missing stub would otherwise hang on a
    real network call instead of failing.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(asyncio.wait_for(coro, timeout=30))
    finally:
        loop.close()


def _cand(tmdb_id, title, year, type_="Movie", status="Released", **extra):
    c = {"tmdb_id": tmdb_id, "title": title, "year": year, "type": type_,
         "imdb_id": f"tt{tmdb_id:07d}", "status": status, "popularity": 10}
    c.update(extra)
    return c


# ------------------------------------------------------------------ #
#  1. Status derivation                                               #
# ------------------------------------------------------------------ #

def test_movie_status_released_upcoming_in_cinemas():
    today = date(2026, 9, 28)
    R, U, C = tmdb.STATUS_RELEASED, tmdb.STATUS_UPCOMING, tmdb.STATUS_IN_CINEMAS

    # Out and available everywhere -> Released.
    assert tmdb.derive_movie_status("2021-09-15", "Released", {3, 4}, today) == R
    # Announced / still in production with a future date -> Upcoming.
    assert tmdb.derive_movie_status("2027-01-01", "Post Production", None, today) == U
    assert tmdb.derive_movie_status("2027-01-01", "Planned", None, today) == U
    # No release_dates data at all + past date -> Released (calendar fallback).
    assert tmdb.derive_movie_status("2021-09-15", "Released", None, today) == R

    # Festival/premiere run: only Premiere (1) + limited Theatrical (2), no
    # wide (3), and the date is recent -> In Cinemas.
    assert tmdb.derive_movie_status("2026-09-20", "Released", {1, 2, 4}, today) == C
    # A wide release exists -> the film is in general circulation, not Cinemas.
    assert tmdb.derive_movie_status("2026-09-20", "Released", {1, 2, 3}, today) == R
    # Limited run that started long ago is over -> Released.
    assert tmdb.derive_movie_status("2024-09-20", "Released", {1, 2}, today) == R

    # TMDb flags a film Released ahead of its own date: trust the calendar.
    assert tmdb.derive_movie_status("2026-12-25", "Released", {3}, today) == U
    # Conversely, a past-dated film TMDb hasn't flipped to Released yet is
    # still out (status lags a few days behind wide releases).
    assert tmdb.derive_movie_status("2026-09-01", "Post Production", None, today) == R


def test_series_status_continuing_and_ended():
    today = date(2026, 9, 28)
    C, E = tmdb.STATUS_CONTINUING, tmdb.STATUS_ENDED

    assert tmdb.derive_series_status("2026-06-01", "Returning Series", None, today) == C
    assert tmdb.derive_series_status("2026-06-01", "In Production", None, today) == C
    assert tmdb.derive_series_status("2024-05-01", "Ended", None, today) == E
    assert tmdb.derive_series_status("2024-05-01", "Canceled", None, today) == E
    # A confirmed next episode overrides a stale "Ended".
    assert tmdb.derive_series_status("2024-05-01", "Ended",
                                     {"air_date": "2027-01-01"}, today) == C
    # No status: infer from air dates (stale vs still airing).
    assert tmdb.derive_series_status("2020-01-01", None, None, today) == E
    assert tmdb.derive_series_status("2026-08-01", None, None, today) == C
    # No data at all -> Unknown rather than a wrong guess.
    assert tmdb.derive_series_status(None, None, None, today) == tmdb.STATUS_UNKNOWN


def test_normalize_content_type():
    assert tmdb.normalize_content_type("Movie") == "Movie"
    assert tmdb.normalize_content_type("movie") == "Movie"
    assert tmdb.normalize_content_type(None) == "Movie"
    assert tmdb.normalize_content_type("Series") == "Series"
    assert tmdb.normalize_content_type("TV") == "Series"
    assert tmdb.normalize_content_type("tv show") == "Series"
    assert tmdb.normalize_content_type("Movie/Series") == "Series"


# ------------------------------------------------------------------ #
#  2. Ambiguity detection                                             #
# ------------------------------------------------------------------ #

def test_ambiguity_rules():
    # No candidates -> nothing to pick from (caller adds title-only).
    assert tmdb.is_ambiguous_title("Dune", []) is False

    # Unique exact movie match -> auto-pick.
    assert tmdb.is_ambiguous_title(
        "Dune", [_cand(1, "Dune", "2021")]) is False
    # Unique exact SHOW match -> always ask: the user may have meant a film
    # of the same name (e.g. "Fargo").
    assert tmdb.is_ambiguous_title(
        "Fargo", [_cand(1, "Fargo", "2014", "Series")]) is True
    # Two remakes -> ask.
    assert tmdb.is_ambiguous_title("Dune", [
        _cand(1, "Dune", "1984"), _cand(2, "Dune", "2021")]) is True
    # A single fuzzy (non-exact) match still needs confirming.
    assert tmdb.is_ambiguous_title(
        "Dun", [_cand(1, "Dune", "2021")]) is True
    # A movie and a show sharing a name -> ask.
    assert tmdb.is_ambiguous_title("Silo", [
        _cand(1, "Silo", "2023", "Series"), _cand(2, "Silo", "2011")]) is True


def test_candidate_ranking_prefers_exact_then_popularity():
    cands = [
        {"tmdb_id": 1, "type": "Movie", "title": "Dune: Part Two",
         "original_title": "Dune: Part Two", "year": "2024", "popularity": 90},
        {"tmdb_id": 2, "type": "Movie", "title": "Dune", "original_title": "Dune",
         "year": "2021", "popularity": 95},
        {"tmdb_id": 3, "type": "Series", "title": "Dune", "original_title": "Dune",
         "year": "2000", "popularity": 80},
    ]
    ranked = tmdb._rank_watch_candidates("Dune", cands, limit=5)
    # The two exact "Dune" titles come first, most popular first among them.
    assert [c["tmdb_id"] for c in ranked] == [2, 3, 1]
    # limit is honoured.
    assert len(tmdb._rank_watch_candidates("Dune", cands, limit=1)) == 1


# ------------------------------------------------------------------ #
#  3. Storage + capacity                                              #
# ------------------------------------------------------------------ #

def test_add_stores_full_detail_and_stays_idempotent():
    async def _t():
        users, _ = _install(premium=True)
        added = await um.add_to_watchlist(
            1, "Dune", year="2021", type_="Movie", tmdb_id=438631,
            imdb_id="tt1160419", status="Released", poster_url="https://p/x.jpg")
        assert added is True

        entry = (await um.get_watchlist(1))[0]
        assert entry["title"] == "Dune"
        assert entry["title_key"] == "dune"
        assert entry["year"] == "2021"
        assert entry["type"] == "Movie"
        assert entry["tmdb_id"] == 438631
        assert entry["imdb_id"] == "tt1160419"
        assert entry["status"] == "Released"
        assert entry["status_checked_at"] is not None
        # Same title again -> no duplicate (and no second user document).
        assert await um.add_to_watchlist(1, "dune", tmdb_id=438631) is False
        assert len(await um.get_watchlist(1)) == 1
        assert len(users.docs) == 1
    run(_t())


def test_add_without_tmdb_stores_no_null_placeholders():
    async def _t():
        _install(premium=True)
        # TMDb-less entry (API down, or a title the DB doesn't know).
        await um.add_to_watchlist(2, "Obscure", tmdb_id=None)
        bare = (await um.get_watchlist(2))[0]
        assert bare["title"] == "Obscure" and bare["tmdb_id"] is None
        assert "imdb_id" not in bare and "status" not in bare
    run(_t())


def test_capacity_free_vs_premium():
    async def _t():
        _install(premium=False)
        try:
            limit, is_premium = await um.watchlist_capacity(5)
            assert (limit, is_premium) == (config.WATCHLIST_FREE_LIMIT, False)
            assert limit == 5

            pm.is_premium_user = AsyncMock(return_value=True)
            limit, is_premium = await um.watchlist_capacity(5)
            assert (limit, is_premium) == (config.WATCHLIST_PREMIUM_LIMIT, True)
            assert limit == 20
        finally:
            _restore_premium()
    run(_t())


def test_capacity_gate_blocks_add_past_free_limit():
    async def _t():
        users, _ = _install(premium=False)
        try:
            # Fill the free cap directly in storage.
            users.docs.append({"user_id": 7, "watchlist": [
                {"title": f"T{i}", "title_key": f"t{i}"} for i in range(5)
            ]})
            # The gate must refuse BEFORE spending a TMDb call.
            real_search = tmdb.search_watch_candidates
            tmdb.search_watch_candidates = AsyncMock(
                side_effect=AssertionError("no TMDb call past the cap"))
            try:
                msg = FakeMessage(7, "/watch New One")
                await wl.cmd_watch(None, msg)
            finally:
                tmdb.search_watch_candidates = real_search
            # Refused with the upgrade hint.
            body = msg.replies[0]["text"]
            assert "Watchlist full" in body, body
            assert "5 of 5" in body, body
            assert "Premium" in body and "20" in body, body
            assert len(await um.get_watchlist(7)) == 5

            # Premium users get the larger cap.
            pm.is_premium_user = AsyncMock(return_value=True)
            msg2 = FakeMessage(7, "/watch New One")
            tmdb.search_watch_candidates = AsyncMock(return_value=[
                _cand(9, "New One", "2026")])
            try:
                await wl.cmd_watch(None, msg2)
            finally:
                tmdb.search_watch_candidates = real_search
            assert len(await um.get_watchlist(7)) == 6, await um.get_watchlist(7)
        finally:
            _restore_premium()
    run(_t())


def test_update_status_patches_only_given_fields():
    async def _t():
        _install(premium=True)
        await um.add_to_watchlist(1, "Silo", year="2023", type_="Series",
                                 tmdb_id=644456, status="Continuing",
                                 seasons=2, episodes=20)
        ok = await um.update_watchlist_status(
            1, "silo", {"status": "Ended", "status_checked_at":
                        datetime.now(timezone.utc)})
        assert ok is True
        entry = (await um.get_watchlist(1))[0]
        assert entry["status"] == "Ended"
        # Untouched fields survive the patch.
        assert entry["seasons"] == 2 and entry["episodes"] == 20
        assert entry["year"] == "2023"
        # A None value never blanks stored data.
        await um.update_watchlist_status(1, "silo", {"status": None})
        assert (await um.get_watchlist(1))[0]["status"] == "Ended"
    run(_t())


# ------------------------------------------------------------------ #
#  4. Floodgate                                                       #
# ------------------------------------------------------------------ #

def test_series_burst_dms_once():
    """A full season dropping at once must produce ONE message per watcher."""
    async def _t():
        users, client = _install(premium=True)
        for uid in (1, 2):
            users.docs.append({"user_id": uid, "watchlist": [
                {"title": "Silo", "title_key": "silo", "tmdb_id": 644456}]})

        # Ten episodes indexed in a burst.
        total = 0
        for ep in range(1, 11):
            total += await um.notify_watchlist({
                "title": "Silo", "tmdb_id": 644456, "season": 1,
                "episode": ep, "channel_id": -100, "message_id": 100 + ep})

        assert total == 2, (total, client.sent)     # one DM per watcher
        assert len(client.sent) == 2
        # The Get button points at the FIRST copy of the burst.
        assert "get_file:-100:101" in str(client.sent[0]["markup"])
    run(_t())


def test_floodgate_is_per_title_not_global():
    async def _t():
        users, client = _install(premium=True)
        users.docs.append({"user_id": 1, "watchlist": [
            {"title": "Silo", "title_key": "silo", "tmdb_id": 644456},
            {"title": "Dune", "title_key": "dune", "tmdb_id": 438631},
        ]})
        assert await um.notify_watchlist(
            {"title": "Silo", "tmdb_id": 644456, "season": 1, "episode": 1,
             "channel_id": -100, "message_id": 1}) == 1
        # A second copy of Silo in the window is suppressed...
        assert await um.notify_watchlist(
            {"title": "Silo", "tmdb_id": 644456, "season": 1, "episode": 2,
             "channel_id": -100, "message_id": 2}) == 0
        # ...but a different title uploaded alongside still notifies.
        assert await um.notify_watchlist(
            {"title": "Dune", "tmdb_id": 438631, "channel_id": -100,
             "message_id": 3}) == 1
        assert len(client.sent) == 2
    run(_t())


def test_cooldown_expires():
    async def _t():
        users, client = _install(premium=True)
        users.docs.append({"user_id": 1, "watchlist": [
            {"title": "Dune", "title_key": "dune", "tmdb_id": 438631}]})
        entry = {"title": "Dune", "tmdb_id": 438631, "channel_id": -100,
                 "message_id": 1}
        assert await um.notify_watchlist(entry) == 1
        # Fast-forward past the window: the next copy notifies again (e.g. a
        # later season landing minutes after the batch).
        real = config.WATCHLIST_NOTIFY_COOLDOWN_SECONDS
        um.WATCHLIST_NOTIFY_COOLDOWN_SECONDS = 0.01
        try:
            time.sleep(0.02)
            entry["message_id"] = 2
            assert await um.notify_watchlist(entry) == 1
        finally:
            um.WATCHLIST_NOTIFY_COOLDOWN_SECONDS = real
        assert len(client.sent) == 2
    run(_t())


def test_failed_dm_does_not_burn_the_window():
    async def _t():
        class FlakyClient:
            def __init__(self):
                self.calls = 0

            async def send_message(self, uid, text, reply_markup=None, **kw):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("telegram down")
                return SimpleNamespace(id=1)

        users = FakeUsersCol()
        flaky = FlakyClient()
        _install(users=users, client=flaky, premium=True)
        users.docs.append({"user_id": 1, "watchlist": [
            {"title": "Dune", "title_key": "dune", "tmdb_id": 438631}]})
        entry = {"title": "Dune", "tmdb_id": 438631, "channel_id": -100,
                 "message_id": 1}
        assert await um.notify_watchlist(entry) == 0   # send raised
        assert await um.notify_watchlist(entry) == 1   # retried, succeeded
    run(_t())


# ------------------------------------------------------------------ #
#  5. Rendering                                                       #
# ------------------------------------------------------------------ #

def test_watchlist_line_format_matches_spec():
    entries = [
        {"title": "Death of a Unicorn", "title_key": "death of a unicorn",
         "type": "Movie", "year": "2026", "status": "Released",
         "imdb_id": "tt1234567"},
        {"title": "Silo", "title_key": "silo", "type": "Series",
         "year": "2023", "status": "Continuing", "seasons": 2, "episodes": 20,
         "tmdb_id": 644456},
        {"title": "Street Fighter", "title_key": "street fighter",
         "type": "Movie", "year": "2026", "status": "In Cinemas"},
    ]
    text = wl.render_watchlist_text(entries)
    lines = [ln for ln in text.splitlines() if ln[:1].isdigit()]
    assert lines[0].startswith("1. <code>Death of a Unicorn</code>: M / 2026 / Released"), lines[0]
    assert "imdb.com/title/tt1234567" in lines[0]
    assert lines[1].startswith("2. <code>Silo</code>: S / 2023 / Continuing"), lines[1]
    assert "2 seasons / 20 eps" in lines[1], lines[1]
    assert lines[2].startswith("3. <code>Street Fighter</code>: M / 2026 / In Cinemas"), lines[2]
    # The empty state still offers the command.
    assert "/watch" in wl.render_watchlist_text([])


def test_watchlist_escapes_html():
    entries = [{"title": "Fast & <Furious>", "title_key": "fast", "type": "Movie",
                "year": "2001", "status": "Released"}]
    text = wl.render_watchlist_text(entries)
    assert "&amp;" in text and "&lt;Furious&gt;" in text
    assert "<Furious>" not in text


def test_watchlist_keyboard_has_update():
    entries = [
        {"title": "A", "title_key": "a"}, {"title": "B", "title_key": "b"},
    ]
    kb = wl.render_watchlist_keyboard(entries, 42)
    data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "watchupd:all:42" in data
    assert "watchupd:one:42:a" in data
    assert "watchupd:one:42:b" in data
    # UPDATE ALL is always the last row.
    assert kb.inline_keyboard[-1][0].callback_data == "watchupd:all:42"
    # An empty list still offers the global refresh.
    assert wl.render_watchlist_keyboard([], 9).inline_keyboard[0][0].callback_data \
        == "watchupd:all:9"


def test_picker_keyboard_and_state():
    cands = [_cand(1, "Dune", "1984"), _cand(2, "Dune", "2021"),
             _cand(3, "Dune: Part Two", "2024")]
    text = wl._render_picker(cands, "Dune")
    assert "Which one did you mean" in text
    assert text.count("<code>") >= 3

    kb = wl._picker_keyboard("tok123", cands)
    data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert data == ["watchpick:tok123:0", "watchpick:tok123:1",
                    "watchpick:tok123:2", "watchpick:tok123:cancel"]


# ------------------------------------------------------------------ #
#  6. /watch flows                                                    #
# ------------------------------------------------------------------ #

def test_watch_unique_match_stores_with_details():
    async def _t():
        _install(premium=True)
        real = tmdb.search_watch_candidates
        tmdb.search_watch_candidates = AsyncMock(
            return_value=[_cand(438631, "Dune", "2021", "Movie", "Released",
                                poster_url="https://p/dune.jpg")])
        try:
            msg = FakeMessage(1, "/watch dune")
            await wl.cmd_watch(None, msg)
        finally:
            tmdb.search_watch_candidates = real
        entry = (await um.get_watchlist(1))[0]
        assert entry["title"] == "Dune" and entry["tmdb_id"] == 438631
        assert entry["status"] == "Released"
        body = msg.edits[-1]["text"]
        assert "Watching" in body and "M / 2021 / Released" in body, body
    run(_t())


def test_watch_ambiguous_shows_picker_instead_of_adding():
    async def _t():
        _install(premium=True)
        cands = [_cand(1, "Dune", "1984"), _cand(2, "Dune", "2021")]
        real = tmdb.search_watch_candidates
        tmdb.search_watch_candidates = AsyncMock(return_value=cands)
        try:
            msg = FakeMessage(1, "/watch dune")
            await wl.cmd_watch(None, msg)
        finally:
            tmdb.search_watch_candidates = real
        # Nothing stored until the user picks.
        assert await um.get_watchlist(1) == []
        body = msg.edits[-1]["text"]
        assert "Which one did you mean" in body
        markup = msg.edits[-1]["reply_markup"]
        data = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert any(d.startswith("watchpick:") and d.endswith(":0") for d in data)
        assert any(d.endswith(":cancel") for d in data)
    run(_t())


def test_watch_no_tmdb_match_still_tracks_title():
    async def _t():
        _install(premium=True)
        real = tmdb.search_watch_candidates
        tmdb.search_watch_candidates = AsyncMock(return_value=[])
        try:
            msg = FakeMessage(1, "/watch Some Obscure Film")
            await wl.cmd_watch(None, msg)
        finally:
            tmdb.search_watch_candidates = real
        entries = await um.get_watchlist(1)
        assert len(entries) == 1 and entries[0]["title"] == "Some Obscure Film"
        # The caveat rides along in the single confirmation edit.
        assert len(msg.edits) == 1, msg.edits
        body = msg.edits[0]["text"]
        assert "No IMDb / TMDb match" in body, body
        assert "title text only" in body, body
        assert "Some Obscure Film" in body, body
    run(_t())


def test_watch_without_title_shows_usage():
    async def _t():
        _install()
        msg = FakeMessage(1, "/watch")
        await wl.cmd_watch(None, msg)
        assert "Usage" in msg.replies[0]["text"] and "&lt;title&gt;" in msg.replies[0]["text"]
    run(_t())


def test_unwatch_removes():
    async def _t():
        _install(premium=True)
        await um.add_to_watchlist(1, "Dune", tmdb_id=438631)
        msg2 = FakeMessage(1, "/unwatch DUNE")
        await wl.cmd_unwatch(None, msg2)
        assert await um.get_watchlist(1) == []
        assert "removed" in msg2.replies[0]["text"]
        # Removing something absent says so rather than claiming success.
        msg3 = FakeMessage(1, "/unwatch DUNE")
        await wl.cmd_unwatch(None, msg3)
        assert "not on your watchlist" in msg3.replies[0]["text"]
    run(_t())


def test_watchlist_command_renders_with_buttons():
    async def _t():
        _install(premium=True)
        await um.add_to_watchlist(1, "Dune", year="2021", type_="Movie",
                                 tmdb_id=438631, status="Released")
        msg = FakeMessage(1, "/watchlist")
        await wl.cmd_watchlist(None, msg)
        body = msg.replies[0]["text"]
        assert "Dune" in body and "Released" in body
        assert "watchupd:all:1" in str(msg.replies[0]["reply_markup"])
        # Empty list replies without buttons rather than erroring.
        msg2 = FakeMessage(2, "/watchlist")
        await wl.cmd_watchlist(None, msg2)
        assert "empty" in msg2.replies[0]["text"]
    run(_t())


# ------------------------------------------------------------------ #
#  7. UPDATE                                                          #
# ------------------------------------------------------------------ #

def test_update_all_refreshes_statuses():
    async def _t():
        _install(premium=True)
        await um.add_to_watchlist(1, "Silo", year="2023", type_="Series",
                                 tmdb_id=644456, status="Continuing",
                                 seasons=2, episodes=20)
        real = tmdb.fetch_title_status
        tmdb.fetch_title_status = AsyncMock(return_value={
            "status": "Ended", "year": "2023", "seasons": 3, "episodes": 30})
        try:
            q = FakeQuery(1)
            await wl.handle_watch_update(None, q, "all", "")
        finally:
            tmdb.fetch_title_status = real
        entry = (await um.get_watchlist(1))[0]
        assert entry["status"] == "Ended"
        assert entry["seasons"] == 3 and entry["episodes"] == 30
        assert entry["status_checked_at"] is not None
    run(_t())


def test_update_one_entry_only():
    async def _t():
        _install(premium=True)
        await um.add_to_watchlist(1, "Silo", type_="Series", tmdb_id=1,
                                 status="Continuing")
        await um.add_to_watchlist(1, "Dune", type_="Movie", tmdb_id=2,
                                 status="Released")
        real = tmdb.fetch_title_status
        tmdb.fetch_title_status = AsyncMock(return_value={"status": "Ended"})
        try:
            await wl.handle_watch_update(None, FakeQuery(1), "one", "silo")
        finally:
            tmdb.fetch_title_status = real
        entries = {e["title_key"]: e for e in await um.get_watchlist(1)}
        assert entries["silo"]["status"] == "Ended"
        assert entries["dune"]["status"] == "Released", "sibling must not change"
    run(_t())


def test_update_skips_entries_without_tmdb_id():
    async def _t():
        _install(premium=True)
        await um.add_to_watchlist(1, "Obscure", tmdb_id=None)
        real = tmdb.fetch_title_status
        called = AsyncMock(return_value={"status": "Released"})
        tmdb.fetch_title_status = called
        try:
            updated = await wl.refresh_watchlist_statuses(1)
        finally:
            tmdb.fetch_title_status = real
        assert updated == 0
        called.assert_not_awaited()
    run(_t())


def test_update_cooldown_blocks_rapid_taps():
    async def _t():
        _install(premium=True)
        await um.add_to_watchlist(1, "Silo", type_="Series", tmdb_id=1,
                                 status="Continuing")
        real = tmdb.fetch_title_status
        tmdb.fetch_title_status = AsyncMock(return_value={"status": "Ended"})
        try:
            q1 = FakeQuery(1)
            await wl.handle_watch_update(None, q1, "all", "")
            assert "Checking" in q1.answers[0]
            # Second tap inside the cooldown is refused without an API call.
            tmdb.fetch_title_status.reset_mock()
            q2 = FakeQuery(1)
            await wl.handle_watch_update(None, q2, "all", "")
            assert any("cooldown" in a for a in q2.answers), q2.answers
            tmdb.fetch_title_status.assert_not_awaited()
        finally:
            tmdb.fetch_title_status = real
    run(_t())


def test_update_rejects_other_users_message():
    async def _t():
        _install()
        q = FakeQuery(5)  # clicked a button whose owner id is 9
        q.data = "watchupd:all:9"
        await wl.handle_watch_update(None, q, "all", "")
        assert any("another user" in a for a in q.answers), q.answers
    run(_t())


# ------------------------------------------------------------------ #
#  Isolation                                                          #
# ------------------------------------------------------------------ #

import pytest


@pytest.fixture(autouse=True)
def _restore_module_state():
    """Snapshot the module-level fakes each test mutates and put them back.

    ``um.users_col``, ``config.client``, ``pm.is_premium_user``,
    ``tmdb.enrich_title`` and the TMDb search/status helpers are module
    attributes, so a test that swaps them leaks into every later test in the
    run. Restoring here keeps this file order-independent and stops it from
    destabilising unrelated modules.
    """
    import features.callbacks as cb
    saved = (um.users_col, getattr(config, "client", None),
             pm.is_premium_user, tmdb.enrich_title,
             tmdb.search_watch_candidates, tmdb.fetch_title_status,
             um.WATCHLIST_NOTIFY_COOLDOWN_SECONDS,
             cb.should_process_command_for_user, cb.has_accepted_terms,
             cb.is_admin, dict(config.bulk_downloads))
    try:
        yield
    finally:
        (um.users_col, config.client, pm.is_premium_user, tmdb.enrich_title,
         tmdb.search_watch_candidates, tmdb.fetch_title_status,
         um.WATCHLIST_NOTIFY_COOLDOWN_SECONDS) = saved[:7]
        (cb.should_process_command_for_user, cb.has_accepted_terms,
         cb.is_admin) = saved[7:10]
        config.bulk_downloads.clear()
        config.bulk_downloads.update(saved[10])


# ------------------------------------------------------------------ #
#  8. Callback routing (through the real callback_handler)            #
# ------------------------------------------------------------------ #

class FakeQueryWithMessage:
    """CallbackQuery stand-in whose .message supports edit_text."""

    def __init__(self, data, user_id=1):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage(user_id)
        self.answers = []

    async def answer(self, text="", show_alert=False, **kwargs):
        self.answers.append(text)


def _allow_callbacks():
    """Bypass the router's access-control gate for a callback test."""
    import features.callbacks as cb
    cb.should_process_command_for_user = AsyncMock(return_value=True)
    cb.has_accepted_terms = AsyncMock(return_value=True)
    cb.is_admin = AsyncMock(return_value=False)


def test_picker_button_adds_through_router():
    async def _t():
        import features.callbacks as cb
        _install(premium=True)
        _allow_callbacks()
        real = tmdb.search_watch_candidates
        tmdb.search_watch_candidates = AsyncMock(return_value=[
            _cand(1, "Dune", "1984"), _cand(2, "Dune", "2021")])
        try:
            await wl.cmd_watch(None, FakeMessage(1, "/watch dune"))
        finally:
            tmdb.search_watch_candidates = real
        token = next(k for k, v in config.bulk_downloads.items()
                     if v.get("type") == "watch_pick")

        q = FakeQueryWithMessage(f"watchpick:{token}:1")
        await cb.callback_handler(None, q)
        assert any("Added" in a for a in q.answers), q.answers
        entry = (await um.get_watchlist(1))[0]
        assert (entry["title"], entry["year"]) == ("Dune", "2021")
        # The token is consumed, so the button can't be pressed twice.
        assert token not in config.bulk_downloads
    run(_t())


def test_picker_cancel_via_router():
    async def _t():
        import features.callbacks as cb
        _install(premium=True)
        _allow_callbacks()
        real = tmdb.search_watch_candidates
        tmdb.search_watch_candidates = AsyncMock(return_value=[
            _cand(1, "Dune", "1984"), _cand(2, "Dune", "2021")])
        try:
            await wl.cmd_watch(None, FakeMessage(1, "/watch dune"))
        finally:
            tmdb.search_watch_candidates = real
        token = next(k for k, v in config.bulk_downloads.items()
                     if v.get("type") == "watch_pick")

        q = FakeQueryWithMessage(f"watchpick:{token}:cancel")
        await cb.callback_handler(None, q)
        assert any("Cancelled" in a for a in q.answers), q.answers
        assert await um.get_watchlist(1) == []
        assert token not in config.bulk_downloads
    run(_t())


def test_picker_expired_token_is_refused():
    async def _t():
        import features.callbacks as cb
        _install(premium=True)
        _allow_callbacks()
        q = FakeQueryWithMessage("watchpick:doesnotexist:0")
        await cb.callback_handler(None, q)
        assert any("expired" in a for a in q.answers), q.answers
    run(_t())


def test_picker_rejects_other_users_pick():
    async def _t():
        import features.callbacks as cb
        _install(premium=True)
        _allow_callbacks()
        config.bulk_downloads["someoneelses"] = {
            "type": "watch_pick", "user_id": 99, "query": "x",
            "candidates": [_cand(3, "Other", "2020")]}
        try:
            q = FakeQueryWithMessage("watchpick:someoneelses:0")
            await cb.callback_handler(None, q)
            assert any("another user" in a for a in q.answers), q.answers
            assert await um.get_watchlist(1) == []
        finally:
            config.bulk_downloads.pop("someoneelses", None)
    run(_t())


def test_update_button_works_through_router():
    async def _t():
        import features.callbacks as cb
        _install(premium=True)
        _allow_callbacks()
        await um.add_to_watchlist(1, "Silo", year="2023", type_="Series",
                                 tmdb_id=644456, status="Continuing",
                                 seasons=2, episodes=20)
        real = tmdb.fetch_title_status
        tmdb.fetch_title_status = AsyncMock(
            return_value={"status": "Ended", "year": "2023",
                          "seasons": 3, "episodes": 30})
        try:
            q = FakeQueryWithMessage("watchupd:one:1:silo")
            await cb.callback_handler(None, q)
        finally:
            tmdb.fetch_title_status = real
        entry = (await um.get_watchlist(1))[0]
        assert entry["status"] == "Ended"
        assert entry["seasons"] == 3 and entry["episodes"] == 30
    run(_t())


def test_update_button_ownership_enforced_by_router():
    async def _t():
        import features.callbacks as cb
        _install(premium=True)
        _allow_callbacks()
        real = tmdb.fetch_title_status
        tmdb.fetch_title_status = AsyncMock(return_value={"status": "Ended"})
        try:
            # Clicker is user 1, but the button belongs to user 77.
            q = FakeQueryWithMessage("watchupd:all:77", user_id=1)
            await cb.callback_handler(None, q)
            assert any("another user" in a for a in q.answers), q.answers
            tmdb.fetch_title_status.assert_not_awaited()
        finally:
            tmdb.fetch_title_status = real
    run(_t())


def test_router_covers_both_watch_callback_prefixes():
    """Guard against a future edit dropping one of the two entry points."""
    import inspect
    import features.callbacks as cb
    src = inspect.getsource(cb.callback_handler)
    assert 'data.startswith("watchpick:")' in src
    assert 'data.startswith("watchupd:")' in src


_TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


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
