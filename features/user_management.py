"""
User Management and Access Control Module

This module handles user authentication, authorization, and access control
for the MovieBot. It includes functions for checking user roles,
banning/unbanning users, and verifying terms acceptance.
"""

import re
import time
from datetime import datetime, timezone
from pyrogram.types import Message
from pyrogram.enums import ChatType

from .config import ADMINS, WATCHLIST_FREE_LIMIT, WATCHLIST_PREMIUM_LIMIT, \
    WATCHLIST_NOTIFY_COOLDOWN_SECONDS
from .database import users_col, logs_col, channels_col
from .tmdb_integration import normalize_content_type


async def get_user_doc(user_id: int):
    """Get user document from database"""
    return await users_col.find_one({"user_id": user_id})


async def is_admin(user_id: int):
    """Check if user is an admin"""
    if user_id in ADMINS:
        return True
    doc = await get_user_doc(user_id)
    return bool(doc and doc.get("role") == "admin")


async def is_banned(user_id: int):
    """Check if user is banned"""
    doc = await get_user_doc(user_id)
    return bool(doc and doc.get("role") == "banned")


async def has_accepted_terms(user_id: int):
    """Check if user has accepted terms and privacy policy"""
    doc = await get_user_doc(user_id)
    return bool(doc and doc.get("terms_accepted", False))


async def load_terms_and_privacy():
    """Load terms and privacy policy from markdown file"""
    try:
        with open('TERMS_AND_PRIVACY.md', 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except Exception as e:
        print(f"❌ Failed to load terms and privacy: {e}")
        return None


async def log_action(action: str, by: int = None, target: int = None, extra: dict = None):
    """Log actions to database and optionally to log channel"""
    doc = {
        "action": action,
        "by": by,
        "target": target,
        "extra": extra or {},
        "ts": datetime.now(timezone.utc)
    }
    try:
        await logs_col.insert_one(doc)
    except Exception:
        pass
    
    # Import client and LOG_CHANNEL here to avoid circular imports
    from .config import client, LOG_CHANNEL
    if client and LOG_CHANNEL:
        try:
            msg = f"Log: {action}\nBy: {by}\nTarget: {target}\nExtra: {extra or {}}"
            await client.send_message(int(LOG_CHANNEL), msg)
        except Exception:
            pass


# ------------------------------------------------------------------ #
#  Role actions (shared by /user and the /promote /demote /ban_user /   #
#  unban_user aliases)                                                 #
# ------------------------------------------------------------------ #
#
# `role` stays a SINGLE field (user | admin | banned), so a banned target is
# always a plain "user" and unban -> "user" is always correct. There is no
# role stash / `role_before_bun`: the demote-then-ban rule below makes a
# multi-state role unnecessary.
#
#   action       -> role written to users_col
ROLE_ACTIONS = {
    "promote": "admin",
    "demote": "user",
    "ban_user": "banned",
    "unban_user": "user",
}

# Past-tense labels for the result summary / dashboard banner.
ACTION_LABELS = {
    "promote": "Promoted",
    "demote": "Demoted",
    "ban_user": "Banned",
    "unban_user": "Unbanned",
}

# Only a config Super Admin (ADMINS) may hand out or revoke the admin role.
SUPER_ONLY_ACTIONS = frozenset({"promote", "demote"})

# Verdict strings — shared by the /user preview table, the result banner and
# the text aliases so one target always reports the same reason. They are
# self-contained phrases: the "— skipped" suffix is part of the hard skips, a
# no-op says "(no-op)" instead.
VERDICT_SUPER_ADMIN = "👑 Super admin — skipped"
VERDICT_SELF = "⚠️ You — skipped"
VERDICT_NOT_FOUND = "❌ Not found"
VERDICT_BAD_INPUT = "⚠️ Bad input"
VERDICT_BANNED_NOOP = "⚠️ Already banned (no-op)"
VERDICT_DEMOTE_FIRST = "⚠️ Demote first — skipped"
VERDICT_UNBAN_FIRST = "⚠️ Unban first — skipped"
VERDICT_ALREADY_ADMIN = "⚠️ Already admin (no-op)"
VERDICT_NOT_ADMIN = "⚠️ Not an admin (no-op)"
VERDICT_NOT_BANNED = "⚠️ Not banned (no-op)"
VERDICT_SUPER_ONLY = "🚫 Super admin only — skipped"
VERDICT_WRITE_FAILED = "❌ Write failed — skipped"

# Telegram handles: a letter, then letters/digits/underscores. The lower bound
# is deliberately loose (Telegram itself only issues 5+ character handles) so a
# short or hand-typed name still resolves instead of being called "not found".
_HANDLE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,31}$")


def parse_target_tokens(raw_text: str) -> list:
    """Split a raw target list into int user ids and '@handle' strings.

    Commas AND whitespace separate, so `123, @bob` and `123 @bob` both work.
    Handles are normalised to a leading '@'; anything that is neither a
    number nor a plausible handle is dropped (a bad token must never reach
    the database or the Telegram RPC).
    """
    tokens = []
    for chunk in re.split(r"[,\s]+", (raw_text or "").strip()):
        if not chunk:
            continue
        try:
            tokens.append(int(chunk))
            continue
        except ValueError:
            pass
        handle = chunk[1:] if chunk.startswith("@") else chunk
        if _HANDLE_RE.match(handle):
            tokens.append("@" + handle)
    return tokens


async def lookup_users_batched(client, targets) -> dict:
    """Resolve ids/@handles with ONE batched `get_users` -> {id: user}.

    pyrogram answers a list input with a `types.List` in arbitrary order and
    silently omits ids it cannot resolve (deleted accounts), so the result is
    keyed by id rather than by position. Any failure degrades to {} — a
    lookup problem must never break a render or a command.
    """
    if client is None or not targets:
        return {}
    try:
        found = await client.get_users(list(targets))
    except Exception as e:
        print(f"⚠️ batched get_users failed: {e}")
        return {}
    users = found if isinstance(found, (list, tuple)) else [found]
    resolved = {}
    for user in users or []:
        uid = getattr(user, "id", None)
        if uid is not None:
            resolved[uid] = user
    return resolved


async def _load_user_roles(user_ids) -> dict:
    """One query for {user_id: role} (default "user" for unknown ids)."""
    ids = [int(uid) for uid in user_ids if uid is not None]
    if not ids:
        return {}
    try:
        cursor = users_col.find({"user_id": {"$in": ids}},
                                {"user_id": 1, "role": 1, "username": 1, "first_name": 1})
        docs = await cursor.to_list(length=len(ids) + 5)
    except Exception as e:
        print(f"⚠️ role lookup failed for {ids}: {e}")
        return {}
    return {doc.get("user_id"): (doc.get("role") or "user") for doc in docs or []}


def role_guard_verdict(action: str, target_id: int, role, actor_id: int):
    """Guard check for one target; ``None`` means the action may be written.

    The single source of truth for WHO may be touched:
      (a) config ADMINS are untouchable,
      (b) nobody may target themselves (Super Admin included),
      (c) a DB-role admin must be demoted before they can be banned,
      (e) a banned user must be unbanned before they can be promoted.
    Per-action no-ops (already banned, not an admin, ...) are reported with
    their own reason instead of being written as a silent no-op. ``action=None``
    (or ``actor_id=None``) evaluates only the guards that apply to every
    action, which is what the dashboard's resolve step needs before the admin
    has picked an action.
    """
    if target_id in ADMINS:
        return VERDICT_SUPER_ADMIN
    if target_id == actor_id:
        return VERDICT_SELF
    role = role or "user"
    if action == "promote":
        if role == "banned":
            return VERDICT_UNBAN_FIRST
        if role == "admin":
            return VERDICT_ALREADY_ADMIN
    elif action == "demote":
        if role != "admin":
            return VERDICT_NOT_ADMIN
    elif action == "ban_user":
        if role == "admin":
            return VERDICT_DEMOTE_FIRST
        if role == "banned":
            return VERDICT_BANNED_NOOP
    elif action == "unban_user":
        if role != "banned":
            return VERDICT_NOT_BANNED
    return None


async def resolve_targets(client, raw_text, actor_id=None, guard_action=None) -> list:
    """Resolve a raw target list into per-target records — READ ONLY.

    One batched `client.get_users([...])` resolves every id/@handle, one query
    loads the current roles, and each record gets a guard ``verdict``:
    ``None`` = actionable, otherwise the reason it will be skipped.

    ``actor_id`` adds the "you may not target yourself" guard and
    ``guard_action`` (``promote`` / ``demote`` / ``ban_user`` / ``unban_user``)
    adds the per-action reason (already banned, demote first, unban first).
    Without them only the action-independent guards (config Super Admin,
    not found) are reported. Nothing is written here: /user renders these
    records as the preview table and hands the actionable ones to
    `apply_role_action`, which re-checks every guard before writing.
    """
    tokens = parse_target_tokens(raw_text)
    if not tokens:
        return []

    found = await lookup_users_batched(client, tokens)
    # `get_users` answers a list of ids AND @handles with a `types.List` that
    # only exposes `id`, so the handle -> user mapping is rebuilt from the
    # usernames of the users that did come back.
    by_handle = {}
    for user in found.values():
        username = getattr(user, "username", None)
        if username:
            by_handle[str(username).lower().lstrip("@")] = user
    # A completely empty answer next to numeric targets means the lookup
    # itself failed (offline / RPC error), not that the accounts are gone:
    # keep those ids actionable so a network hiccup cannot block the admin.
    lookup_failed = not found and any(isinstance(t, int) for t in tokens)

    records, resolved = [], set()
    for token in tokens:
        user = found.get(token) if isinstance(token, int) else by_handle.get(token[1:].lower())
        if user is not None:
            resolved.add(str(token))
        records.append({
            "input": str(token),
            "id": user.id if user is not None else (token if isinstance(token, int) else None),
            "username": getattr(user, "username", None),
            "first_name": getattr(user, "first_name", None),
            "role": None,
            "verdict": None,
        })

    roles = await _load_user_roles([r["id"] for r in records if r["id"] is not None])
    for rec in records:
        if rec["id"] is None:
            # An @handle that resolved to nobody.
            rec["verdict"] = VERDICT_NOT_FOUND
            continue
        rec["role"] = roles.get(rec["id"], "user")
        if guard_action or actor_id is not None:
            rec["verdict"] = role_guard_verdict(
                guard_action, rec["id"], rec["role"], actor_id)
        if rec["verdict"]:
            continue
        if rec["input"] not in resolved and not lookup_failed:
            # A numeric id Telegram knows but did not answer back — the account
            # was deleted. The guards run first so a Super Admin target always
            # reports the Super Admin reason, never "Not found".
            rec["verdict"] = VERDICT_NOT_FOUND
    return records


def role_target_label(record) -> str:
    """Short label for a resolved target: `@bob` when known, else the id."""
    record = record or {}
    username = record.get("username")
    if username:
        return f"@{username}"
    target_id = record.get("id")
    if target_id is not None:
        return str(target_id)
    return str(record.get("input") or "?")


def format_role_target_lines(records) -> list:
    """`label — verdict` lines: ✅ for actionable targets, the verdict for
    every target that will be skipped (bad ids and skips are shown BEFORE any
    write happens)."""
    lines = []
    for rec in records or []:
        label = role_target_label(rec)
        verdict = (rec or {}).get("verdict")
        lines.append(f"✅ {label}" if not verdict else f"{label} — {verdict}")
    return lines


def format_role_skipped_lines(skipped, limit: int = 0) -> list:
    """`label — verdict` lines for the ``(record, verdict)`` pairs that
    `apply_role_action` returns as its `skipped` list.

    Those reasons are decided at WRITE time, not at preview time, so they are
    formatted here rather than through `format_role_target_lines` (which reads
    the `verdict` key of a preview record). `limit` caps the list for a banner.
    """
    pairs = list(skipped or [])
    if limit:
        pairs = pairs[:limit]
    return [f"{role_target_label(rec)} — {verdict}" for rec, verdict in pairs]


def format_role_summary(summary: dict) -> str:
    """One-line result summary: `✅ Banned 3 · ⚠️ 1 skipped`."""
    summary = summary or {}
    label = ACTION_LABELS.get(summary.get("action"), "Done")
    applied = summary.get("applied") or []
    skipped = summary.get("skipped") or []
    text = f"✅ {label} {len(applied)}" if applied else f"⚠️ {label} 0"
    if skipped:
        text += f" · ⚠️ {len(skipped)} skipped"
    return text


async def apply_role_action(by: int, action: str, resolved_targets, via: str = "dashboard") -> dict:
    """Write ``role`` for every actionable target. Returns {applied, skipped}.

    Every guard is RE-CHECKED here instead of trusting the preview: a target
    whose state changed between preview and confirm (or whose id was forged
    into the callback data) is skipped and surfaces in the result banner
    rather than being written. Log action names stay the historic ones
    (promote / demote / ban_user / unban_user) so `/logs` keeps rendering
    them; ``extra={"via": ...}`` records whether the change came from the
    dashboard or a text alias.
    """
    if action not in ROLE_ACTIONS:
        raise ValueError(f"Unknown role action: {action}")
    role = ROLE_ACTIONS[action]
    applied, skipped = [], []
    targets = [t for t in (resolved_targets or []) if t]
    if not targets:
        return {"action": action, "applied": applied, "skipped": skipped}

    # (d) Only a config Super Admin may promote/demote — checked once for the
    # whole batch so a non-super admin gets a single clear reason.
    if action in SUPER_ONLY_ACTIONS and by not in ADMINS:
        return {"action": action, "applied": applied,
                "skipped": [(t, VERDICT_SUPER_ONLY) for t in targets]}

    roles = await _load_user_roles([t.get("id") for t in targets if t.get("id") is not None])
    for rec in targets:
        target_id = rec.get("id")
        if target_id is None:
            skipped.append((rec, VERDICT_NOT_FOUND))
            continue
        verdict = role_guard_verdict(action, target_id, roles.get(target_id), by)
        if verdict:
            skipped.append((rec, verdict))
            continue
        try:
            await users_col.update_one({"user_id": target_id},
                                       {"$set": {"role": role}}, upsert=True)
        except Exception as e:
            print(f"⚠️ {action} failed for {target_id}: {e}")
            skipped.append((rec, VERDICT_WRITE_FAILED))
            continue
        await log_action(action, by=by, target=target_id, extra={"via": via})
        applied.append(target_id)
    return {"action": action, "applied": applied, "skipped": skipped}


# ------------------------------------------------------------------ #
#  Watchlist (notify users when a watched title gets indexed)          #
# ------------------------------------------------------------------ #


def _watch_key(title: str) -> str:
    """Normalized lowercase key used for watchlist matching."""
    return (title or "").strip().lower()


async def _resolve_tmdb_id(title: str, year=None, type_=None):
    """Best-effort TMDb ID lookup (cached; None without API key/failure)."""
    try:
        from .tmdb_integration import enrich_title
        meta = await enrich_title(title, year, type_ or "Movie")
    except Exception:
        return None
    return (meta or {}).get("tmdb_id")


async def add_to_watchlist(user_id: int, title: str, year=None, type_=None,
                           tmdb_id=None, imdb_id=None, status=None,
                           poster_url=None, seasons=None, episodes=None) -> bool:
    """Add a title to a user's watchlist (idempotent). Returns True if added.

    The entry carries the TMDb ID (resolved via the cached enrichment when
    not passed) so notifications match remakes/transliterations exactly;
    the normalized title stays as fallback for titles TMDb doesn't know.

    Callers that already resolved a candidate through the /watch picker pass
    the full detail set (``imdb_id``, ``status``, ``poster_url``, and for
    series ``seasons``/``episodes``) so the stored entry renders the
    type/year/status line in /watchlist without another API call.
    """
    if not title or not str(title).strip():
        return False
    key = _watch_key(title)
    if tmdb_id is None:
        tmdb_id = await _resolve_tmdb_id(str(title).strip(), year, type_)
    entry = {
        "title": str(title).strip(),
        "title_key": key,
        "year": year,
        "type": normalize_content_type(type_),
        "tmdb_id": tmdb_id,
        "added_at": datetime.now(timezone.utc),
    }
    # Only store the optional detail fields when we actually have them, so a
    # TMDb-less entry stays clean instead of carrying null placeholders.
    for field, value in (("imdb_id", imdb_id), ("status", status),
                         ("poster_url", poster_url), ("seasons", seasons),
                         ("episodes", episodes)):
        if value is not None:
            entry[field] = value
    if entry.get("status"):
        entry["status_checked_at"] = entry["added_at"]

    try:
        # Ensure the user document exists FIRST (upsert on user_id alone). A
        # $ne-filtered upsert would insert a SECOND user document whenever the
        # title is already watched (filter matches nothing -> upsert inserts).
        await users_col.update_one(
            {"user_id": user_id},
            {"$setOnInsert": {"user_id": user_id, "watchlist": []}},
            upsert=True,
        )
        # Idempotent on EITHER identity: skip the push when an entry with the
        # same TMDb ID or the same normalized title already exists.
        filt = {"user_id": user_id,
                "watchlist.title_key": {"$ne": key}}
        if tmdb_id is not None:
            filt["watchlist.tmdb_id"] = {"$ne": tmdb_id}
        result = await users_col.update_one(filt, {"$push": {"watchlist": entry}})
        return bool(result.modified_count)
    except Exception as e:
        print(f"⚠️ add_to_watchlist failed for {user_id}: {e}")
        return False


async def remove_from_watchlist(user_id: int, title: str) -> bool:
    """Remove a title from a user's watchlist. Returns True if removed."""
    key = _watch_key(title)
    try:
        result = await users_col.update_one(
            {"user_id": user_id},
            {"$pull": {"watchlist": {"title_key": key}}},
        )
        return bool(result.modified_count)
    except Exception as e:
        print(f"⚠️ remove_from_watchlist failed for {user_id}: {e}")
        return False


async def get_watchlist(user_id: int):
    """Return the user's watchlist (list of entries) or []."""
    try:
        doc = await users_col.find_one({"user_id": user_id}, {"watchlist": 1})
    except Exception as e:
        print(f"⚠️ get_watchlist failed for {user_id}: {e}")
        return []
    return (doc or {}).get("watchlist") or []


async def watchlist_capacity(user_id: int) -> tuple:
    """Return ``(limit, is_premium)`` for a user's watchlist cap.

    Free users track WATCHLIST_FREE_LIMIT titles, premium users
    WATCHLIST_PREMIUM_LIMIT. Admins get the premium cap without holding a
    premium record (same bypass the /request rate limits use).
    """
    if await is_admin(user_id):
        return WATCHLIST_PREMIUM_LIMIT, True
    # Imported lazily: premium_management imports log_action from this module,
    # so a top-level import here would be circular.
    from .premium_management import is_premium_user
    try:
        premium = await is_premium_user(user_id)
    except Exception as e:
        print(f"⚠️ watchlist_capacity premium check failed for {user_id}: {e}")
        premium = False
    return (WATCHLIST_PREMIUM_LIMIT if premium else WATCHLIST_FREE_LIMIT), premium


async def update_watchlist_status(user_id: int, title_key: str, fields: dict) -> bool:
    """Patch the status/detail fields of one watchlist entry. True if changed.

    Called by the /watchlist UPDATE button. Only the fields present in
    ``fields`` are written, so a partial TMDb response (e.g. a failed status
    derivation) never blanks data we already had.
    """
    allowed = {"status", "status_checked_at", "seasons", "episodes", "year"}
    patch = {k: v for k, v in (fields or {}).items() if k in allowed and v is not None}
    if not patch:
        return False
    try:
        result = await users_col.update_one(
            {"user_id": user_id, "watchlist.title_key": title_key},
            {"$set": {f"watchlist.$.{k}": v for k, v in patch.items()}},
        )
        return bool(result.modified_count)
    except Exception as e:
        print(f"⚠️ update_watchlist_status failed for {user_id}/{title_key}: {e}")
        return False


# Per-(user, title) floodgate: (uid, identity) -> (sent_at, extra_count).
# A series batch (S01E01..E10) or a multi-file drop indexes in one burst and
# each file would otherwise DM the watcher. Only the first copy inside the
# window notifies; the rest are suppressed. Keyed per title so two different
# titles landing together each get their own single message.
_notify_cooldowns: dict = {}


def _notify_identity(title: str, tmdb_id) -> str:
    """Cooldown key for one title: TMDb ID when known, else normalized title."""
    if tmdb_id is not None:
        return f"tmdb:{tmdb_id}"
    return f"title:{_watch_key(title)}"


def _cooldown_active(key: tuple) -> bool:
    """True when this (user, title) was already notified inside the window."""
    record = _notify_cooldowns.get(key)
    if not record:
        return False
    sent_at, count = record
    if (time.monotonic() - sent_at) > WATCHLIST_NOTIFY_COOLDOWN_SECONDS:
        _notify_cooldowns.pop(key, None)
        return False
    # Already DMed in this window: absorb the extra copy into the count
    # instead of sending a second message.
    _notify_cooldowns[key] = (sent_at, count + 1)
    return True


def reset_notify_cooldowns() -> None:
    """Clear the watchlist floodgate state (tests / manual recovery)."""
    _notify_cooldowns.clear()


async def notify_watchlist(entry: dict) -> int:
    """DM every user watching a title when a new copy is indexed.

    Matching is by TMDb ID first (exact across remakes/transliterations),
    falling back to normalized title (exact, case-insensitive) so a new
    season or episode of a watched series notifies too. The DM carries a
    Get button for the freshly indexed copy. Returns users notified.

    Floodgate: a burst of copies for the same title (a full season dropping
    at once, or several quality variants) sends each watcher ONE message —
    the rest are absorbed by the per-(user, title) cooldown above.
    """
    from .config import client
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    title = (entry.get("title") or "").strip()
    if not title or client is None:
        return 0
    key = _watch_key(title)
    tmdb_id = entry.get("tmdb_id")

    query = {"watchlist.title_key": key}
    if tmdb_id is not None:
        query = {"$or": [{"watchlist.tmdb_id": tmdb_id},
                         {"watchlist.title_key": key}]}

    try:
        docs = await users_col.find(query).to_list(length=200)
    except Exception as e:
        print(f"⚠️ notify_watchlist query failed: {e}")
        return 0

    notified = 0
    channel_id = entry.get("channel_id")
    message_id = entry.get("message_id")
    identity = _notify_identity(title, tmdb_id)
    for doc in docs:
        uid = doc.get("user_id")
        if uid is None:
            continue
        if _cooldown_active((uid, identity)):
            continue
        try:
            text = (
                f"🎬 **{title}** is now available!\n\n"
                f"You're watching this title - grab it below."
            )
            reply_markup = None
            if channel_id and message_id:
                reply_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "📥 Get File",
                        callback_data=f"get_file:{channel_id}:{message_id}",
                    )
                ]])
            await client.send_message(uid, text, reply_markup=reply_markup)
            # Record only after a successful send, so a failed DM does not
            # burn the user's window.
            _notify_cooldowns[(uid, identity)] = (time.monotonic(), 0)
            notified += 1
        except Exception as e:
            print(f"⚠️ notify_watchlist DM failed for {uid}: {e}")
    return notified


async def check_banned(message: Message) -> bool:
    """Check if user is banned and send message if they are"""
    uid = message.from_user.id
    if await is_banned(uid):
        await message.reply_text("🚫 You are banned from using this bot.")
        return True
    return False


async def check_terms_acceptance(message: Message) -> bool:
    """Check if user has accepted terms and send prompt if they haven't"""
    uid = message.from_user.id

    # Admins bypass terms acceptance check
    if await is_admin(uid):
        return True

    if not await has_accepted_terms(uid):
        await message.reply_text(
            "⚠️ **Terms Acceptance Required**\n\n"
            "You must accept our Terms of Use and Privacy Policy before using this bot.\n\n"
            "Please use /start to view and accept the terms."
        )
        return False
    return True


async def should_process_command(message: Message) -> bool:
    """
    Determine if a command should be processed based on access control rules.

    Commands are processed if:
    1. Message is from a private chat (direct message to bot)
    2. Message is from a monitored channel/group (registered in channels_col
       and enabled)
    3. User is an admin (in ADMINS list or has admin role in database)

    This prevents the bot from responding to commands in random groups.

    Note: chat.type is a pyrogram ChatType enum (not a plain string), so it
    is compared against the enum values directly.
    """
    # Always process private messages (direct messages to bot)
    if message.chat.type == ChatType.PRIVATE:
        return True

    # Check if user is an admin - admins can use commands anywhere
    user_id = message.from_user.id
    if await is_admin(user_id):
        return True

    # For groups/supergroups/channels, only process commands if the chat is a
    # registered, enabled monitored channel
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL):
        channel_doc = await channels_col.find_one({"channel_id": message.chat.id})
        if channel_doc and channel_doc.get("enabled", True):
            return True

    # Default: Don't process commands from unauthorized sources
    return False


def require_not_banned(func):
    """Decorator to check if user is banned before executing command"""
    async def wrapper(client, message: Message):
        if await check_banned(message):
            return
        return await func(client, message)
    return wrapper


async def should_process_command_for_user(user_id: int) -> bool:
    """Check if user has access to use bot commands"""
    # Check if user is admin
    if await is_admin(user_id):
        return True

    # Check if user is banned
    if await is_banned(user_id):
        return False

    # For now, allow all non-banned users
    return True