"""
Unified User Management Dashboard (/user)

One entry point for everything that used to be four separate commands
(`/promote`, `/demote`, `/ban_user`, `/unban_user` — kept as hidden text
aliases that run the same guards). Mirrors how `/mc` owns channel
management: a paginated list, single-select status filters, and inline
buttons that map onto the shared resolve -> preview -> confirm flow in
`user_management.py`.

Layout of one page (all rendered as HTML, names HTML-escaped because they
come from Telegram and are untrusted):

    👥 User manager · All
    All 120 · Free 100 · ⭐ 15 · 👑 3 · 🚫 2
    <pre>1. Alice @alice
       Admin · 93618599 · seen today</pre>
    [filters] [active/recent/show all] [search/ban/unban] [◀ 1/3 ▶]

State that outlives a single render (the pending confirm tokens) lives in
`config.bulk_downloads` under a short token so `callback_data` stays well
under Telegram's 64-byte cap, and carries `created_at` so
`cleanup_expired_bulk_downloads` reaps it.
"""

import asyncio
import html
import uuid
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from pyrogram.enums import ParseMode, ChatType
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from .config import ADMINS, bulk_downloads, user_input_events
from .database import users_col, premium_users_col
from .user_management import (
    ACTION_LABELS,
    SUPER_ONLY_ACTIONS,
    apply_role_action,
    format_role_skipped_lines,
    format_role_summary,
    format_role_target_lines,
    is_admin,
    lookup_users_batched,
    parse_target_tokens,
    resolve_targets,
    role_target_label,
)
from .utils import wait_for_user_input

# ------------------------------------------------------------------ #
#  Tunables                                                           #
# ------------------------------------------------------------------ #

USER_PAGE_SIZE = 10
# "Active" = last_seen within 7 days, "Recent" = joined within 30 days.
ACTIVE_WINDOW_DAYS = 7
RECENT_WINDOW_DAYS = 30
# How long an admin has to answer a target prompt (matches /index_channel).
PROMPT_TIMEOUT_SECONDS = 60
# Display cap for an untrusted display name.
MAX_NAME_LEN = 24
# How many skip reasons the result banner spells out (the counter always tells
# the full number).
MAX_BANNER_REASONS = 5
# Telegram rejects messages over 4096 chars; the list is the only part that
# grows, so the rendered body is kept comfortably below the limit.
MAX_MESSAGE_CHARS = 3900
# NOTE: deliberately NO read caps here (an earlier draft capped the premium /
# role / recent scans at 2000/2000/500 rows). A cap makes the header numbers
# silently wrong once a collection outgrows it. Every number is either a
# count_documents() result, the premium-id set (bounded by the paying
# population, never by total users), or a query whose result set IS the
# population being counted. Indexes: database.ensure_indexes() creates
# last_seen, role, terms_accepted_at (users) and expiry_date (premium_users).

# ------------------------------------------------------------------ #
#  Filter / action vocabulary                                         #
# ------------------------------------------------------------------ #

# Single-select status filters. `uid` is not a filter the user can pick: it
# backs the single-user view the Search action renders.
FILTER_ALL = "all"
FILTER_FREE = "free"
FILTER_PREMIUM = "premium"
FILTER_ADMIN = "admin"
FILTER_BANNED = "banned"
FILTER_ACTIVE = "active"
FILTER_RECENT = "recent"
FILTER_UID = "uid"

VISIBLE_FILTERS = (FILTER_ALL, FILTER_FREE, FILTER_PREMIUM, FILTER_ADMIN,
                   FILTER_BANNED, FILTER_ACTIVE, FILTER_RECENT)
FILTER_ROW_ONE = (FILTER_ALL, FILTER_FREE, FILTER_PREMIUM, FILTER_ADMIN,
                  FILTER_BANNED)
FILTER_ROW_TWO = (FILTER_ACTIVE, FILTER_RECENT)
FILTER_LABELS = {
    FILTER_ALL: "All",
    FILTER_FREE: "Free",
    FILTER_PREMIUM: "⭐ Premium",
    FILTER_ADMIN: "👑 Admin",
    FILTER_BANNED: "🚫 Banned",
    FILTER_ACTIVE: "Active",
    FILTER_RECENT: "Recent",
}

ACTION_SEARCH = "search"
ACTION_BUTTONS = {
    ACTION_SEARCH: "🔍 Search",
    "ban_user": "🚫 Ban",
    "unban_user": "✅ Unban",
    "demote": "⬇️ Demote",
    "promote": "⬆️ Promote",
}
# Order of the always-present action row; the Super-Admin-only row follows.
ACTION_ROW_BASE = (ACTION_SEARCH, "ban_user", "unban_user")
ACTION_ROW_SUPER = ("demote", "promote")

# Where the dashboard lands after a confirmed action: the action's own
# result set (Ban -> Banned, Promote -> Admin, Demote/Unban -> Free).
ACTION_RESULT_FILTER = {
    "ban_user": FILTER_BANNED,
    "promote": FILTER_ADMIN,
    "demote": FILTER_FREE,
    "unban_user": FILTER_FREE,
}

# Pending-action state kind stored in config.bulk_downloads.
STATE_USER_ACTION = "user_action"


def is_super_admin(user_id) -> bool:
    """True for a config Super Admin (ADMINS) — the only role that may
    promote/demote, and the only one whose id is pinned to the top."""
    return user_id in ADMINS


async def can_use_dashboard(user_id, chat_type, action=None) -> bool:
    """Gate for `/user` and every `usr#` callback.

    Private chat + admin, plus Super Admin for promote/demote. Callback data
    can be forged, so this is re-evaluated on every button press and not only
    when the keyboard was rendered.
    """
    if chat_type not in (ChatType.PRIVATE, "private"):
        return False
    if not await is_admin(user_id):
        return False
    if action in SUPER_ONLY_ACTIONS and not is_super_admin(user_id):
        return False
    return True


# ------------------------------------------------------------------ #
#  Data access                                                        #
# ------------------------------------------------------------------ #


async def _active_premium_ids() -> set:
    """`{user_id}` holding a non-expired premium record.

    Read WITHOUT a cap on purpose: the size of this set is the paying
    population, not the user base, so it stays small while the header stays
    exact. Capping it (as the first draft did) silently reclassifies premium
    users as free once the cap is passed. One projection read, one document
    per premium subscriber.
    """
    try:
        cursor = premium_users_col.find(
            {"expiry_date": {"$gt": datetime.now(timezone.utc)}}, {"user_id": 1})
        docs = await cursor.to_list(length=None)
    except Exception as e:
        print(f"⚠️ user dashboard premium scan failed: {e}")
        return set()
    return {doc.get("user_id") for doc in docs or [] if doc.get("user_id") is not None}


async def _super_admin_rows() -> list:
    """Config ADMINS that have no user document yet, as injectable rows.

    Injected rows carry no `last_seen`/join date (rendered as `—`) and are
    pinned to the TOP of page 1 in the All and Admin filters only.
    """
    if not ADMINS:
        return []
    try:
        docs = await users_col.find({"user_id": {"$in": ADMINS}},
                                    {"user_id": 1, "role": 1}).to_list(length=len(ADMINS) + 5)
    except Exception as e:
        print(f"⚠️ user dashboard super-admin scan failed: {e}")
        docs = []
    with_doc = {doc.get("user_id") for doc in docs or []}
    return [{"user_id": uid, "role": "admin", "injected": True}
            for uid in ADMINS if uid not in with_doc]


async def _sorted_docs(query: dict, skip: int, limit=None) -> list:
    """Query -> docs sorted by `last_seen` DESC (uses the `last_seen` index
    from `ensure_indexes()`).

    ``limit=None`` reads every match — only safe where the query itself is
    already bounded to the population being shown (the Recent window), so
    nothing is truncated and the count stays exact. Paginated views always
    pass a real limit.
    """
    if limit is not None and limit <= 0:
        return []
    try:
        cursor = users_col.find(query).sort("last_seen", -1)
        if skip:
            cursor = cursor.skip(skip)
        if limit is not None:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=limit)
    except Exception as e:
        print(f"⚠️ user dashboard query failed: {e}")
        return []


def _filter_query(filter_key: str, premium_ids: set) -> dict:
    """Mongo predicate for one status filter.

    Admin wins over Premium: a user who is both shows as `Admin` and is
    EXCLUDED from the Premium filter. A banned user holding an active premium
    record shows as `Banned ⭐` and appears in both Banned and Premium.
    """
    now = datetime.now(timezone.utc)
    if filter_key == FILTER_FREE:
        return {"role": {"$nin": ["admin", "banned"]},
                "user_id": {"$nin": list(premium_ids)}}
    if filter_key == FILTER_PREMIUM:
        return {"user_id": {"$in": list(premium_ids)}, "role": {"$ne": "admin"}}
    if filter_key == FILTER_ADMIN:
        return {"$or": [{"role": "admin"}, {"user_id": {"$in": ADMINS}}]}
    if filter_key == FILTER_BANNED:
        return {"role": "banned"}
    if filter_key == FILTER_ACTIVE:
        return {"last_seen": {"$gte": now - timedelta(days=ACTIVE_WINDOW_DAYS)}}
    return {}


async def _fetch_page(filter_key: str, page: int, premium_ids: set, uid=None):
    """Return ``(rows, total_pages, total)`` for one dashboard page."""
    page = max(1, int(page or 1))

    if filter_key == FILTER_UID:
        docs = await _sorted_docs({"user_id": uid} if uid is not None
                                  else {"user_id": -1}, 0, 1)
        return docs, 1, len(docs)

    if filter_key == FILTER_RECENT:
        # The 30-day window lives entirely IN THE QUERY, so the result set IS
        # the recent-joiner population and count/pager are exact at any size:
        #   branch A: an explicit join date inside the window;
        #   branch B: no join date -> fall back to the document creation time,
        #             which the default _id index stores as its leading
        #             timestamp (`_id >= ObjectId(cutoff)` is an indexed range
        #             scan). `{field: None}` matches a missing OR null value
        #             — the same fallback the old in-Python window used.
        # Comparing in the query also sidesteps Python's naive-vs-aware
        # TypeError: Mongo dates come back naive from a non-tz_aware client.
        cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_WINDOW_DAYS)
        docs = await _sorted_docs(
            {"$or": [{"terms_accepted_at": {"$gte": cutoff}},
                     {"terms_accepted_at": None,
                      "_id": {"$gte": ObjectId.from_datetime(cutoff)}}]},
            0, None)
        total = len(docs)
        total_pages = max(1, (total + USER_PAGE_SIZE - 1) // USER_PAGE_SIZE)
        page = min(page, total_pages)
        start = (page - 1) * USER_PAGE_SIZE
        return docs[start:start + USER_PAGE_SIZE], total_pages, total

    query = _filter_query(filter_key, premium_ids)
    # Injected Super Admins (config ADMINS with no user document) appear only
    # in the All and Admin views and lead page 1 — but they are COUNTED on
    # every page, so `total` and the pager cannot disagree between pages.
    injected = await _super_admin_rows() if filter_key in (FILTER_ALL, FILTER_ADMIN) else []
    try:
        total = (await users_col.count_documents(query)) + len(injected)
    except Exception as e:
        print(f"⚠️ user dashboard count failed: {e}")
        total = len(injected)
    total_pages = max(1, (total + USER_PAGE_SIZE - 1) // USER_PAGE_SIZE)
    page = min(page, total_pages)

    pinned = len(injected)
    if page == 1 and injected:
        # Pinned rows displace the TAIL of page 1, never later pages.
        room = max(0, USER_PAGE_SIZE - pinned)
        rows = list(injected) + await _sorted_docs(query, 0, room)
    else:
        # ...so every later page shifts UP by the pinned count: without this,
        # the rows displaced from page 1 would fall through the gap before
        # page 2 and never be shown.
        rows = await _sorted_docs(query, max(0, (page - 1) * USER_PAGE_SIZE - pinned),
                                  USER_PAGE_SIZE)
    return rows, total_pages, total


async def _status_counts(premium_ids: set) -> dict:
    """All / Free / Premium / Admin / Banned for the dashboard header.

    Every figure is the SAME query its list view runs (plus the pinned Super
    Admins, which only exist in the All/Admin views), so the header can never
    disagree with the rows below it — at any user-base size. Nothing is
    scanned into memory: `count_documents` returns a number, and the only id
    set in play is the premium one (see `_active_premium_ids`).

    A banned user with an active premium record counts under both Banned and
    ⭐ (that is why the sum can exceed `total`); admins win over Premium, so
    they are never counted as premium.
    """
    injected = len(await _super_admin_rows())
    try:
        return {
            "total": await users_col.count_documents({}) + injected,
            "free": await users_col.count_documents(
                _filter_query(FILTER_FREE, premium_ids)),
            "premium": await users_col.count_documents(
                _filter_query(FILTER_PREMIUM, premium_ids)),
            "admin": await users_col.count_documents(
                _filter_query(FILTER_ADMIN, premium_ids)) + injected,
            "banned": await users_col.count_documents(
                _filter_query(FILTER_BANNED, premium_ids)),
        }
    except Exception as e:
        print(f"⚠️ user dashboard counts failed: {e}")
        return {"total": 0, "free": 0, "premium": 0, "admin": 0, "banned": 0}


async def _resolve_names(client, rows) -> dict:
    """Display names for one page with ONE batched `get_users`.

    Order of truth: the live Telegram lookup, then any fields stored on the
    user document, then `—`. A failed lookup degrades to the stored fields;
    it never breaks the render.
    """
    ids = [row.get("user_id") for row in rows if row.get("user_id") is not None]
    live = await lookup_users_batched(client, ids)
    names = {}
    for row in rows:
        uid = row.get("user_id")
        user = live.get(uid)
        first = getattr(user, "first_name", None) or row.get("first_name")
        username = getattr(user, "username", None) or row.get("username")
        if not first and row.get("injected"):
            # An injected Super Admin has neither a user document nor a live
            # lookup result: its id reads better than a bare dash on the
            # pinned first line.
            first = str(uid)
        names[uid] = (first or "—", username or "—")
    return names


def status_label(row: dict, premium_ids: set) -> str:
    """Status column. Precedence: Super Admin > Admin > Banned (+⭐) >
    Premium > Free, so an admin holding a premium record reads `Admin`."""
    user_id = (row or {}).get("user_id")
    if user_id in ADMINS:
        return "👑 Super Admin"
    role = (row or {}).get("role") or "user"
    if role == "admin":
        return "Admin"
    if role == "banned":
        return "Banned ⭐" if user_id in premium_ids else "Banned"
    if user_id in premium_ids:
        return "⭐ Premium"
    return "Free"


def _ago(moment) -> str:
    """`last_seen` as `today` / `3d` / `5w` / `—`."""
    if not moment:
        return "—"
    if getattr(moment, "tzinfo", None) is None:
        moment = moment.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc) - moment).days
    if days <= 0:
        return "today"
    if days < 7:
        return f"{days}d"
    if days < 365:
        return f"{days // 7}w"
    return f"{days // 365}y"


# ------------------------------------------------------------------ #
#  Rendering                                                          #
# ------------------------------------------------------------------ #


def _truncate(text: str) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= MAX_NAME_LEN else text[:MAX_NAME_LEN - 1] + "…"


def _row_lines(index: int, row: dict, names: dict, premium_ids: set) -> list:
    """Two pre-formatted lines for one user."""
    user_id = row.get("user_id")
    first, username = names.get(user_id, ("—", "—"))
    handle = "" if username == "—" else f" @{username}"
    seen = _ago(row.get("last_seen"))
    return [f"{index}. {_truncate(first)}{handle}",
            f"   {status_label(row, premium_ids)} · {user_id} · seen {seen}"]


def render_user_page_text(filter_key, rows, names, counts, page, total_pages,
                          total, premium_ids, result_banner=None) -> str:
    """HTML body of one dashboard page.

    Every untrusted value (names, usernames, ids, the result banner) is HTML
    escaped, and the list lives in a single `<pre>` block that is truncated
    to stay under Telegram's 4096-character limit.
    """
    title = FILTER_LABELS.get(filter_key, FILTER_LABELS[FILTER_ALL])
    head = [f"👥 <b>User manager</b> · <b>{html.escape(title)}</b>",
            "<code>All {total} · Free {free} · ⭐ {premium} · 👑 {admin} · 🚫 {banned}</code>".format(
                total=counts["total"], free=counts["free"], premium=counts["premium"],
                admin=counts["admin"], banned=counts["banned"]),
            f"<code>{total} in this view · page {page}/{total_pages}</code>"]
    if result_banner:
        head.append(html.escape(result_banner))

    budget = MAX_MESSAGE_CHARS - sum(len(line) + 1 for line in head) - len("<pre></pre>")
    block_lines, dropped = [], 0
    for index, row in enumerate(rows, 1):
        chunk = _row_lines(index, row, names, premium_ids)
        used = sum(len(line) + 1 for line in block_lines)
        if used + sum(len(line) + 1 for line in chunk) > budget:
            dropped = len(rows) - index + 1
            break
        block_lines.extend(chunk)
    if dropped:
        block_lines.append(f"… +{dropped} more")
    body = ("<pre>" + html.escape("\n".join(block_lines)) + "</pre>") if block_lines \
        else "<i>No users in this view.</i>"
    return "\n".join(head + [body])


def build_user_keyboard(filter_key, page, total_pages, super_admin) -> InlineKeyboardMarkup:
    """Filter rows, action rows, pagination. `filter_key` may be the hidden
    `uid` view (no filter button is marked active then)."""
    rows = []
    first = [InlineKeyboardButton(
        ("• " if key == filter_key else "") + FILTER_LABELS[key],
        callback_data=f"usr#pg#1#{key}") for key in FILTER_ROW_ONE]
    second = [InlineKeyboardButton(
        ("• " if key == filter_key else "") + FILTER_LABELS[key],
        callback_data=f"usr#pg#1#{key}") for key in FILTER_ROW_TWO]
    second.append(InlineKeyboardButton("Show all", callback_data="usr#all"))
    rows.append(first)
    rows.append(second)

    base = [InlineKeyboardButton(ACTION_BUTTONS[action], callback_data=f"usr#act#{action}")
            for action in ACTION_ROW_BASE]
    rows.append(base)
    # Promote/demote hand out the admin role: Super Admin only.
    if super_admin:
        rows.append([InlineKeyboardButton(ACTION_BUTTONS[action], callback_data=f"usr#act#{action}")
                     for action in ACTION_ROW_SUPER])

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("◀", callback_data=f"usr#pg#{page - 1}#{filter_key}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}",
                                    callback_data=f"usr#pg#{page}#{filter_key}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("▶", callback_data=f"usr#pg#{page + 1}#{filter_key}"))
    rows.append(nav)
    return InlineKeyboardMarkup(rows)


def _viewer_id(target) -> int:
    """The admin behind a Message or a CallbackQuery."""
    from_user = getattr(target, "from_user", None)
    return getattr(from_user, "id", 0)


def _target_message(target):
    """The message a Message / CallbackQuery should be rendered on."""
    message = getattr(target, "message", None)
    return (message, True) if message is not None else (target, False)


async def _deliver(target, text: str, keyboard) -> None:
    """Edit in place for a callback, reply for a command message."""
    message, is_callback = _target_message(target)
    if is_callback:
        try:
            await message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            return
        except Exception as e:
            print(f"⚠️ user dashboard edit failed: {e}")
    await message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def render_user_page(client, target, page=1, filter_key=FILTER_ALL,
                           result_banner=None, uid=None) -> None:
    """Render the /user dashboard on a command message or a callback.

    `target` is the originating `Message` (new reply) or `CallbackQuery`
    (edit in place) so the router, the filter buttons, a confirmed action and
    the Search view all share one renderer.
    """
    if filter_key not in VISIBLE_FILTERS and filter_key != FILTER_UID:
        filter_key = FILTER_ALL
    premium_ids = await _active_premium_ids()
    rows, total_pages, total = await _fetch_page(filter_key, page, premium_ids, uid=uid)
    names = await _resolve_names(client, rows)
    counts = await _status_counts(premium_ids)
    text = render_user_page_text(filter_key, rows, names, counts, page,
                                 total_pages, total, premium_ids, result_banner)
    keyboard = build_user_keyboard(filter_key, page, total_pages,
                                   is_super_admin(_viewer_id(target)))
    await _deliver(target, text, keyboard)


# ------------------------------------------------------------------ #
#  /user                                                              #
# ------------------------------------------------------------------ #


async def cmd_user(client, message: Message):
    """Unified user manager: filters, live names, batch role actions.

    Private chat only (the dashboard shows every account) and admins only.
    """
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    if message.chat.type != ChatType.PRIVATE:
        return await message.reply_text("🔒 Use /user in a private chat with me.")
    await render_user_page(client, message, 1, FILTER_ALL)


# ------------------------------------------------------------------ #
#  Action flow: prompt -> preview -> confirm                          #
# ------------------------------------------------------------------ #

PROMPT_FOOTER = (
    "Send the values as a plain message (commands are not read here).\n"
    "Reply <b>CANCEL</b> to abort.\n\n"
    f"⏱️ {PROMPT_TIMEOUT_SECONDS} seconds.")


def build_prompt(action: str) -> str:
    titles = {
        "ban_user": "🚫 Ban users",
        "unban_user": "✅ Unban users",
        "promote": "⬆️ Promote to admin",
        "demote": "⬇️ Demote from admin",
        ACTION_SEARCH: "🔍 Find a user",
    }
    return (f"<b>{titles.get(action, 'Manage users')}</b>\n\n"
            "Send numeric user IDs or @usernames, comma-separated.\n"
            + PROMPT_FOOTER)


def build_preview_text(action: str, valid, skipped) -> str:
    """The confirmation table: every target, and why the skipped ones are."""
    lines = [f"<b>{ACTION_LABELS.get(action, 'Update')} — {len(valid)} target(s)</b>", ""]
    lines += [html.escape(line) for line in format_role_target_lines(valid)]
    if skipped:
        lines += ["", "<b>Skipped</b>"]
        lines += [html.escape(line) for line in format_role_target_lines(skipped)]
    lines += ["", "Nothing is written until you press Confirm."]
    return "\n".join(lines)


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Show all", callback_data="usr#all")]])


def _store_pending_action(action, valid, skipped, admin_id) -> str:
    """Park a previewed action under a short token.

    `created_at` is mandatory: `cleanup_expired_bulk_downloads` reaps by that
    field, and without it a forgotten preview would leak. The token keeps
    `callback_data` at ~16 bytes, far below Telegram's 64-byte cap.
    """
    token = uuid.uuid4().hex[:8]
    bulk_downloads[token] = {
        "type": STATE_USER_ACTION,
        "action": action,
        "valid": valid,
        "skipped": skipped,
        "admin_id": admin_id,
        "created_at": datetime.now(timezone.utc),
    }
    return token


def _pop_pending_action(token: str):
    state = bulk_downloads.pop(token, None) if token else None
    if not state or state.get("type") != STATE_USER_ACTION:
        return None
    return state


async def _prompt_for_targets(client, callback_query, action: str) -> str:
    """Ask the admin for targets and return the raw reply ('' = cancelled).

    Refuses to start when the admin already has a prompt open: `utils.wait_
    for_user_input` keeps ONE pending prompt per (chat, user) key, so
    starting a second one would overwrite the entry and strand the first
    waiter forever.
    """
    chat = callback_query.message.chat
    admin_id = callback_query.from_user.id
    key = f"{chat.id}_{admin_id}"
    if key in user_input_events:
        await callback_query.answer(
            "You already have an open prompt — finish it or send CANCEL first.",
            show_alert=True)
        return None
    await callback_query.answer()
    await callback_query.message.reply_text(build_prompt(action), parse_mode=ParseMode.HTML)
    try:
        response = await wait_for_user_input(chat.id, admin_id,
                                             timeout=PROMPT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        await render_user_page(client, callback_query, 1, FILTER_ALL,
                               result_banner="⏰ Timed out — nothing changed")
        return None
    return (getattr(response, "text", "") or "").strip()


async def start_user_action(client, callback_query, action: str) -> None:
    """Action button -> target prompt -> preview with Confirm/Cancel."""
    admin_id = callback_query.from_user.id
    chat = callback_query.message.chat
    # Re-checked here as well as in the usr# branch: promote/demote are
    # Super-Admin-only and a promoted (DB) admin must not see them.
    if action not in ACTION_BUTTONS or not await can_use_dashboard(
            admin_id, getattr(chat, "type", None), action):
        return await callback_query.answer("🚫 Not allowed.", show_alert=True)

    raw = await _prompt_for_targets(client, callback_query, action)
    if raw is None:
        return
    if not raw or raw.upper() == "CANCEL":
        return await render_user_page(client, callback_query, 1, FILTER_ALL,
                                      result_banner="❌ Cancelled — nothing changed")
    if action == ACTION_SEARCH:
        return await run_user_search(client, callback_query, raw)

    records = await resolve_targets(client, raw, actor_id=admin_id, guard_action=action)
    if not records:
        return await render_user_page(
            client, callback_query, 1, FILTER_ALL,
            result_banner="⚠️ No numeric id or @username recognised")
    valid = [rec for rec in records if not rec["verdict"]]
    skipped = [rec for rec in records if rec["verdict"]]
    if not valid:
        # Nothing to write — show every reason, then return to the list.
        await callback_query.message.edit_text(
            build_preview_text(action, valid, skipped), parse_mode=ParseMode.HTML,
            reply_markup=_back_keyboard())
        return await callback_query.answer("⚠️ No actionable target", show_alert=True)

    token = _store_pending_action(action, valid, skipped, admin_id)
    await callback_query.message.edit_text(
        build_preview_text(action, valid, skipped), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirm", callback_data=f"usr#cnf#{token}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"usr#can#{token}"),
        ]]))
    return await callback_query.answer(f"👀 {len(valid)} target(s) — confirm?")


async def confirm_user_action(client, callback_query, token: str) -> None:
    """Confirm -> write the roles -> refresh to the produced filter set.

    `apply_role_action` re-checks every guard, so a target that changed state
    between preview and confirm is skipped and shows up in the banner.
    """
    state = _pop_pending_action(token)
    if not state:
        return await callback_query.answer("⌛ This preview expired. Open /user again.",
                                           show_alert=True)
    admin_id = callback_query.from_user.id
    if state.get("admin_id") != admin_id:
        return await callback_query.answer("🚫 This preview belongs to another admin.",
                                           show_alert=True)
    action = state.get("action")
    chat = callback_query.message.chat
    if not await can_use_dashboard(admin_id, getattr(chat, "type", None), action):
        return await callback_query.answer("🚫 Not allowed.", show_alert=True)

    await callback_query.answer()
    summary = await apply_role_action(admin_id, action, state.get("valid") or [],
                                      via="dashboard")
    banner = format_role_summary(summary)
    reasons = format_role_skipped_lines(summary.get("skipped"), limit=MAX_BANNER_REASONS)
    if reasons:
        banner += "\n" + "\n".join(reasons)
    await render_user_page(client, callback_query, 1,
                           ACTION_RESULT_FILTER.get(action, FILTER_ALL),
                           result_banner=banner)


async def cancel_user_action(client, callback_query, token: str) -> None:
    """Drop the pending action and go back to the list. Writes nothing."""
    state = _pop_pending_action(token)
    if not state:
        return await callback_query.answer("⌛ This preview expired. Open /user again.",
                                           show_alert=True)
    if state.get("admin_id") != callback_query.from_user.id:
        return await callback_query.answer("🚫 This preview belongs to another admin.",
                                           show_alert=True)
    await callback_query.answer()
    await render_user_page(client, callback_query, 1, FILTER_ALL,
                           result_banner="❌ Cancelled — nothing changed")


async def run_user_search(client, callback_query, raw: str) -> None:
    """Resolve one target and render the dashboard for just that user."""
    tokens = parse_target_tokens(raw)
    records = await resolve_targets(client, raw, actor_id=callback_query.from_user.id)
    target = next((rec for rec in records if rec["id"] is not None), None)
    if target is None:
        if not tokens:
            return await callback_query.answer(
                "⚠️ No id or @username recognised.", show_alert=True)
        return await callback_query.answer(
            "❌ Not found — send a numeric id or @username.", show_alert=True)
    await callback_query.answer()
    await render_user_page(client, callback_query, 1, FILTER_UID, uid=target["id"],
                           result_banner=f"🔍 {role_target_label(target)}")
