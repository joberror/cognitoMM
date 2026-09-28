#!/usr/bin/env python3
"""
Test: premium monetization (Telegram Stars, expiry reminders, download quota).

Pins cluster 8:

1. Plan config parsing + plan keyboard/text (features/config.py,
   features/premium_payments.py).
2. Stars invoice flow: payload build/parse, send_premium_invoice (enabled /
   disabled / unknown plan), pre-checkout validation, successful_payment
   activation incl. idempotency per charge id.
3. Tier-based daily download quota (features/premium_management.py):
   free cap enforced, premium unlimited, day rollover, fail-open on DB error.
4. Premium expiry reminders: 3d/1d thresholds, once per threshold, no burst
   for a user already inside a smaller window, expired users skipped.

All DB/Telegram access runs against injected fakes - no live services.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import features.config as config
import features.premium_management as premium_management
import features.premium_payments as premium_payments


# ------------------------------------------------------------------ #
# Fakes                                                               #
# ------------------------------------------------------------------ #

def _matches(doc, query):
    for k, v in (query or {}).items():
        if doc.get(k) != v:
            return False
    return True


class FakeUsersCol:
    def __init__(self, doc=None):
        self.doc = dict(doc) if doc else None

    async def find_one(self, query, **kwargs):
        if self.doc and _matches(self.doc, query):
            return dict(self.doc)
        return None

    async def update_one(self, query, update, upsert=False):
        if self.doc is None:
            self.doc = {}
        for k, v in (update.get("$set") or {}).items():
            self.doc[k] = v
        return SimpleNamespace(matched_count=1, modified_count=1)


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

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

    async def update_one(self, query, update, upsert=False):
        for d in self.docs:
            if _matches(d, query):
                for k, v in (update.get("$set") or {}).items():
                    d[k] = v
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)


class FakePaymentsCol:
    def __init__(self):
        self.docs = []

    async def find_one(self, query, **kwargs):
        for d in self.docs:
            if _matches(d, query):
                return dict(d)
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=len(self.docs))


class FakeClient:
    def __init__(self):
        self.invoices = []
        self.messages = []
        self.pre_checkouts = []

    async def send_invoice(self, **kwargs):
        self.invoices.append(kwargs)
        return SimpleNamespace(id=1)

    async def send_message(self, uid, text, **kwargs):
        self.messages.append({"uid": uid, "text": text})
        return SimpleNamespace(id=1)

    async def answer_pre_checkout_query(self, query_id, ok, error_message=None):
        self.pre_checkouts.append({"id": query_id, "ok": ok, "error": error_message})
        return True


class FakePaymentMessage:
    def __init__(self, payload, user_id=555, charge_id="chg_1", username="bob"):
        self.successful_payment = SimpleNamespace(
            invoice_payload=payload,
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id="prov_1",
        )
        self.from_user = SimpleNamespace(id=user_id, username=username)
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)
        return SimpleNamespace(id=1)


def run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        loop = asyncio.new_event_loop()
    return loop.run_until_complete(coro)


# ------------------------------------------------------------------ #
# 1. Plans                                                            #
# ------------------------------------------------------------------ #

def test_parse_premium_plans():
    plans = config._parse_premium_plans("1m:30:50, 3m:90:120,bad,0m:0:5,x:y:z")
    assert set(plans) == {"1m", "3m"}, plans
    assert plans["1m"] == {"key": "1m", "days": 30, "stars": 50}, plans
    assert plans["3m"]["stars"] == 120, plans


def test_plans_keyboard_and_text():
    saved = config.PREMIUM_PLANS
    config.PREMIUM_PLANS = {"1m": {"key": "1m", "days": 30, "stars": 50}}
    premium_payments.PREMIUM_PLANS = config.PREMIUM_PLANS
    try:
        kb = premium_payments.build_plans_keyboard()
        assert kb is not None
        assert kb.inline_keyboard[0][0].callback_data == "buyplan:1m"
        assert "30 days" in kb.inline_keyboard[0][0].text
        assert "Premium unlocks" in premium_payments.format_plans_text()
    finally:
        config.PREMIUM_PLANS = saved
        premium_payments.PREMIUM_PLANS = saved


def test_payload_roundtrip():
    payload = premium_payments.build_payment_payload("1m", 42)
    assert payload == "premium:1m:42"
    info = premium_payments.parse_payment_payload(payload)
    assert info and info["user_id"] == 42 and info["plan_key"] == "1m"
    assert premium_payments.parse_payment_payload("garbage") is None
    assert premium_payments.parse_payment_payload("premium:nope:42") is None
    assert premium_payments.parse_payment_payload("premium:1m:notanint") is None


# ------------------------------------------------------------------ #
# 2. Stars invoice flow                                               #
# ------------------------------------------------------------------ #

def test_send_invoice_and_disabled():
    client = FakeClient()
    ok, err = run(premium_payments.send_premium_invoice(client, 42, "1m", user_id=42))
    assert ok, err
    inv = client.invoices[0]
    assert inv["chat_id"] == 42 and inv["currency"] == "XTR"
    assert inv["payload"] == "premium:1m:42"
    assert inv["prices"][0].amount == config.PREMIUM_PLANS["1m"]["stars"]

    saved = premium_payments.PREMIUM_STARS_ENABLED
    premium_payments.PREMIUM_STARS_ENABLED = False
    try:
        assert run(premium_payments.send_premium_invoice(client, 42, "1m"))[0] is False
    finally:
        premium_payments.PREMIUM_STARS_ENABLED = saved
    assert run(premium_payments.send_premium_invoice(client, 42, "nope"))[0] is False


def test_pre_checkout_validation():
    client = FakeClient()
    good = SimpleNamespace(id="q1", invoice_payload="premium:1m:42")
    assert run(premium_payments.handle_pre_checkout(client, good)) is True
    assert client.pre_checkouts[-1]["ok"] is True
    bad = SimpleNamespace(id="q2", invoice_payload="garbage")
    assert run(premium_payments.handle_pre_checkout(client, bad)) is False
    assert client.pre_checkouts[-1]["ok"] is False


def test_successful_payment_activates_and_is_idempotent():
    saved_col = premium_payments.premium_payments_col
    saved_add = premium_payments.add_premium_user
    saved_log = premium_payments.log_action
    premium_payments.premium_payments_col = FakePaymentsCol()
    premium_payments.add_premium_user = AsyncMock(return_value=(True, "ok"))
    premium_payments.log_action = AsyncMock()
    try:
        client = FakeClient()
        msg = FakePaymentMessage("premium:1m:555", user_id=555)
        run(premium_payments.handle_successful_payment(client, msg))
        premium_payments.add_premium_user.assert_awaited_once()
        args, kwargs = premium_payments.add_premium_user.await_args
        assert args[0] == 555 and args[1] == config.PREMIUM_PLANS["1m"]["days"], (args, kwargs)
        assert len(premium_payments.premium_payments_col.docs) == 1
        assert "Premium activated" in msg.replies[0]

        # Replay the same charge id -> no second grant.
        premium_payments.add_premium_user.reset_mock()
        msg2 = FakePaymentMessage("premium:1m:555", user_id=555, charge_id="chg_1")
        run(premium_payments.handle_successful_payment(client, msg2))
        premium_payments.add_premium_user.assert_not_awaited()
        assert "already applied" in msg2.replies[0]
    finally:
        premium_payments.premium_payments_col = saved_col
        premium_payments.add_premium_user = saved_add
        premium_payments.log_action = saved_log


# ------------------------------------------------------------------ #
# 3. Download quota                                                   #
# ------------------------------------------------------------------ #

def test_quota_free_limit_enforced():
    saved_users = premium_management.users_col
    saved_prem = premium_management.is_premium_user
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    premium_management.users_col = FakeUsersCol(
        {"user_id": 1, "download_day": today, "downloads_today": 10})
    premium_management.is_premium_user = AsyncMock(return_value=False)
    try:
        allowed, remaining, limit, msg = run(premium_management.check_download_quota(1))
        assert allowed is False and remaining == 0
        assert limit == config.FREE_DOWNLOAD_DAILY_LIMIT
        assert "Daily download limit" in msg
    finally:
        premium_management.users_col = saved_users
        premium_management.is_premium_user = saved_prem


def test_quota_premium_unlimited():
    saved_users = premium_management.users_col
    saved_prem = premium_management.is_premium_user
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    premium_management.users_col = FakeUsersCol(
        {"user_id": 1, "download_day": today, "downloads_today": 999})
    premium_management.is_premium_user = AsyncMock(return_value=True)
    try:
        allowed, remaining, limit, msg = run(premium_management.check_download_quota(1))
        assert allowed is True and remaining is None and limit == 0 and msg is None
    finally:
        premium_management.users_col = saved_users
        premium_management.is_premium_user = saved_prem


def test_quota_resets_on_new_day():
    saved_users = premium_management.users_col
    saved_prem = premium_management.is_premium_user
    premium_management.users_col = FakeUsersCol(
        {"user_id": 1, "download_day": "2000-01-01", "downloads_today": 999})
    premium_management.is_premium_user = AsyncMock(return_value=False)
    try:
        allowed, remaining, limit, msg = run(premium_management.check_download_quota(1))
        assert allowed is True and remaining == config.FREE_DOWNLOAD_DAILY_LIMIT
    finally:
        premium_management.users_col = saved_users
        premium_management.is_premium_user = saved_prem


def test_quota_fails_open_on_db_error():
    saved_users = premium_management.users_col
    premium_management.users_col = AsyncMock()
    premium_management.users_col.find_one = AsyncMock(side_effect=RuntimeError("db down"))
    try:
        allowed, remaining, limit, msg = run(premium_management.check_download_quota(1))
        assert allowed is True and msg is None
    finally:
        premium_management.users_col = saved_users


def test_record_download_increments_and_resets():
    saved_users = premium_management.users_col
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    premium_management.users_col = FakeUsersCol(
        {"user_id": 1, "download_day": today, "downloads_today": 4})
    try:
        n = run(premium_management.record_download(1))
        assert n == 5 and premium_management.users_col.doc["downloads_today"] == 5
        premium_management.users_col.doc["download_day"] = "2000-01-01"
        n = run(premium_management.record_download(1))
        assert n == 1, n  # rolled over
    finally:
        premium_management.users_col = saved_users


# ------------------------------------------------------------------ #
# 4. Expiry reminders                                                 #
# ------------------------------------------------------------------ #

def test_expiry_warnings_once_per_threshold_and_no_burst():
    saved_col = premium_management.premium_users_col
    saved_client = config.client
    now = datetime(2030, 1, 10, 12, 0, tzinfo=timezone.utc)
    premium_management.premium_users_col = FakePremiumUsersCol([
        # 3 days left -> 3d warning only
        {"user_id": 1, "expiry_date": now + timedelta(days=3)},
        # 8 hours left (0 days floor) -> 1d warning; larger flag set too (no burst)
        {"user_id": 2, "expiry_date": now + timedelta(hours=8)},
        # already expired -> skipped
        {"user_id": 3, "expiry_date": now - timedelta(days=1)},
    ])
    config.client = FakeClient()
    try:
        sent = run(premium_management.warn_expiring_premium(now=now))
        assert sent == 2, sent
        uids = sorted(m["uid"] for m in config.client.messages)
        assert uids == [1, 2], config.client.messages
        # user 2 got only the 1d message (burst suppressed)
        assert len([m for m in config.client.messages if m["uid"] == 2]) == 1

        # Second run: both flagged -> no repeats.
        before = len(config.client.messages)
        sent2 = run(premium_management.warn_expiring_premium(now=now))
        assert sent2 == 0, sent2
        assert len(config.client.messages) == before

        # Flag bookkeeping: user 2 marked warned_3d AND warned_1d.
        d2 = next(d for d in premium_management.premium_users_col.docs
                  if d["user_id"] == 2)
        assert d2.get("warned_1d") is True and d2.get("warned_3d") is True, d2
    finally:
        premium_management.premium_users_col = saved_col
        config.client = saved_client


# ------------------------------------------------------------------ #
# Standalone runner                                                   #
# ------------------------------------------------------------------ #

_TESTS = [
    test_parse_premium_plans,
    test_plans_keyboard_and_text,
    test_payload_roundtrip,
    test_send_invoice_and_disabled,
    test_pre_checkout_validation,
    test_successful_payment_activates_and_is_idempotent,
    test_quota_free_limit_enforced,
    test_quota_premium_unlimited,
    test_quota_resets_on_new_day,
    test_quota_fails_open_on_db_error,
    test_record_download_increments_and_resets,
    test_expiry_warnings_once_per_threshold_and_no_burst,
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
