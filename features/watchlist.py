"""
Watchlist Module — the /watch surface.

Extracted from commands.py (which re-exports the handlers for its router) so
the whole watchlist domain lives together:

1. ``/watch <title>``  — resolve the title on TMDb (movies AND shows), let the
   user disambiguate when it's ambiguous, then store the entry with its
   type / year / status / IMDb / TMDb detail.
2. ``/unwatch <title>`` — drop an entry.
3. ``/watchlist``      — list entries as ``Title: M / 2026 / Released · IMDb``
   with an UPDATE button that re-reads each title's status from TMDb/IMDb.

Storage primitives (``add_to_watchlist``, ``notify_watchlist``, capacity,
status patch) live in user_management.py; the TMDb status derivation lives in
tmdb_integration.py. This module is the UI + orchestration layer.
"""

import html
import uuid
from datetime import datetime, timezone

from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions,
)
from pyrogram.enums import ParseMode

from .config import (
    bulk_downloads,
    WATCHLIST_REFRESH_COOLDOWN_SECONDS,
    WATCHLIST_PREMIUM_LIMIT,
    WATCHLIST_PICK_LIMIT,
)
# Imported as a MODULE, not by name: every TMDb call below is reached through
# the module attribute so the dependency is explicit at each call site (and
# stubbable in tests without rebinding three local names).
from . import tmdb_integration as tmdb

STATUS_UNKNOWN = tmdb.STATUS_UNKNOWN

from .user_management import (
    add_to_watchlist,
    remove_from_watchlist,
    get_watchlist,
    update_watchlist_status,
    watchlist_capacity,
    log_action,
)

# How long a disambiguation picker stays clickable before it's swept up by
# cleanup_expired_bulk_downloads (shared store, so we stay well inside it).
PICK_TTL_SECONDS = 600

# user_id -> monotonic timestamp of their last UPDATE press.
_last_refresh: dict = {}


def _type_letter(type_: str) -> str:
    """``Movie`` -> ``M``, ``Series`` -> ``S`` for the one-line list format."""
    return "S" if tmdb.normalize_content_type(type_) == "Series" else "M"


def _links_html(entry: dict) -> str:
    """Trailing IMDb / TMDb link segment for a watchlist line."""
    links = []
    imdb_id = entry.get("imdb_id")
    if imdb_id:
        links.append(
            f'<a href="https://www.imdb.com/title/{imdb_id}/">IMDb</a>')
    tmdb_id = entry.get("tmdb_id")
    if tmdb_id is not None:
        links.append(
            f'<a href="https://www.themoviedb.org/{"movie" if _type_letter(entry) == "M" else "tv"}/{tmdb_id}">TMDb</a>')
    return " · ".join(links)


def _season_suffix(entry: dict) -> str:
    """`` · 3 seasons / 20 eps`` when TMDb reported the counts for a series."""
    if _type_letter(entry) != "S":
        return ""
    seasons, episodes = entry.get("seasons"), entry.get("episodes")
    parts = []
    if seasons:
        parts.append(f"{seasons} season{'s' if seasons != 1 else ''}")
    if episodes:
        parts.append(f"{episodes} ep{'s' if episodes != 1 else ''}")
    return f" · {' / '.join(parts)}" if parts else ""


def render_watchlist_text(entries: list) -> str:
    """Render the /watchlist body — one ``Title: M / 2026 / Released`` per line.

    Titles stay tap-to-copy (inside <code>) so a user can re-run /search with
    the exact string, matching /my_history and /recent.
    """
    if not entries:
        return (
            "👁️ <b>Your watchlist is empty</b>\n\n"
            "Use <code>/watch &lt;title&gt;</code> to get notified when a "
            "title is indexed."
        )

    lines = []
    for i, e in enumerate(entries, 1):
        title = html.escape(str(e.get("title") or "Unknown"))
        year = e.get("year") or "?"
        status = e.get("status") or STATUS_UNKNOWN
        links = _links_html(e)
        line = (
            f"{i}. <code>{title}</code>: {_type_letter(e)} / {year} / {status}"
            f"{_season_suffix(e)}"
        )
        if links:
            line += f" · {links}"
        lines.append(line)

    text = "👁️ <b>Your Watchlist</b>\n\n" + "\n".join(lines)
    text += (
        "\n\n<i>Tap any title to copy</i> · Remove with "
        "<code>/unwatch title</code>\n"
        "🔄 UPDATE re-checks each title's status on IMDb / TMDb."
    )
    return text


def render_watchlist_keyboard(entries: list, user_id: int) -> InlineKeyboardMarkup:
    """UPDATE (and per-entry refresh) keyboard under a /watchlist listing.

    ``🔄 UPDATE ALL`` re-checks every entry. A per-entry ``🔄`` next to a
    watched title re-checks just that one, which is what a user wants when a
    single show's status is the thing they're tracking.
    """
    rows = []
    if entries:
        per_entry = []
        for i, e in enumerate(entries):
            per_entry.append(InlineKeyboardButton(
                f"🔄 {i + 1}",
                callback_data=f"watchupd:one:{user_id}:{e.get('title_key')}",
            ))
        # Keep the row readable: 5 refresh chips per row.
        for start in range(0, len(per_entry), 5):
            rows.append(per_entry[start:start + 5])
    rows.append([InlineKeyboardButton(
        "🔄 UPDATE ALL", callback_data=f"watchupd:all:{user_id}")])
    return InlineKeyboardMarkup(rows)


async def _send_watchlist(client, message: Message, user_id: int, edit=False):
    """Render and send (or edit) the watchlist listing for a user."""
    entries = await get_watchlist(user_id)
    text = render_watchlist_text(entries)
    markup = render_watchlist_keyboard(entries, user_id)
    if edit:
        try:
            await message.edit_text(
                text, reply_markup=markup, parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True))
            return
        except Exception as e:
            # Message not editable (identical text, or too old) — fall through
            # and post a fresh copy so the user still gets their buttons.
            print(f"⚠️ watchlist edit failed ({user_id}): {e}")
    await message.reply_text(
        text, reply_markup=markup, parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True))


# ------------------------------------------------------------------ #
#  /watch <title>                                                    #
# ------------------------------------------------------------------ #

def _render_picker(candidates: list, query: str) -> str:
    """Body text for the disambiguation picker."""
    lines = [
        "🔍 <b>Which one did you mean?</b>",
        "",
        f"Multiple titles match <code>{html.escape(str(query))}</code>:",
        "",
    ]
    for i, c in enumerate(candidates, 1):
        title = html.escape(str(c.get("title") or "Unknown"))
        year = c.get("year") or "?"
        status = c.get("status") or STATUS_UNKNOWN
        lines.append(f"{i}. <code>{title}</code>: {_type_letter(c)} / {year} / {status}")
    lines += [
        "",
        "Pick one below — you'll be notified the moment a file for it is indexed.",
    ]
    return "\n".join(lines)


def _picker_keyboard(token: str, candidates: list) -> InlineKeyboardMarkup:
    """One button per candidate, plus Cancel."""
    rows = []
    for i, c in enumerate(candidates):
        title = str(c.get("title") or "Unknown")
        year = c.get("year") or "?"
        label = f"{title} ({year}) [{_type_letter(c)}]"
        # Inline button labels are length-capped by Telegram; trim the tail
        # (the year/type bracket survives, the title start is what identifies
        # the row in the list above it).
        if len(label) > 40:
            label = label[:39] + "…"
        rows.append([InlineKeyboardButton(
            label, callback_data=f"watchpick:{token}:{i}")])
    rows.append([InlineKeyboardButton(
        "✖️ Cancel", callback_data=f"watchpick:{token}:cancel")])
    return InlineKeyboardMarkup(rows)


async def cmd_watch(client, message: Message):
    """Handle /watch <title> — resolve on TMDb, disambiguate, then store."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await message.reply_text(
            "👁️ <b>Watchlist</b>\n\nUsage: <code>/watch &lt;title&gt;</code>\n"
            "I'll check IMDb / TMDb for the exact title, then notify you the "
            "moment a file for it is indexed.",
            parse_mode=ParseMode.HTML,
        )
    query = parts[1].strip()
    uid = message.from_user.id

    # Capacity gate first: don't spend TMDb calls on a request we'd refuse.
    entries = await get_watchlist(uid)
    limit, premium = await watchlist_capacity(uid)
    if len(entries) >= limit:
        upgrade = (
            f"\n\n⭐ Upgrade to Premium for {WATCHLIST_PREMIUM_LIMIT} titles."
            if not premium else ""
        )
        return await message.reply_text(
            f"👁️ <b>Watchlist full</b>\n\n"
            f"You're tracking {len(entries)} of {limit} titles."
            f"{upgrade}\n\nRemove one with <code>/unwatch &lt;title&gt;</code>.",
            parse_mode=ParseMode.HTML,
        )

    status_msg = await message.reply_text(
        f"🔍 Checking IMDb / TMDb for <b>{html.escape(query)}</b>...",
        parse_mode=ParseMode.HTML,
    )

    try:
        candidates = await tmdb.search_watch_candidates(
            query, limit=WATCHLIST_PICK_LIMIT)
    except Exception as e:
        print(f"⚠️ watch search failed for {uid}: {e}")
        candidates = []

    if not candidates:
        # No TMDb match: still track it on the normalized-title fallback so
        # the user isn't left without a watch, but be explicit that matching
        # will be title-only. ``store_watch_pick`` edits the message, so the
        # caveat is folded into its confirmation rather than sent separately
        # (two edits in a row would race and lose text).
        return await store_watch_pick(uid, query, status_msg,
                                      no_match_note=True)

    if tmdb.is_ambiguous_title(query, candidates):
        token = uuid.uuid4().hex[:12]
        bulk_downloads[token] = {
            "type": "watch_pick",
            "user_id": uid,
            "query": query,
            "candidates": candidates,
            "expires": datetime.now().timestamp() + PICK_TTL_SECONDS,
        }
        await status_msg.edit_text(
            _render_picker(candidates, query),
            reply_markup=_picker_keyboard(token, candidates),
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return

    # Unambiguous single exact match — store straight away.
    chosen = candidates[0]
    await store_watch_pick(uid, chosen, status_msg, raw_title=query)


async def store_watch_pick(uid: int, source, target_msg: Message,
                           raw_title=None, no_match_note: bool = False) -> bool:
    """Persist one resolved candidate (or a bare title); confirm in-place.

    ``source`` is either a TMDb candidate dict or, when TMDb found nothing, a
    plain title string. The confirmation replaces the message the user is
    looking at (the "Checking…" reply for /watch, or the picker message for a
    disambiguation button). ``no_match_note`` adds the title-only-matching
    caveat to that confirmation. Returns True when a new entry was added.
    """
    if isinstance(source, str):
        title = source
        details = {}
    else:
        title = (source.get("title") or raw_title or "").strip()
        details = source
    if not title:
        await target_msg.edit_text(
            "❌ Couldn't read a title from that pick. Try <code>/watch "
            "&lt;title&gt;</code> again.",
            parse_mode=ParseMode.HTML,
        )
        return False

    added = await add_to_watchlist(
        uid,
        title,
        year=details.get("year"),
        type_=details.get("type"),
        tmdb_id=details.get("tmdb_id"),
        imdb_id=details.get("imdb_id"),
        status=details.get("status"),
        poster_url=details.get("poster_url"),
        seasons=details.get("seasons"),
        episodes=details.get("episodes"),
    )

    if added:
        await log_action("watch_added", by=uid, extra={
            "title": title, "tmdb_id": details.get("tmdb_id"),
            "status": details.get("status"),
        })
        limit, _ = await watchlist_capacity(uid)
        entries = await get_watchlist(uid)
        line = f"<code>{html.escape(title)}</code>: {_type_letter(details)}"
        if details.get("year"):
            line += f" / {details['year']}"
        if details.get("status"):
            line += f" / {details['status']}{_season_suffix(details)}"
        links = _links_html(details)
        if links:
            line += f" · {links}"
        text = f"👁️ <b>Watching</b>\n\n{line}"
        if limit and len(entries) >= limit:
            text += f"\n\n⚠️ That's your last slot ({len(entries)}/{limit})."
        if no_match_note:
            text += (
                "\n\n⚠️ No IMDb / TMDb match, so this is stored on the title "
                "text only — a remake of the same name may also notify you."
            )
        else:
            text += "\n\nI'll DM you the moment a file for it is indexed."
        await target_msg.edit_text(text, parse_mode=ParseMode.HTML)
    else:
        await target_msg.edit_text(
            f"👁️ <b>{html.escape(title)}</b> is already on your watchlist.",
            parse_mode=ParseMode.HTML,
        )
    return added


# ------------------------------------------------------------------ #
#  /unwatch <title>                                                  #
# ------------------------------------------------------------------ #

async def cmd_unwatch(client, message: Message):
    """Handle /unwatch <title> — remove a title from the watchlist."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return await message.reply_text(
            "👁️ Usage: <code>/unwatch &lt;title&gt;</code>",
            parse_mode=ParseMode.HTML)
    title = parts[1].strip()
    removed = await remove_from_watchlist(message.from_user.id, title)
    if removed:
        await message.reply_text(
            f"✅ <b>{html.escape(title)}</b> removed from your watchlist.",
            parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(
            f"👁️ <b>{html.escape(title)}</b> is not on your watchlist.",
            parse_mode=ParseMode.HTML)


# ------------------------------------------------------------------ #
#  /watchlist                                                        #
# ------------------------------------------------------------------ #

async def cmd_watchlist(client, message: Message):
    """Handle /watchlist — list watched titles with the UPDATE button."""
    uid = message.from_user.id
    entries = await get_watchlist(uid)
    if not entries:
        return await message.reply_text(
            render_watchlist_text(entries), parse_mode=ParseMode.HTML)
    await _send_watchlist(client, message, uid)


# ------------------------------------------------------------------ #
#  UPDATE (watchupd:) callbacks                                       #
# ------------------------------------------------------------------ #

def _refresh_allowed(uid: int) -> bool:
    """Per-user floor between UPDATE presses (one TMDb call per entry)."""
    import time as _time
    last = _last_refresh.get(uid)
    now = _time.monotonic()
    if last is not None and (now - last) < WATCHLIST_REFRESH_COOLDOWN_SECONDS:
        wait = int(WATCHLIST_REFRESH_COOLDOWN_SECONDS - (now - last)) + 1
        return wait
    _last_refresh[uid] = now
    return True


async def refresh_watchlist_statuses(uid: int, only_key: str = None) -> int:
    """Re-read status for watchlist entries from TMDb. Returns entries updated.

    ``only_key`` limits the refresh to a single entry (the per-title 🔄
    button). Entries without a TMDb ID can't be re-checked — the status is
    derived from TMDb, and a title-only entry has no identity to query — so
    they're skipped rather than blanked.
    """
    entries = await get_watchlist(uid)
    updated = 0
    for entry in entries:
        if only_key is not None and entry.get("title_key") != only_key:
            continue
        tmdb_id = entry.get("tmdb_id")
        if tmdb_id is None:
            continue
        try:
            detail = await tmdb.fetch_title_status(tmdb_id, entry.get("type"))
        except Exception as e:
            print(f"⚠️ watchlist refresh failed for {uid}/{entry.get('title_key')}: {e}")
            continue
        if not detail or not detail.get("status"):
            continue
        patch = {
            "status": detail["status"],
            "status_checked_at": datetime.now(timezone.utc),
        }
        if detail.get("seasons") is not None:
            patch["seasons"] = detail["seasons"]
        if detail.get("episodes") is not None:
            patch["episodes"] = detail["episodes"]
        if detail.get("year") and detail["year"] != "N/A":
            patch["year"] = detail["year"]
        if await update_watchlist_status(uid, entry["title_key"], patch):
            updated += 1
    return updated


async def handle_watch_update(client, callback_query, scope: str, arg: str):
    """Run an UPDATE press, then re-render the list. Shared by both buttons.

    ``scope`` is ``all`` or ``one``; ``arg`` is unused for ``all`` and holds
    the ``title_key`` for ``one``. The clicker's user id is carried in the
    callback data so a shared message can't be used to refresh someone else's
    list.
    """
    uid = callback_query.from_user.id
    target = arg if scope == "one" else None

    # Ownership: the buttons embed the list owner's id. A message forwarded
    # to someone else must not act on the original owner's watchlist.
    parts = (callback_query.data or "").split(":")
    owner = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else uid
    if owner != uid:
        return await callback_query.answer(
            "🚫 This watchlist belongs to another user.", show_alert=True)

    allowed = _refresh_allowed(uid)
    if allowed is not True:
        return await callback_query.answer(
            f"⏳ Update cooldown — try again in {allowed}s.", show_alert=True)

    # Answer first: Telegram's 15s callback window closes fast, and a refresh
    # that walks up to 20 TMDb lookups can outrun it.
    await callback_query.answer("🔄 Checking IMDb / TMDb...")
    updated = await refresh_watchlist_statuses(uid, only_key=target)
    if target is None:
        entries = await get_watchlist(uid)
        skipped = sum(1 for e in entries if e.get("tmdb_id") is None)
        if skipped and not updated:
            return await callback_query.message.edit_text(
                "⚠️ No title on your watchlist could be updated.\n\n"
                "Entries added without an IMDb / TMDb match have no status to "
                "re-check — re-add them with <code>/watch &lt;title&gt;</code> "
                "to get a resolvable entry.",
                parse_mode=ParseMode.HTML)
    await _send_watchlist(client, callback_query.message, uid, edit=True)
    return updated


def reset_refresh_state() -> None:
    """Clear the UPDATE cooldown state (tests)."""
    _last_refresh.clear()
