#!/usr/bin/env python3
"""
Test: admin premium user list (features/premium_management.py).

Pins the /premium -> View Users list:

1. Formatting: code block, one row per user, 10 users per page, page clamp,
   expiry-sorted order.
2. Status buckets: ACTIVE / EXPIRING (<= warn threshold) / EXPIRED, with
   expired entries showing days since lapse, never a negative "days left".
3. Search: case-insensitive username substring, exact user id, no-match note.
4. Callback data: pagination embeds page + query, stays under Telegram's
   64-byte callback_data cap.
5. Enrichment (downloads today, watchlist, paid-vs-granted source) is
   best-effort: a failing users/payments collection does not break the list.

All DB access runs against injected fakes - no live services.
"""

import asyncio
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import features.premium_management as premium_management


NOW = datetime(2030, 1, 10, 12, 0, tzinfo=timezone.utc)


def _matches(doc, query):
    for k, v in (query or {}).items():
        if isinstance(v, dict) and "$in" in v:
            if doc.get(k) not in v["$in"]:
                return False
        elif isinstance(v, dict) and "$regex" in v:
            if not re.search(v["$regex"], str(doc.get(k) or ""), re.IGNORECASE):
                return False
        elif doc.get(k) != v:
            return False
    return True


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, key, direction=-1):
        self._docs.sort(key=lambda d: d.get(key), reverse=(direction == -1))
        return self

    async def to_list(self, length=None):
        return self._docs[:length] if length else list(self._docs)


class FakePremiumUsersCol:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]

    async def find_one(self, query, **kwargs):
        for d in self.docs:
            if _matches(d, query):
                return dict(d)
        return None

    def find(self, query):
        return FakeCursor([d for d in self.docs if _matches(d, query)])


class FakeUsersCol:
    def __init__(self, docs=None, fail=False):
        self.docs = [dict(d) for d in (docs or [])]
        self.fail = fail

    async def find_one(self, query, **kwargs):
        if self.fail:
            raise RuntimeError("db down")
        for d in self.docs:
            if _matches(d, query):
                return dict(d)
        return None

    def find(self, query, projection=None):
        if self.fail:
            raise FakeCursorExploding()
        return FakeCursor([d for d in self.docs if _matches(d, query)])


class FakeCursorExploding(FakeCursor):
    def __init__(self):
        super().__init__([])

    async def to_list(self, length=None):
        raise RuntimeError("db down")


class ExplodingCol:
    def find(self, query):
        raise RuntimeError("db down")

    async def find_one(self, query, **kwargs):
        raise RuntimeError("db down")


def run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        loop = asyncio.new_event_loop()
    return loop.run_until_complete(coro)


def make_doc(user_id, username, days_left):
    expiry = NOW + timedelta(days=days_left)
    return {
        "user_id": user_id,
        "username": username,
        "added_date": NOW - timedelta(days=90),
        "added_by": 7,
        "expiry_date": expiry,
        "last_updated": expiry,
        "last_updated_by": 7,
    }


def patch_cols(premium_docs, users=None, payments_fail=False, premium_col=None):
    saved = {
        "premium_users_col": premium_management.premium_users_col,
        "users_col": premium_management.users_col,
        "payments_col": getattr(premium_management, "premium_payments_col", None),
    }
    premium_management.premium_users_col = premium_col or FakePremiumUsersCol(premium_docs)
    premium_management.users_col = users if users is not None else FakeUsersCol()
    if payments_fail:
        premium_management.premium_payments_col = ExplodingCol()
    return saved


def restore_cols(saved):
    premium_management.premium_users_col = saved["premium_users_col"]
    premium_management.users_col = saved["users_col"]
    if saved["payments_col"] is not None:
        premium_management.premium_payments_col = saved["payments_col"]


# ------------------------------------------------------------------ #
# 1. Formatting + pagination                                          #
# ------------------------------------------------------------------ #

def test_list_empty():
    saved = patch_cols([])
    try:
        text, keyboard = run(
            premium_management.build_premium_user_list(NOW, page=1, query=None))
        assert "No premium users" in text
        assert keyboard.inline_keyboard[0][0].callback_data == "premium:back"
    finally:
        restore_cols(saved)


def test_list_page_size_and_order():
    docs = [make_doc(1000 + i, f"user{i}", days_left=i) for i in range(1, 26)]
    saved = patch_cols(docs)
    try:
        text, kb = run(premium_management.build_premium_user_list(NOW, page=1, query=None))
        # code block formatting
        assert text.startswith("```") and text.rstrip().endswith("```"), text[:60]
        # 10 users on page 1
        rows = [ln for ln in text.splitlines() if ln.startswith("#")]
        assert len(rows) == 10, len(rows)
        # sorted by expiry ascending: nearest deadline first (user1, days_left=1)
        assert re.match(r"#1\s.*user1\b", rows[0]), rows[0]
        # numbering is global across pages
        text2, _ = run(premium_management.build_premium_user_list(NOW, page=3, query=None))
        rows2 = [ln for ln in text2.splitlines() if ln.startswith("#")]
        assert len(rows2) == 5 and rows2[0].startswith("#21"), rows2
        # header shows totals + page position
        assert "Page 1/3" in text and "Total: 25" in text, text
    finally:
        restore_cols(saved)


def test_list_page_clamp_and_nav_buttons():
    docs = [make_doc(1000 + i, f"user{i}", days_left=i) for i in range(1, 26)]
    saved = patch_cols(docs)
    try:
        # Page 1: no prev, next targets page 2.
        _, kb1 = run(premium_management.build_premium_user_list(NOW, page=1, query=None))
        d1 = [b.callback_data for row in kb1.inline_keyboard for b in row]
        assert not any((b or "").startswith("plist:prev") for b in d1), d1
        assert "plist:next:2" in d1, d1

        # Way past the end: clamped to the last page, no next, prev targets 2.
        text, kb = run(premium_management.build_premium_user_list(NOW, page=99, query=None))
        assert "Page 3/3" in text, text
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert not any((b or "").startswith("plist:next") for b in datas), datas
        assert "plist:prev:2" in datas, datas
        assert any(b == "plist:search" for b in datas), datas
        assert any(b == "premium:back" for b in datas), datas

        # Middle page has both nav buttons, targeting neighbours.
        _, kb2 = run(premium_management.build_premium_user_list(NOW, page=2, query=None))
        datas2 = [b.callback_data for row in kb2.inline_keyboard for b in row]
        assert "plist:prev:1" in datas2 and "plist:next:3" in datas2, datas2
    finally:
        restore_cols(saved)


# ------------------------------------------------------------------ #
# 2. Status buckets                                                   #
# ------------------------------------------------------------------ #

def test_status_buckets():
    docs = [
        make_doc(1, "alice", 4),      # ACTIVE
        make_doc(2, "bob", 3),        # EXPIRING (boundary)
        make_doc(3, "carol", 1),      # EXPIRING
        make_doc(4, "dave", -5),      # EXPIRED
    ]
    saved = patch_cols(docs)
    try:
        text, _ = run(premium_management.build_premium_user_list(NOW, page=1, query=None))
        lines = {u: ln for ln in text.splitlines()
                 for u in ("alice", "bob", "carol", "dave") if u in ln}
        assert "ACTIVE" in lines["alice"], lines["alice"]
        assert "EXPIRING" in lines["bob"], lines["bob"]
        assert "EXPIRING" in lines["carol"], lines["carol"]
        assert "EXPIRED" in lines["dave"], lines["dave"]
        # expired never shows negative days left
        assert "-5" not in lines["dave"] and "5d" in lines["dave"], lines["dave"]
        # summary counts
        assert "Active: 3" in text and "Expired: 1" in text and "Expiring: 2" in text, text
    finally:
        restore_cols(saved)


# ------------------------------------------------------------------ #
# 3. Search                                                           #
# ------------------------------------------------------------------ #

def test_search_by_username_and_id():
    docs = [make_doc(1, "alice", 4), make_doc(2, "BOB", 10), make_doc(3, "carol", 2)]
    saved = patch_cols(docs)
    try:
        text, _ = run(premium_management.build_premium_user_list(NOW, page=1, query="b"))
        rows = [ln for ln in text.splitlines() if ln.startswith("#")]
        assert len(rows) == 1 and "BOB" in rows[0], rows  # case-insensitive substring
        assert 'Filter: "b"' in text, text

        text2, _ = run(premium_management.build_premium_user_list(NOW, page=1, query=" 1 "))
        rows2 = [ln for ln in text2.splitlines() if ln.startswith("#")]
        assert len(rows2) == 1 and "alice" in rows2[0], rows2  # exact id

        kb = run(premium_management.build_premium_user_list(NOW, page=1, query="b"))[1]
        datas = [bb.callback_data for row in kb.inline_keyboard for bb in row]
        assert any((d or "").startswith("plist:clear") for d in datas), datas

        text3, _ = run(premium_management.build_premium_user_list(NOW, page=1, query="zzz"))
        assert "No premium users match" in text3, text3
    finally:
        restore_cols(saved)


# ------------------------------------------------------------------ #
# 4. Callback data size                                               #
# ------------------------------------------------------------------ #

def test_callback_data_under_limit():
    docs = [make_doc(123456789012, "u", 4)]
    saved = patch_cols(docs)
    try:
        _, kb = run(premium_management.build_premium_user_list(
            NOW, page=2, query="verylongusername"))
        for row in kb.inline_keyboard:
            for b in row:
                d = b.callback_data or ""
                assert len(d.encode("utf-8")) <= 64, d
        # action buttons key on the real user id
        _, kb2 = run(premium_management.build_premium_user_list(NOW, page=1, query=None))
        datas = [b.callback_data for row in kb2.inline_keyboard for b in row]
        assert any(d == "plist:edit:123456789012" for d in datas), datas
    finally:
        restore_cols(saved)


# ------------------------------------------------------------------ #
# 5. Enrichment is best-effort                                        #
# ------------------------------------------------------------------ #

def test_enrichment_failure_does_not_break_list():
    docs = [make_doc(1, "alice", 4)]
    saved = patch_cols(docs, users=ExplodingCol(), payments_fail=True)
    try:
        text, _ = run(premium_management.build_premium_user_list(NOW, page=1, query=None))
        assert "alice" in text  # still renders
    finally:
        restore_cols(saved)


def test_enrichment_shows_usage_and_source():
    today = NOW.strftime("%Y-%m-%d")
    docs = [make_doc(1, "alice", 4)]
    users = FakeUsersCol([{"user_id": 1, "download_day": today,
                           "downloads_today": 3,
                           "watchlist": [{"title_key": "x"}]}])
    saved = patch_cols(docs, users=users)
    saved_p = getattr(premium_management, "premium_payments_col", None)
    premium_management.premium_payments_col = FakePremiumUsersCol(
        [{"user_id": 1, "stars": 50, "plan_key": "1m", "charge_id": "c1"}])
    try:
        text, _ = run(premium_management.build_premium_user_list(NOW, page=1, query=None))
        assert "DL: 3" in text, text
        assert "WL: 1" in text, text
        assert "paid 50XTR" in text, text

        # no payment record -> admin grant
        premium_management.premium_payments_col = FakePremiumUsersCol([])
        text2, _ = run(premium_management.build_premium_user_list(NOW, page=1, query=None))
        assert "grant" in text2.lower(), text2
    finally:
        premium_management.premium_payments_col = saved_p
        restore_cols(saved)


def test_enrichment_is_batched_per_page():
    # ONE users_col.find + ONE payments find per page, never per row.
    docs = [make_doc(1000 + i, f"user{i}", i) for i in range(1, 11)]
    users = FakeUsersCol([{"user_id": 1001, "download_day": NOW.strftime("%Y-%m-%d"),
                           "downloads_today": 2}])
    calls = {"users": 0, "pay": 0}
    orig_users_find = users.find
    orig_prem_find = None

    def counting_users_find(*a, **k):
        calls["users"] += 1
        return orig_users_find(*a, **k)

    users.find = counting_users_find
    saved = patch_cols(docs, users=users)
    pay_col = FakePremiumUsersCol([])
    orig_prem_find = pay_col.find

    def counting_pay_find(*a, **k):
        calls["pay"] += 1
        return orig_prem_find(*a, **k)

    pay_col.find = counting_pay_find
    saved_p = getattr(premium_management, "premium_payments_col", None)
    premium_management.premium_payments_col = pay_col
    try:
        run(premium_management.build_premium_user_list(NOW, page=1, query=None))
        assert calls["users"] == 1, calls
        assert calls["pay"] == 1, calls
    finally:
        premium_management.premium_payments_col = saved_p
        restore_cols(saved)


def test_query_colons_cannot_break_callback_parsing():
    # A typed filter with ":" is stripped, so "plist:next:<page>:<query>"
    # always splits into at most 4 parts for the callback handler.
    docs = [make_doc(1, "alice", 4), make_doc(2, "bob", 9)]
    saved = patch_cols(docs)
    try:
        text, kb = run(premium_management.build_premium_user_list(
            NOW, page=1, query="bob:1"))
        for row in kb.inline_keyboard:
            for b in row:
                d = b.callback_data or ""
                assert len(d.split(":")) <= 4, d
        assert text  # list still renders
    finally:
        restore_cols(saved)


def test_premium_list_page_and_query_helpers():
    assert premium_management._clean_list_query(None) is None
    assert premium_management._clean_list_query("") is None
    assert premium_management._clean_list_query("  bob  ") == "bob"
    assert premium_management._clean_list_query("a:b") == "ab"
    assert premium_management._clean_list_query("x" * 99) == "x" * 24
    # Multibyte caps count UTF-8 bytes, not chars (callback_data is byte-capped).
    assert len(premium_management._clean_list_query("é" * 99).encode("utf-8")) == 24
    assert premium_management._list_query_token(None) == ""
    assert premium_management._list_query_token("bob") == ":bob"


def test_callback_data_under_64_bytes_with_long_query():
    # Multibyte query: cap is 24 UTF-8 bytes; worst realistic nav callback
    # "plist:next:<3-digit page>:<query>" must stay <= 64 bytes.
    saved = patch_cols([])  # just for the _clean_list_query helper
    try:
        emoji_q = "🔎" * 20                      # raw 80 bytes
        clean = premium_management._clean_list_query(emoji_q)
        assert len(clean.encode("utf-8")) == 24
        assert len(f"plist:next:100:{clean}".encode("utf-8")) <= 64
    finally:
        restore_cols(saved)

    # Filtered list where rows actually match: nav buttons must be valid.
    name_q = premium_management._clean_list_query("🔎" * 20)  # 8 emojis
    docs = [make_doc(1000 + i, f"u{name_q}", i) for i in range(1, 13)]
    saved = patch_cols(docs)
    try:
        _, kb = run(premium_management.build_premium_user_list(
            NOW, page=2, query="🔎" * 20))
        nav = [b.callback_data for row in kb.inline_keyboard for b in row
               if (b.callback_data or "").startswith(("plist:prev", "plist:next"))]
        assert nav, "page 2 of a 2-page filtered list should have nav buttons"
        for d in nav:
            assert len(d.encode("utf-8")) <= 64, (d, len(d.encode("utf-8")))
    finally:
        restore_cols(saved)


def test_search_handler_filters_list():
    import features.premium_commands as premium_commands
    docs = [make_doc(1, "alice", 4), make_doc(2, "bob", 9)]
    saved = patch_cols(docs)
    saved_admin = premium_commands.is_admin
    premium_commands.is_admin = AsyncMock(return_value=True)
    replies = []

    class Msg:
        class from_user:
            id = 7
        chat = SimpleNamespace(id=7)
        text = "@bob"
        async def reply_text(self, t, **kw):
            replies.append(t)
            return SimpleNamespace(id=1)

    try:
        run(premium_commands.handle_premium_list_search(Msg()))
        assert len(replies) == 1
        assert "bob" in replies[0] and "alice" not in replies[0], replies[0]
        assert 'Filter: "bob"' in replies[0]
    finally:
        premium_commands.is_admin = saved_admin
        restore_cols(saved)


# ------------------------------------------------------------------ #
# Standalone runner                                                   #
# ------------------------------------------------------------------ #

_TESTS = [
    test_list_empty,
    test_list_page_size_and_order,
    test_list_page_clamp_and_nav_buttons,
    test_status_buckets,
    test_search_by_username_and_id,
    test_callback_data_under_limit,
    test_enrichment_failure_does_not_break_list,
    test_enrichment_shows_usage_and_source,
    test_enrichment_is_batched_per_page,
    test_query_colons_cannot_break_callback_parsing,
    test_premium_list_page_and_query_helpers,
    test_callback_data_under_64_bytes_with_long_query,
    test_search_handler_filters_list,
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
