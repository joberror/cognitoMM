"""
Tests for the unified /user dashboard.

Covers the three moving parts:
  1. admin == premium (features/premium_management.is_premium_user): a config
     Super Admin short-circuits, a DB-role admin gets the premium tier, and a
     paying premium user still costs exactly one read.
  2. the shared resolve -> apply helpers (features/user_management): the
     target guards, the preview verdicts and the re-check-before-write.
  3. the dashboard itself (features/user_commands): filters, sorting, super
     admin pinning, page size, HTML escaping, the private-chat gate and the
     text aliases routed through the same write path.

No live services: every collection and the Telegram client are fakes, and the
audit log sink is replaced too, so nothing reaches MongoDB or Telegram.
"""

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

# Ensure project root is on the path so the features package is importable
# when this file is run standalone (python tests/test_user_dashboard.py).
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from pyrogram.enums import ChatType
from bson import ObjectId

import features.commands as commands
import features.config as config
import features.premium_management as pm
import features.user_commands as uc
import features.user_management as um


# ------------------------------------------------------------------ #
#  Fakes                                                              #
# ------------------------------------------------------------------ #

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _as_utc(value):
    if value is None or getattr(value, "tzinfo", None) is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _sort_key(value):
    """Mongo-like ordering: missing dates sort lowest."""
    if value is None:
        return (1, _EPOCH)
    return (0, _as_utc(value))


def _geq(left, right) -> bool:
    """Mongo `$gte` for dates AND for ObjectId ranges.

    The Recent window's `_id >= ObjectId(cutoff)` compares two ObjectIds
    (which order by their leading timestamp); everything else is a date.
    """
    if left is None:
        return False
    if hasattr(right, "generation_time"):
        return hasattr(left, "generation_time") and left >= right
    return _as_utc(left) >= _as_utc(right)


def _match(doc, query):
    """Minimal Mongo query matcher for the operators the dashboard uses."""
    for key, cond in (query or {}).items():
        if key == "$or":
            if not any(_match(doc, sub) for sub in cond):
                return False
            continue
        if key == "$and":
            if not all(_match(doc, sub) for sub in cond):
                return False
            continue
        value = doc.get(key)
        if isinstance(cond, dict):
            for op, operand in cond.items():
                if op == "$in":
                    if value not in operand:
                        return False
                elif op == "$nin":
                    if value in operand:
                        return False
                elif op == "$ne":
                    if value == operand:
                        return False
                elif op == "$gt":
                    if value is None or _as_utc(value) <= _as_utc(operand):
                        return False
                elif op == "$lt":
                    if value is None or _as_utc(value) >= _as_utc(operand):
                        return False
                elif op == "$gte":
                    if not _geq(value, operand):
                        return False
                elif op == "$exists":
                    if (value is not None) != bool(operand):
                        return False
                else:
                    raise AssertionError(f"fake collection: unsupported operator {op}")
        elif value != cond:
            return False
    return True


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, key, direction=-1):
        self.docs.sort(key=lambda doc: _sort_key(doc.get(key)), reverse=direction < 0)
        return self

    def skip(self, count):
        self.docs = self.docs[count:]
        return self

    def limit(self, count):
        self.docs = self.docs[:count]
        return self

    async def to_list(self, length=None):
        return [dict(doc) for doc in self.docs]


class FakeUsersCol:
    def __init__(self, docs=()):
        self.docs = [dict(doc) for doc in docs]
        self.writes = []

    def find(self, query=None, projection=None):
        return FakeCursor([doc for doc in self.docs if _match(doc, query)])

    async def find_one(self, query=None, projection=None):
        for doc in self.docs:
            if _match(doc, query):
                return dict(doc)
        return None

    async def count_documents(self, query=None):
        return sum(1 for doc in self.docs if _match(doc, query))

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if _match(doc, query):
                doc.update(update.get("$set", {}))
                self.writes.append((dict(update.get("$set", {}))))
                return SimpleNamespace(modified_count=1)
        if upsert:
            new_doc = {k: v for k, v in (query or {}).items() if not k.startswith("$")}
            new_doc.update(update.get("$set", {}))
            self.docs.append(new_doc)
            self.writes.append((dict(update.get("$set", {}))))
            return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)


class FakePremiumCol:
    def __init__(self, docs=()):
        self.docs = [dict(doc) for doc in docs]

    def find(self, query=None, projection=None):
        return FakeCursor([doc for doc in self.docs if _match(doc, query)])

    async def find_one(self, query=None, projection=None):
        for doc in self.docs:
            if _match(doc, query):
                return dict(doc)
        return None


class FakeLogsCol:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(doc)
        return SimpleNamespace(inserted_id=len(self.docs))


class FakeUser:
    """Stand-in for pyrogram's User (only what the dashboard reads)."""

    def __init__(self, user_id, first_name="User", username=None):
        self.id = user_id
        self.first_name = first_name
        self.username = username


class FakeClient:
    def __init__(self, users=(), fail=False):
        self.users = {user.id: user for user in users}
        self.by_handle = {user.username: user
                          for user in users if user.username}
        self.fail = fail
        self.calls = []

    async def get_users(self, user_ids):
        """Mirrors Telegram: one call resolves the ids AND @handles asked
        for, and the answer comes back without the unresolvable entries."""
        self.calls.append(list(user_ids))
        if self.fail:
            raise RuntimeError("telegram unreachable")
        found = []
        for token in user_ids:
            if isinstance(token, int) and token in self.users:
                found.append(self.users[token])
            elif isinstance(token, str) and token.lstrip("@") in self.by_handle:
                found.append(self.by_handle[token.lstrip("@")])
        return found


class FakeMessage:
    def __init__(self, text="", user_id=42, chat_type=ChatType.PRIVATE, chat_id=None):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(type=chat_type, id=chat_id or user_id)
        self.replies = []
        self.edits = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))
        return SimpleNamespace(id=len(self.replies))

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))
        return SimpleNamespace(id=1)


class FakeCallbackQuery:
    def __init__(self, data, user_id=42, chat_type=ChatType.PRIVATE, chat_id=None,
                 message=None):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = message or FakeMessage(user_id=user_id, chat_type=chat_type,
                                              chat_id=chat_id)
        self.answers = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class Env:
    """Install the fakes into every module that touches the database."""

    def __init__(self, docs=(), premium=(), admins=(), client=None, logs=None):
        self.users = FakeUsersCol(docs)
        self.premium = FakePremiumCol(premium)
        self.logs = logs if logs is not None else FakeLogsCol()
        self.client = client if client is not None else FakeClient()
        self.admins = list(admins)
        self._saved = {}

    def __enter__(self):
        self._saved = {
            "um.users_col": um.users_col,
            "um.ADMINS": um.ADMINS,
            "um.logs_col": um.logs_col,
            "uc.users_col": uc.users_col,
            "uc.premium_users_col": uc.premium_users_col,
            "uc.ADMINS": uc.ADMINS,
            "uc.bulk_downloads": uc.bulk_downloads,
            "pm.premium_users_col": pm.premium_users_col,
            "pm.ADMINS": pm.ADMINS,
            "config.client": config.client,
        }
        um.users_col = self.users
        um.ADMINS = self.admins
        um.logs_col = self.logs
        uc.users_col = self.users
        uc.premium_users_col = self.premium
        uc.ADMINS = self.admins
        uc.bulk_downloads.clear()
        pm.premium_users_col = self.premium
        pm.ADMINS = self.admins  # premium_management holds its own binding
        config.client = None  # keep the audit log off Telegram
        return self

    def __exit__(self, *exc):
        um.users_col = self._saved["um.users_col"]
        um.ADMINS = self._saved["um.ADMINS"]
        um.logs_col = self._saved["um.logs_col"]
        uc.users_col = self._saved["uc.users_col"]
        uc.premium_users_col = self._saved["uc.premium_users_col"]
        uc.ADMINS = self._saved["uc.ADMINS"]
        uc.bulk_downloads.clear()
        pm.premium_users_col = self._saved["pm.premium_users_col"]
        pm.ADMINS = self._saved["pm.ADMINS"]
        config.client = self._saved["config.client"]
        return False


def days_ago(days):
    return datetime.now(timezone.utc) - timedelta(days=days)


def in_days(days):
    return datetime.now(timezone.utc) + timedelta(days=days)


def role_of(env, user_id):
    for doc in env.users.docs:
        if doc.get("user_id") == user_id:
            return doc.get("role", "user")
    return None


def _boom(*args, **kwargs):
    raise AssertionError("no lookup expected")


def list_block(text: str) -> str:
    """The `<pre>` list of a rendered dashboard page."""
    return text.split("<pre>")[1].split("</pre>")[0]


def listed_ids(text: str) -> list:
    """User ids of a rendered page, in display order.

    Read from the `Status · <id> · seen …` meta lines instead of the name
    lines so a page rendered without a live Telegram lookup (no client) still
    asserts on the right rows.
    """
    return re.findall(r"· (\d+) ·", list_block(text))


# ------------------------------------------------------------------ #
#  1. admin == premium                                                 #
# ------------------------------------------------------------------ #


async def test_config_admin_is_premium_without_any_read():
    """A config Super Admin short-circuits: no premium doc, no role read."""
    with Env(admins=[7]) as env:
        env.premium.find = _boom  # any premium read would explode
        env.premium.find_one = _boom
        assert await pm.is_premium_user(7) is True


async def test_db_role_admin_counts_as_premium():
    """A database admin (role=admin) gets the premium tier without a record."""
    with Env(docs=[{"user_id": 5, "role": "admin"}]):
        assert await pm.is_premium_user(5) is True


async def test_premium_user_pays_no_extra_read():
    """An active premium record short-circuits before the admin fallback."""
    with Env(docs=[{"user_id": 5, "role": "user"}],
             premium=[{"user_id": 5, "expiry_date": in_days(10)}]) as env:
        env.users.find = _boom  # the admin fallback must not run
        assert await pm.is_premium_user(5) is True


async def test_expired_premium_and_non_admin_is_free():
    """An expired record falls through to is_admin(), which says no."""
    with Env(docs=[{"user_id": 5, "role": "user"}],
             premium=[{"user_id": 5, "expiry_date": days_ago(2)}]):
        assert await pm.is_premium_user(5) is False


async def test_banned_user_is_not_premium():
    with Env(docs=[{"user_id": 6, "role": "banned"}]):
        assert await pm.is_premium_user(6) is False


# ------------------------------------------------------------------ #
#  2. Shared resolve / apply helpers                                  #
# ------------------------------------------------------------------ #


def test_parse_target_tokens_accepts_ids_and_handles():
    assert um.parse_target_tokens("111, @bob, 222 @carol") == [111, "@bob", 222, "@carol"]
    # Junk is dropped instead of reaching the database or the RPC.
    assert um.parse_target_tokens("???, 12, a!") == [12]
    assert um.parse_target_tokens("") == []


async def test_mixed_comma_parsing_resolves_names_and_roles():
    """`123, @bob` resolves both in ONE batched get_users call."""
    client = FakeClient([FakeUser(123, "Ann", "ann"), FakeUser(777, "Bob", "bob")])
    with Env(docs=[{"user_id": 777, "role": "admin"}], client=client):
        records = await um.resolve_targets(client, "123, @bob", actor_id=1)
    assert len(client.calls) == 1, "resolve must use a single batched lookup"
    assert [rec["id"] for rec in records] == [123, 777]
    assert records[0]["first_name"] == "Ann"
    assert records[1]["role"] == "admin"
    assert all(rec["verdict"] is None for rec in records)


async def test_preview_verdicts_cover_every_guard():
    """Super admin, yourself, not found, already banned and demote-first."""
    client = FakeClient([FakeUser(10), FakeUser(11), FakeUser(12), FakeUser(13)])
    with Env(docs=[
        {"user_id": 10, "role": "user"},
        {"user_id": 11, "role": "banned"},
        {"user_id": 12, "role": "admin"},
    ], admins=[99], client=client):
        records = await um.resolve_targets(
            client, "10, 99, 11, 12, @ghostuser, 13",
            actor_id=13, guard_action="ban_user")
    verdicts = {rec["input"]: rec["verdict"] for rec in records}
    assert verdicts["10"] is None
    assert verdicts["99"] == um.VERDICT_SUPER_ADMIN
    assert verdicts["13"] == um.VERDICT_SELF
    assert verdicts["11"] == um.VERDICT_BANNED_NOOP
    assert verdicts["12"] == um.VERDICT_DEMOTE_FIRST
    assert verdicts["@ghostuser"] == um.VERDICT_NOT_FOUND


async def test_promoting_a_banned_user_is_blocked():
    client = FakeClient([FakeUser(11)])
    with Env(docs=[{"user_id": 11, "role": "banned"}], admins=[1], client=client):
        records = await um.resolve_targets(client, "11", actor_id=1, guard_action="promote")
        assert records[0]["verdict"] == um.VERDICT_UNBAN_FIRST
        summary = await um.apply_role_action(1, "promote", records)
    assert summary["applied"] == []
    assert summary["skipped"][0][1] == um.VERDICT_UNBAN_FIRST


async def test_ban_requires_demote_first():
    """(c) a DB-role admin must be demoted before they can be banned."""
    with Env(docs=[{"user_id": 12, "role": "admin"}], admins=[1]):
        summary = await um.apply_role_action(1, "ban_user",
                                             [{"id": 12, "verdict": None}], via="test")
        assert summary["applied"] == []
        assert summary["skipped"][0][1] == um.VERDICT_DEMOTE_FIRST


async def test_demote_then_ban_two_step():
    """The two-step demote -> ban path, ending back on `user` after an unban."""
    with Env(docs=[{"user_id": 12, "role": "admin"}], admins=[1]) as env:
        demote = await um.apply_role_action(1, "demote", [{"id": 12, "verdict": None}])
        assert demote["applied"] == [12]
        assert role_of(env, 12) == "user"
        ban = await um.apply_role_action(1, "ban_user", [{"id": 12, "verdict": None}])
        assert ban["applied"] == [12]
        assert role_of(env, 12) == "banned"
        unban = await um.apply_role_action(1, "unban_user", [{"id": 12, "verdict": None}])
        assert unban["applied"] == [12]
        assert role_of(env, 12) == "user"


async def test_super_admin_only_promote_and_demote():
    """(d) a promoted (DB) admin may not hand out or revoke the role."""
    with Env(docs=[{"user_id": 21, "role": "user"},
                   {"user_id": 30, "role": "admin"}], admins=[]) as env:
        # 21 is a plain user here, so it acts as the acting admin.
        promote = await um.apply_role_action(21, "promote", [{"id": 22, "verdict": None}])
        assert promote["applied"] == []
        assert promote["skipped"][0][1] == um.VERDICT_SUPER_ONLY
        demote = await um.apply_role_action(30, "demote", [{"id": 30, "verdict": None}])
        assert demote["applied"] == []
        assert demote["skipped"][0][1] == um.VERDICT_SUPER_ONLY
        assert role_of(env, 30) == "admin"
        # A config Super Admin may do both.
        env.admins.append(1)
        assert (await um.apply_role_action(1, "demote",
                                           [{"id": 30, "verdict": None}]))["applied"] == [30]


async def test_config_admin_can_never_be_targeted():
    with Env(docs=[{"user_id": 42, "role": "banned"}], admins=[42, 1]) as env:
        for action in ("ban_user", "unban_user", "promote", "demote"):
            summary = await um.apply_role_action(1, action, [{"id": 42, "verdict": None}])
            assert summary["applied"] == [], action
            assert summary["skipped"][0][1] == um.VERDICT_SUPER_ADMIN, action
        assert role_of(env, 42) == "banned"


async def test_guards_are_rechecked_at_execution_time():
    """Preview -> confirm race: the role changed in between, so skip."""
    with Env(docs=[{"user_id": 12, "role": "user"}], admins=[1]) as env:
        previewed = [{"id": 12, "verdict": None}]
        for doc in env.users.docs:  # an admin promotes the target behind our back
            if doc.get("user_id") == 12:
                doc["role"] = "admin"
        summary = await um.apply_role_action(1, "ban_user", previewed)
        assert summary["applied"] == []
        assert summary["skipped"][0][1] == um.VERDICT_DEMOTE_FIRST
        assert role_of(env, 12) == "admin"


async def test_apply_role_action_keeps_log_action_names():
    """/logs keeps rendering promote / demote / ban_user / unban_user."""
    with Env(docs=[{"user_id": 55, "role": "user"}], admins=[1]) as env:
        await um.apply_role_action(1, "ban_user", [{"id": 55, "verdict": None}], via="alias")
    action = env.logs.docs[-1]
    assert action["action"] == "ban_user"
    assert action["by"] == 1 and action["target"] == 55
    assert action["extra"] == {"via": "alias"}


def test_role_summary_and_target_lines():
    summary = {"action": "ban_user", "applied": [1, 2, 3],
               "skipped": [({"id": 4}, um.VERDICT_SELF)]}
    assert um.format_role_summary(summary) == "✅ Banned 3 · ⚠️ 1 skipped"
    assert um.format_role_summary({"action": "demote", "applied": [], "skipped": []}) \
        == "⚠️ Demoted 0"
    assert um.format_role_target_lines([{"id": 4, "verdict": um.VERDICT_SELF}]) \
        == ["4 — ⚠️ You — skipped"]


async def test_lookup_failure_never_blocks_the_admin():
    """A dead get_users keeps numeric ids actionable (names degrade)."""
    client = FakeClient(fail=True)
    with Env(docs=[{"user_id": 5, "role": "user"}], client=client):
        records = await um.resolve_targets(client, "5, @ghostuser", actor_id=1)
    by_input = {rec["input"]: rec for rec in records}
    assert by_input["5"]["id"] == 5 and by_input["5"]["verdict"] is None
    assert by_input["@ghostuser"]["verdict"] == um.VERDICT_NOT_FOUND


# ------------------------------------------------------------------ #
#  3. Dashboard rendering                                             #
# ------------------------------------------------------------------ #


async def test_domain_split_keeps_cmd_user_in_its_own_module():
    import features.user_commands as user_commands
    assert commands.cmd_user is user_commands.cmd_user


async def test_dashboard_is_private_and_admin_only():
    with Env(admins=[1]):
        group_msg = FakeMessage("/user", user_id=1, chat_type=ChatType.SUPERGROUP)
        await uc.cmd_user(None, group_msg)
        assert "private" in group_msg.replies[0][0].lower()
        assert not group_msg.replies[0][1].get("reply_markup")

        stranger = FakeMessage("/user", user_id=777)
        await uc.cmd_user(None, stranger)
        assert "Admins only" in stranger.replies[0][0]

        allowed = FakeMessage("/user", user_id=1)
        await uc.cmd_user(None, allowed)
        assert "User manager" in allowed.replies[0][0]


async def test_can_use_dashboard_gate():
    with Env(docs=[{"user_id": 30, "role": "admin"}], admins=[1]):
        assert await uc.can_use_dashboard(1, ChatType.PRIVATE) is True
        assert await uc.can_use_dashboard(30, ChatType.PRIVATE) is True  # DB admin
        assert await uc.can_use_dashboard(30, ChatType.SUPERGROUP) is False
        assert await uc.can_use_dashboard(99, ChatType.PRIVATE) is False
        # promote/demote need a config Super Admin, re-checked on every press.
        assert await uc.can_use_dashboard(1, ChatType.PRIVATE, "promote") is True
        assert await uc.can_use_dashboard(30, ChatType.PRIVATE, "promote") is False
        assert await uc.can_use_dashboard(30, ChatType.PRIVATE, "ban_user") is True


async def test_status_column_precedence():
    premium = {5, 11}
    rows = [
        {"user_id": 99, "role": "user"},                 # config admin
        {"user_id": 1, "role": "admin"},                 # db admin
        {"user_id": 11, "role": "banned"},               # banned + premium
        {"user_id": 12, "role": "banned"},               # banned
        {"user_id": 5, "role": "user"},                  # premium
        {"user_id": 6, "role": "user"},                  # free
    ]
    with Env(admins=[99]):
        labels = [uc.status_label(row, premium) for row in rows]
    assert labels == ["👑 Super Admin", "Admin", "Banned ⭐", "Banned",
                      "⭐ Premium", "Free"]


async def test_page_size_is_ten_and_super_admins_pin_page_one():
    now = datetime.now(timezone.utc)
    docs = [{"user_id": i, "last_seen": now - timedelta(minutes=i), "role": "user"}
            for i in range(1, 26)]
    client = FakeClient([FakeUser(i) for i in range(1, 26)])
    with Env(docs=docs, admins=[900], client=client):
        page1 = FakeMessage(user_id=900)
        await uc.render_user_page(client, page1, 1, uc.FILTER_ALL)
        rows1 = list_block(page1.replies[0][0]).strip().splitlines()
        assert len(rows1) == 2 * uc.USER_PAGE_SIZE  # 10 entries, two lines each
        assert rows1[0].startswith("1. 900"), rows1[0]  # pinned super admin first
        assert "page 1/3" in page1.replies[0][0]

        page2 = FakeMessage(user_id=900)
        await uc.render_user_page(client, page2, 2, uc.FILTER_ALL)
        rows2 = list_block(page2.replies[0][0]).strip().splitlines()
        assert not rows2[0].startswith("1. 900")
        assert "page 2/3" in page2.replies[0][0]


async def test_pinned_super_admin_does_not_leave_a_gap():
    """Pinned rows displace the TAIL of page 1 and shift later pages up by
    their count — otherwise exactly `pinned` rows would fall through the gap
    before page 2 and never be shown (and `total` must not change between
    pages)."""
    now = datetime.now(timezone.utc)
    docs = [{"user_id": i, "last_seen": now - timedelta(minutes=i), "role": "user"}
            for i in range(1, 26)]
    with Env(docs=docs, admins=[900]):
        page1, page2 = FakeMessage(user_id=900), FakeMessage(user_id=900)
        await uc.render_user_page(None, page1, 1, uc.FILTER_ALL)
        await uc.render_user_page(None, page2, 2, uc.FILTER_ALL)
    ids = listed_ids(page1.replies[0][0]) + listed_ids(page2.replies[0][0])
    assert ids == ["900"] + [str(i) for i in range(1, 20)], ids
    assert "page 1/3" in page1.replies[0][0]
    assert "page 2/3" in page2.replies[0][0]


async def test_sort_is_last_seen_descending():
    now = datetime.now(timezone.utc)
    docs = [
        {"user_id": 1, "last_seen": now - timedelta(days=3)},
        {"user_id": 2, "last_seen": now - timedelta(minutes=1)},
        {"user_id": 3, "last_seen": now - timedelta(days=1)},
    ]
    with Env(docs=docs):
        msg = FakeMessage(user_id=900)
        await uc.render_user_page(None, msg, 1, uc.FILTER_ALL)
    assert listed_ids(msg.replies[0][0]) == ["2", "3", "1"]


async def test_active_filter_uses_a_seven_day_window():
    docs = [
        {"user_id": 1, "last_seen": datetime.now(timezone.utc) - timedelta(days=6)},
        {"user_id": 2, "last_seen": datetime.now(timezone.utc) - timedelta(days=8)},
        {"user_id": 3},  # never seen -> excluded
    ]
    with Env(docs=docs):
        msg = FakeMessage(user_id=900)
        await uc.render_user_page(None, msg, 1, uc.FILTER_ACTIVE)
    assert listed_ids(msg.replies[0][0]) == ["1"]


async def test_recent_filter_uses_a_thirty_day_join_window():
    now = datetime.now(timezone.utc)
    docs = [
        {"user_id": 1, "terms_accepted_at": now - timedelta(days=5)},
        {"user_id": 2, "terms_accepted_at": now - timedelta(days=45)},
        # No terms_accepted_at: falls back to the document creation time,
        # which Mongo stores as the ObjectId's leading timestamp — the same
        # `_id >= ObjectId(cutoff)` range the query runs.
        {"user_id": 3, "_id": ObjectId.from_datetime(now - timedelta(days=10))},
        {"user_id": 4, "_id": ObjectId.from_datetime(now - timedelta(days=90))},
    ]
    with Env(docs=docs):
        msg = FakeMessage(user_id=900)
        await uc.render_user_page(None, msg, 1, uc.FILTER_RECENT)
    assert sorted(listed_ids(msg.replies[0][0])) == ["1", "3"]


async def test_recent_window_is_exact_past_five_hundred_joiners():
    """The window lives in the query, so there is no scan cap to trip: 600
    joiners report 600 (the old 500-row cap reported 500) and the pager is
    built from the true total."""
    now = datetime.now(timezone.utc)
    docs = [{"user_id": 6000 + i,
             "terms_accepted_at": now - timedelta(days=1)} for i in range(600)]
    docs += [{"user_id": 9000 + i,
              "terms_accepted_at": now - timedelta(days=90)} for i in range(100)]
    with Env(docs=docs, admins=[1]):
        msg = FakeMessage(user_id=1)
        await uc.render_user_page(None, msg, 1, uc.FILTER_RECENT)
    text = msg.replies[0][0]
    assert "600 in this view" in text
    assert "page 1/60" in text


async def test_header_counts_stay_exact_at_scale():
    """Fail-safe: no read is capped, so past the old 2000-row scan limits
    the header and every list view still agree with reality."""
    now = datetime.now(timezone.utc)
    n_free, n_prem, n_banned = 1000, 2100, 2100
    docs = [{"user_id": 1000 + i, "role": "user"} for i in range(n_free)]
    docs += [{"user_id": 10000 + i, "role": "user"} for i in range(n_prem)]
    docs += [{"user_id": 90000 + i, "role": "banned"} for i in range(n_banned)]
    premium = [{"user_id": 10000 + i, "expiry_date": now + timedelta(days=5)}
               for i in range(n_prem)]
    with Env(docs=docs, premium=premium, admins=[1]):
        header = FakeMessage(user_id=1)
        await uc.render_user_page(None, header, 1, uc.FILTER_ALL)
        counts_line = header.replies[0][0].split("<code>")[1].split("</code>")[0]
        # admins=[1] adds one pinned Super Admin who has no user document.
        assert counts_line == (f"All {len(docs) + 1} · Free {n_free} "
                               f"· ⭐ {n_prem} · 👑 1 · 🚫 {n_banned}"), counts_line

        for filter_key, expected in ((uc.FILTER_FREE, n_free),
                                     (uc.FILTER_PREMIUM, n_prem),
                                     (uc.FILTER_BANNED, n_banned)):
            msg = FakeMessage(user_id=1)
            await uc.render_user_page(None, msg, 1, filter_key)
            assert f"{expected} in this view" in msg.replies[0][0], filter_key


async def test_hostile_names_are_html_escaped():
    evil = '<script>alert("x")</script> & co'
    client = FakeClient([FakeUser(1, evil, "</pre><b>pwn")])
    with Env(docs=[{"user_id": 1, "last_seen": datetime.now(timezone.utc)}],
             client=client):
        msg = FakeMessage(user_id=900)
        await uc.render_user_page(client, msg, 1, uc.FILTER_ALL)
    text, kwargs = msg.replies[0]
    assert "<script>" not in text and "</pre><b>pwn" not in text
    assert "&lt;script&gt;" in text
    assert text.count("<pre>") == 1 and text.count("</pre>") == 1
    assert kwargs["parse_mode"].value == "html"


async def test_lookup_failure_degrades_to_dashes():
    client = FakeClient(fail=True)
    with Env(docs=[{"user_id": 1, "last_seen": datetime.now(timezone.utc)}],
             client=client):
        msg = FakeMessage(user_id=900)
        await uc.render_user_page(client, msg, 1, uc.FILTER_ALL)
    assert "—" in msg.replies[0][0]
    assert "User manager" in msg.replies[0][0]


async def test_keyboard_marks_the_active_filter_and_gates_promote():
    with Env(admins=[1]):
        super_kb = uc.build_user_keyboard(uc.FILTER_BANNED, 1, 2, True).inline_keyboard
        flat = [button for row in super_kb for button in row]
        assert any(button.text.startswith("• ") for button in flat)
        assert any(button.callback_data == "usr#act#promote" for button in flat)

        admin_kb = uc.build_user_keyboard(uc.FILTER_ALL, 1, 2, False).inline_keyboard
        flat = [button for row in admin_kb for button in row]
        # A promoted (DB) admin sees Search / Ban / Unban only.
        assert not any(button.callback_data.endswith(("promote", "demote")) for button in flat)
        # Page 1 of 2: the current page and next, no back arrow.
        assert [button.callback_data for button in flat[-2:]] == [
            "usr#pg#1#all", "usr#pg#2#all"]


async def test_premium_filter_excludes_admins():
    now = datetime.now(timezone.utc)
    docs = [{"user_id": 1, "role": "admin"}, {"user_id": 2, "role": "user"}]
    premium = [{"user_id": 1, "expiry_date": now + timedelta(days=5)},
               {"user_id": 2, "expiry_date": now + timedelta(days=5)}]
    with Env(docs=docs, premium=premium):
        msg = FakeMessage(user_id=900)
        await uc.render_user_page(None, msg, 1, uc.FILTER_PREMIUM)
    assert listed_ids(msg.replies[0][0]) == ["2"]


# ------------------------------------------------------------------ #
#  4. Confirm / cancel round trip                                     #
# ------------------------------------------------------------------ #


def _queue_input(text):
    """Pre-resolve one prompt answer so wait_for_user_input returns at once."""
    chat_id, admin_id = 42, 42

    async def _fake_wait(chat, user, timeout=None):
        return SimpleNamespace(text=text)

    return chat_id, admin_id, _fake_wait


async def test_confirm_writes_roles_and_shows_the_result_banner():
    with Env(docs=[{"user_id": 5, "role": "user"}, {"user_id": 6, "role": "user"}],
             admins=[42]) as env:
        _chat, _uid, fake_wait = _queue_input("5, 6")
        original_wait = uc.wait_for_user_input
        uc.wait_for_user_input = fake_wait
        try:
            cb = FakeCallbackQuery("usr#act#ban_user", user_id=42)
            await uc.start_user_action(None, cb, "ban_user")
            # The preview is shown BEFORE anything is written.
            assert env.users.writes == []
            assert any("Confirm" in button.text
                       for row in cb.message.edits[0][1]["reply_markup"].inline_keyboard
                       for button in row)
            token = next(b.callback_data.split("#")[2]
                         for row in cb.message.edits[0][1]["reply_markup"].inline_keyboard
                         for b in row if b.callback_data.startswith("usr#cnf"))

            confirm = FakeCallbackQuery(f"usr#cnf#{token}", user_id=42,
                                        message=cb.message)
            await uc.confirm_user_action(None, confirm, token)
        finally:
            uc.wait_for_user_input = original_wait
        assert role_of(env, 5) == "banned" and role_of(env, 6) == "banned"
        # The dashboard comes back on the produced status set (Ban -> Banned);
        # it replaces the preview, so it is the last edit.
        assert "Banned 2" in confirm.message.edits[-1][0]
        assert "🚫 Banned" in confirm.message.edits[-1][0]
        # A replayed token is refused.
        replay = FakeCallbackQuery(f"usr#cnf#{token}", user_id=42, message=cb.message)
        await uc.confirm_user_action(None, replay, token)
        assert "expired" in replay.answers[-1][0]


async def test_pending_action_state_is_reaped_by_the_cleanup_sweep():
    """The preview state carries created_at so the sweeper can drop it."""
    from features.utils import cleanup_expired_bulk_downloads
    with Env(docs=[{"user_id": 5, "role": "user"}], admins=[42]):
        _chat, _uid, fake_wait = _queue_input("5")
        original_wait = uc.wait_for_user_input
        uc.wait_for_user_input = fake_wait
        try:
            cb = FakeCallbackQuery("usr#act#ban_user", user_id=42)
            await uc.start_user_action(None, cb, "ban_user")
        finally:
            uc.wait_for_user_input = original_wait
        token = next(b.callback_data.split("#")[2]
                     for row in cb.message.edits[0][1]["reply_markup"].inline_keyboard
                     for b in row if b.callback_data.startswith("usr#cnf"))
        state = uc.bulk_downloads[token]
        assert state["type"] == "user_action" and state["admin_id"] == 42
        assert state["created_at"] is not None
        uc.bulk_downloads[token]["created_at"] = days_ago(2)
        await cleanup_expired_bulk_downloads(uc.bulk_downloads)
        assert token not in uc.bulk_downloads


async def test_cancel_writes_nothing():
    with Env(docs=[{"user_id": 5, "role": "user"}], admins=[42]) as env:
        _chat, _uid, fake_wait = _queue_input("5")
        original_wait = uc.wait_for_user_input
        uc.wait_for_user_input = fake_wait
        try:
            cb = FakeCallbackQuery("usr#act#ban_user", user_id=42)
            await uc.start_user_action(None, cb, "ban_user")
        finally:
            uc.wait_for_user_input = original_wait
        token = next(b.callback_data.split("#")[2]
                     for row in cb.message.edits[0][1]["reply_markup"].inline_keyboard
                     for b in row if b.callback_data.startswith("usr#cnf"))
        cancel = FakeCallbackQuery(f"usr#can#{token}", user_id=42, message=cb.message)
        await uc.cancel_user_action(None, cancel, token)
        assert env.users.writes == []
        # The dashboard comes back on top of the preview (last edit).
        assert "Cancelled" in cancel.message.edits[-1][0]


async def test_second_prompt_is_refused_while_one_is_open():
    """One pending prompt per (chat, user) — the first waiter is never stranded."""
    from features.config import user_input_events
    with Env(admins=[42]):
        user_input_events.clear()
        user_input_events["42_42"] = {"event": object(), "message": None}
        try:
            cb = FakeCallbackQuery("usr#act#ban_user", user_id=42)
            await uc.start_user_action(None, cb, "ban_user")
        finally:
            user_input_events.clear()
        assert cb.answers[-1][1] is True  # alert
        assert "already have an open prompt" in cb.answers[-1][0]
        assert cb.message.replies == []


async def test_prompt_can_be_cancelled_by_typing_cancel():
    with Env(docs=[{"user_id": 5, "role": "user"}], admins=[42]) as env:
        _chat, _uid, fake_wait = _queue_input("cancel")
        original_wait = uc.wait_for_user_input
        uc.wait_for_user_input = fake_wait
        try:
            cb = FakeCallbackQuery("usr#act#ban_user", user_id=42)
            await uc.start_user_action(None, cb, "ban_user")
        finally:
            uc.wait_for_user_input = original_wait
        assert env.users.writes == []
        assert "Cancelled" in cb.message.edits[0][0]


async def test_promoted_admin_cannot_promote_through_the_dashboard():
    with Env(docs=[{"user_id": 5, "role": "user"}], admins=[42]):
        _chat, _uid, fake_wait = _queue_input("5")
        original_wait = uc.wait_for_user_input
        uc.wait_for_user_input = fake_wait
        try:
            cb = FakeCallbackQuery("usr#act#promote", user_id=5)  # DB admin, not super
            await uc.start_user_action(None, cb, "promote")
        finally:
            uc.wait_for_user_input = original_wait
        assert "Not allowed" in cb.answers[-1][0]
        assert cb.message.replies == []


async def test_search_view_shows_a_single_user():
    client = FakeClient([FakeUser(77, "Zed", "zed")])
    with Env(docs=[{"user_id": 77, "role": "banned"}], admins=[42], client=client):
        _chat, _uid, fake_wait = _queue_input("@zed")
        original_wait = uc.wait_for_user_input
        uc.wait_for_user_input = fake_wait
        try:
            cb = FakeCallbackQuery("usr#act#search", user_id=42)
            await uc.start_user_action(client, cb, uc.ACTION_SEARCH)
        finally:
            uc.wait_for_user_input = original_wait
        block = list_block(cb.message.edits[0][0])
        assert "Zed" in block and "77" in block and "Banned" in block
        assert any(button.callback_data == "usr#all"
                   for row in cb.message.edits[0][1]["reply_markup"].inline_keyboard
                   for button in row)


async def test_search_not_found_alerts():
    with Env(admins=[42]):
        _chat, _uid, fake_wait = _queue_input("@ghostuser")
        original_wait = uc.wait_for_user_input
        uc.wait_for_user_input = fake_wait
        try:
            cb = FakeCallbackQuery("usr#act#search", user_id=42)
            await uc.start_user_action(None, cb, uc.ACTION_SEARCH)
        finally:
            uc.wait_for_user_input = original_wait
        assert cb.answers[-1][1] is True
        assert "Not found" in cb.answers[-1][0]


# ------------------------------------------------------------------ #
#  5. Text aliases route through the same write path                  #
# ------------------------------------------------------------------ #


async def test_aliases_route_through_apply_role_action():
    """The four legacy commands share /user's guards and write path."""
    calls = []
    real_apply = um.apply_role_action

    async def spy(by, action, records, via="dashboard"):
        calls.append((action, via, [rec["id"] for rec in records]))
        return await real_apply(by, action, records, via=via)

    client = FakeClient([FakeUser(5), FakeUser(6)])
    with Env(docs=[{"user_id": 5, "role": "user"}, {"user_id": 6, "role": "user"}],
             admins=[42], client=client):
        um.apply_role_action = spy
        commands.apply_role_action = spy
        try:
            msg = FakeMessage("/ban_user 5, 6", user_id=42)
            await commands.cmd_ban_user(client, msg)
        finally:
            um.apply_role_action = real_apply
            commands.apply_role_action = real_apply
    assert calls == [("ban_user", "alias", [5, 6])]
    assert "Banned 2" in msg.replies[0][0]


async def test_alias_is_private_only_and_admin_only():
    with Env(admins=[42]):
        group = FakeMessage("/ban_user 5", user_id=42, chat_type=ChatType.GROUP)
        await commands.cmd_ban_user(None, group)
        assert "private" in group.replies[0][0].lower()

        stranger = FakeMessage("/ban_user 5", user_id=99)
        await commands.cmd_ban_user(None, stranger)
        assert "Admins only" in stranger.replies[0][0]

        empty = FakeMessage("/ban_user", user_id=42)
        await commands.cmd_ban_user(None, empty)
        assert "Usage:" in empty.replies[0][0]


async def test_alias_skips_guarded_targets_in_the_summary():
    # The acting admin has the DB role, not a config Super Admin seat, so
    # targeting themselves reports "You" instead of "Super admin".
    with Env(docs=[{"user_id": 42, "role": "admin"},
                   {"user_id": 12, "role": "admin"},
                   {"user_id": 13, "role": "user"}],
             admins=[99]) as env:
        msg = FakeMessage("/ban_user 12, 13, 99, 42", user_id=42)
        await commands.cmd_ban_user(None, msg)
        text = msg.replies[0][0]
        assert "Banned 1" in text
        assert um.VERDICT_DEMOTE_FIRST in text
        assert um.VERDICT_SUPER_ADMIN in text
        assert um.VERDICT_SELF in text
        assert role_of(env, 13) == "banned"
        assert role_of(env, 12) == "admin"
        assert role_of(env, 42) == "admin"


async def test_alias_demote_requires_a_super_admin():
    with Env(docs=[{"user_id": 30, "role": "admin"},
                   {"user_id": 31, "role": "admin"}], admins=[42]) as env:
        db_admin = FakeMessage("/demote 30", user_id=31)
        await commands.cmd_demote(None, db_admin)
        assert um.VERDICT_SUPER_ONLY in db_admin.replies[0][0]
        assert role_of(env, 30) == "admin"

        super_msg = FakeMessage("/demote 30", user_id=42)
        await commands.cmd_demote(None, super_msg)
        assert "Demoted 1" in super_msg.replies[0][0]
        assert role_of(env, 30) == "user"


if __name__ == "__main__":
    import asyncio
    import inspect

    failures = 0
    for name, fn in sorted(globals().items()):
        if not (name.startswith("test_") and inspect.isfunction(fn)):
            continue
        try:
            # pytest-asyncio runs the `async def` tests; the standalone runner
            # has to do it, and must leave the plain sync ones alone.
            if inspect.iscoroutinefunction(fn):
                asyncio.run(fn())
            else:
                fn()
            print(f"PASS {name}")
        except Exception as error:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name}: {error}")
            import traceback
            traceback.print_exc()
    print(f"\n{'all tests passed' if not failures else str(failures) + ' failure(s)'}")
    sys.exit(1 if failures else 0)
