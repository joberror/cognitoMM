#!/usr/bin/env python3
"""
publish_telegraph.py — publish / update the MovieBot help guides on Telegra.ph.

Two pages are maintained, one per audience:

* ``user``  — the public command reference every user can open.
* ``admin`` — the admin-only reference (destructive / user-management ops).

Content for each lives in :func:`_user_sections` / :func:`_admin_sections` as
Telegra.ph "Node" JSON. On the first run a page is created; on every later run
the SAME page is edited (``editPage`` by the stored path), so each public URL
stays stable across updates.

Auth comes from ``TELEGRAPH_ACCESS_TOKEN`` (read from ``.env``). Page
paths/urls are persisted to ``telegraph_page.json`` in the repo root — commit
it so updates land on the same URLs.

The resulting URLs are written back to ``HELP_GUIDE_URL`` (user) and
``ADMIN_GUIDE_URL`` (admin) in ``.env`` / ``.env.example``. The bot's ``/help``
menu shows the user guide button on every page, and the admin guide button on
the admin section only.

Usage:
    scripts/publish_telegraph.py            # create or edit both pages
    scripts/publish_telegraph.py --role user  # only one role
    scripts/publish_telegraph.py --dry-run  # render + size check, no API call
    scripts/publish_telegraph.py --print    # dump the rendered content JSON
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "telegraph_page.json"
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE_PATH = ROOT / ".env.example"

API_BASE = "https://api.telegra.ph"
AUTHOR_NAME = "MovieBot"
# Telegra.ph limit is 64 KB for the serialized content array.
MAX_CONTENT_BYTES = 64 * 1024


# --------------------------------------------------------------------------
# Telegra.ph node helpers (https://telegra.ph/api — Node definition)
# --------------------------------------------------------------------------
def _node(tag, *children, **attrs):
    node = {"tag": tag, "children": list(children)}
    if attrs:
        node["attrs"] = attrs
    return node


def p(*children):
    return _node("p", *children)


def h3(text):
    return _node("h3", text)


def h4(text):
    return _node("h4", text)


def b(text):
    return _node("b", text)


def i(text):
    return _node("i", text)


def c(text):
    """Inline <code>."""
    return _node("code", text)


def li(*children):
    return _node("li", *children)


def ul(*items):
    return _node("ul", *items)


def hr():
    return _node("hr")


def cmd(name, *rest):
    """A list item: monospaced command + trailing description."""
    return li(c(name), *rest)


def _user_sections():
    """Return the public (user) guide as a list of (heading, [nodes]) tuples."""
    S = []

    S.append(("", [
        p("The complete command reference for MovieBot — a Telegram bot for "
          "searching, discovering and downloading movies and series."),
        p("Tap any command to copy it. Everything here is available to all "
          "users."),
    ]))

    # -- Search ------------------------------------------------------------
    S.append(("🔎 Search", [
        cmd("/search <title>", " — smart search: exact titles first, then fuzzy "
            "matches."),
        cmd("/f <title>", " — quick search; identical to ", c("/search"),
            " (shortest to type)."),
        cmd("/search -e <title>", " — exact title match only."),
        h4("Appendable filters"),
        p("Combine any of these after the title:"),
        ul(
            li(b("Year"), " — ", c("/search Dune 2021")),
            li(b("Quality"), " — ", c("480p"), ", ", c("720p"), ", ",
               c("1080p"), ", ", c("2160p"), ", ", c("4k")),
            li(b("Type"), " — ", c("movie"), " or ", c("series")),
            li(b("Language"), " — ", c("lang:hindi")),
            li(b("Subtitles"), " — ", c("subs:esub")),
            li(b("Audio"), " — ", c("audio:atmos")),
            li(b("HDR"), " — ", c("hdr"), " or ", c("hdr:dv")),
        ),
        h4("Full example"),
        p(c("/search Dune 2021 1080p movie lang:hindi")),
        p("Results show a per-title code-block list and a TMDb information "
          "block (⭐ rating · genres · IMDb). Each title gets ",
          b("Pick [n]"), " (all copies, with resolution/season filters, "
          "and a ", b("Get All"), " pack) and ", b("Get [n]"), " (latest "
          "copy)."),
    ]))

    # -- Discover ----------------------------------------------------------
    S.append(("📌 Discover", [
        cmd("/recent", " — the newest batch of indexed titles."),
        cmd("/trending", " — TMDb trending movies, shows and new releases "
            "(category buttons)."),
        cmd("/random", " — a random indexed title (poster when available)."),
        cmd("/genres", " — list every genre with counts."),
        cmd("/genres <name>", " — browse one genre, 12 per page, sortable by ",
            b("A–Z"), ", ", b("Newest"), " or ", b("Top Rated"), "."),
        cmd("/request <title>", " — request a missing title; TMDb-verified."),
        p(b("Request limits"), ": 3 pending · 1 per day · 20 global per day. "
          "Upvote an existing request instead of duplicating it. You are DM'd "
          "when your request is fulfilled."),
    ]))

    # -- Me ----------------------------------------------------------------
    S.append(("👤 Me", [
        cmd("/my_history", " — your recent searches, grouped by date."),
        cmd("/my_stat", " — your usage dashboard and premium info."),
        cmd("/watch <title>", " — add a title to your watchlist; you get a DM "
            "when it is indexed."),
        cmd("/watchlist", " — your watched titles, each with a 🔄 refresh "
            "button, plus ", b("UPDATE ALL"), "."),
        cmd("/unwatch <title>", " — remove a watched title."),
        cmd("/buy_premium", " — buy premium with Telegram Stars."),
        cmd("/help", " — this menu."),
        p(b("Watchlist limits"), ": 5 titles free / 20 premium. Watch targets "
          "are verified against TMDb; ambiguous titles open a picker."),
    ]))

    # -- Premium -----------------------------------------------------------
    S.append(("⭐ Premium", [
        p("Buy with Telegram Stars via ", c("/buy_premium"), ". Premium "
          "unlocks:"),
        ul(
            li("Watchlist up to ", b("20"), " titles (free: 5)."),
            li("Longer file retention: ", b("30 min"), " single / ",
               b("60 min"), " bulk (free: 5 / 15)."),
            li(b("Unlimited"), " daily downloads (free: 10/day)."),
            li("Premium-only features when enabled by the admin."),
        ),
    ]))

    # -- Reference ---------------------------------------------------------
    S.append(("📋 Command aliases", [
        ul(
            li(c("/f"), " = ", c("/search")),
        ),
        p(b("Also available"), ": ", c("/start"), " (welcome, with the terms "
          "gate)."),
    ]))

    S.append(("ℹ️ Good to know", [
        ul(
            li("Search accepts filters after the title (year, quality, type "
               "and the lang/subs/audio/hdr facets)."),
            li("Delivered files are auto-deleted after a tier-based delay "
               "(5 min free / 30 min premium for single files; 15 / 60 min "
               "for bulk) — save what you want to keep."),
            li("A daily download quota applies: 10/day free, unlimited for "
               "premium."),
            li("Watchlist DMs are flood-gated per title, so a whole season "
               "landing at once sends one message."),
            li("Requests and watch entries are TMDb-verified."),
        ),
        hr(),
        p("This guide is generated from the codebase notes and can be updated "
          "as new features ship. Administrators have a separate admin guide."),
    ]))

    return S


def _admin_sections():
    """Return the admin-only guide as a list of (heading, [nodes]) tuples."""
    S = []

    S.append(("", [
        p("Administrator reference for MovieBot — the admin commands, on top of "
          "everything in the user guide."),
        p("Keep this link private: it documents destructive and "
          "user-management operations."),
    ]))

    S.append(("📊 Stats", [
        cmd("/stat", " — full dashboard."),
        cmd("/quickstat", " — quick key numbers."),
        cmd("/logs [n]", " — recent audit-log entries in-chat (default 10, "
            "max 50)."),
    ]))

    S.append(("📢 Broadcast & Requests", [
        cmd("/broadcast [message]", " — send a message to all eligible users "
            "(interactive, with progress + summary)."),
        cmd("/request_list", " — paginated pending-request queue, most-voted "
            "first; mark requests done and notify requesters."),
    ]))

    S.append(("⭐ Premium", [
        cmd("/premium", " — manage premium users (add/edit/remove) and toggle "
            "premium-only feature flags (recent, request, get_all)."),
    ]))

    S.append(("📡 Channels", [
        cmd("/mc", " (alias ", c("/manage_channel"), ") — unified channel "
            "manager with action buttons."),
        cmd("/add_channel <id>", " — register a channel (raw id, t.me slug or "
            "@username)."),
        cmd("/remove_channel <id>", " — unregister a channel."),
        cmd("/index_channel", " — interactive indexing: link/forward → skip "
            "count → confirm."),
        cmd("/toggle_indexing", " — turn global auto-indexing on/off."),
        cmd("/reset_channel", " — delete one channel's indexed data "
            "(confirm)."),
        p("⚠️ Add the bot as an admin in your channels so it can index and "
          "monitor uploads."),
    ]))

    S.append(("👥 Users", [
        cmd("/user", " — unified user manager: paginated list with filters "
            "(All/Free/⭐/👑/🚫/Active/Recent), search and batch actions "
            "(promote, demote, ban, unban) with a preview + confirm step."),
        cmd("/promote <id>", " — promote to admin (hidden alias; immediate)."),
        cmd("/demote <id>", " — demote an admin."),
        cmd("/ban_user <id>", " — ban a user."),
        cmd("/unban_user <id>", " — unban a user."),
        p("The four aliases skip the preview flow — ", c("/user"),
          " is their dashboard."),
    ]))

    S.append(("🗄️ Database", [
        cmd("/update_db", " — reconcile a channel over a message range: remove "
            "orphans and index new files (progress + ETA). Also runs on a "
            "timer when ", c("DB_RESCAN_ENABLED"), " is on."),
        cmd("/manual_deletion <title>", " — search and batch-delete indexed "
            "entries."),
        cmd("/indexing_stats", " — diagnostic counters (attempts, successes, "
            "duplicates, errors)."),
        cmd("/queue", " — live ops snapshot: index-queue depth, processor "
            "liveness, prune stats, per-channel rescan cursors."),
        cmd("/reset_stats", " — reset the indexing counters."),
        cmd("/enrich [n]", " — backfill TMDb metadata (default 30, max 200)."),
        cmd("/enrich_status", " — how many entries still lack TMDb metadata."),
        cmd("/reset", " — WIPE all indexed data (CONFIRM gate)."),
    ]))

    S.append(("📋 Aliases", [
        ul(
            li(c("/mc"), " = ", c("/manage_channel")),
        ),
        p("The role aliases ", c("/promote"), ", ", c("/demote"), ", ",
          c("/ban_user"), " and ", c("/unban_user"), " are hidden from the "
          "menu on purpose — ", c("/user"), " is their dashboard."),
    ]))

    S.append(("ℹ️ Operate safely", [
        ul(
            li("Add the bot as an admin in every channel it should index or "
               "monitor."),
            li(c("/reset"), " and ", c("/reset_channel"), " are destructive — "
               "both run a CONFIRM gate."),
            li("Scheduled database rescans run automatically while ",
               c("DB_RESCAN_ENABLED"), " is on."),
        ),
        hr(),
        p("This guide is generated from the codebase notes and can be updated "
          "as new features ship."),
    ]))

    return S


# Role -> (page title, section builder, env var). The state file keys the
# stored page path/url by role.
PAGES = {
    "user": ("MovieBot — Help Guide", _user_sections, "HELP_GUIDE_URL"),
    "admin": ("MovieBot — Admin Guide", _admin_sections, "ADMIN_GUIDE_URL"),
}


def _render(sections):
    """Turn a (heading, [nodes]) list into Telegra.ph content nodes."""
    nodes = []
    for heading, body in sections:
        if heading:
            nodes.append(h3(heading))
        nodes.extend(body)
    return nodes


def build_content(role="user"):
    """Assemble the Telegra.ph content for ``role`` ("user" or "admin")."""
    return _render(PAGES[role][1]())


# --------------------------------------------------------------------------
# API + persistence
# --------------------------------------------------------------------------
def _load_dotenv():
    """Minimal .env loader (python-dotenv isn't guaranteed for a bare script)."""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _load_state():
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        # Migrate the old flat format ({path, url}) to the per-role layout so
        # the existing user page is edited rather than duplicated.
        if "path" in data and "user" not in data:
            return {"user": {"path": data.get("path"), "url": data.get("url")}}
        return data
    return {}


def _save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _upsert_env_var(path, key, value, required=False, comment=False):
    """Set ``key=value`` in ``path``, replacing an existing (optionally
    commented) line if present."""
    line = f"# {key}={value}" if comment else f"{key}={value}"
    if not path.exists():
        if not required:
            return
        path.write_text(line + "\n", encoding="utf-8")
        return
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^#?\s*{re.escape(key)}=.*$", re.M)
    if pattern.search(text):
        text = pattern.sub(line, text)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
    path.write_text(text, encoding="utf-8")


def _post(method, **payload):
    resp = requests.post(f"{API_BASE}/{method}", data=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegraph {method} failed: "
                           f"{data.get('error', data)}")
    return data["result"]


def _serialize(nodes):
    """JSON-encode the content and enforce the 64 KB page limit."""
    body = json.dumps(nodes, ensure_ascii=False)
    size = len(body.encode("utf-8"))
    if size > MAX_CONTENT_BYTES:
        raise RuntimeError(
            f"content is {size} bytes, over the {MAX_CONTENT_BYTES}-byte "
            f"Telegraph limit — split the guide into multiple pages")
    return body


def publish(access_token, role, content, dry_run=False):
    """Create the role's page the first time, edit it afterwards.

    Returns ``{path, url, bytes, _action}``. State is stored under ``role`` in
    ``telegraph_page.json`` so the two pages keep independent, stable URLs.
    """
    body = _serialize(content)
    title = PAGES[role][0]
    state = _load_state()
    entry = state.get(role) or {}
    path = entry.get("path")

    if dry_run:
        return {"path": path, "url": entry.get("url"), "dry_run": True,
                "bytes": len(body.encode("utf-8")), "_action": "would publish"}

    if path:
        result = _post(
            "editPage",
            access_token=access_token,
            path=path,
            title=title,
            content=body,
            author_name=AUTHOR_NAME,
        )
        action = "edited"
    else:
        result = _post(
            "createPage",
            access_token=access_token,
            title=title,
            content=body,
            author_name=AUTHOR_NAME,
            return_content="false",
        )
        action = "created"

    state[role] = {"path": result.get("path", path), "url": result.get("url")}
    _save_state(state)
    result = dict(result)
    result["_action"] = action
    result["bytes"] = len(body.encode("utf-8"))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=sorted(PAGES),
                        help="publish only this role (default: both)")
    parser.add_argument("--dry-run", action="store_true",
                        help="render and size-check without calling the API")
    parser.add_argument("--print", dest="print_content", action="store_true",
                        help="print the rendered content JSON and exit")
    args = parser.parse_args(argv)

    roles = [args.role] if args.role else sorted(PAGES)

    if args.print_content:
        # Print one JSON array (or an object when both roles are requested).
        dumped = {r: build_content(r) for r in roles}
        print(json.dumps(dumped[roles[0]] if len(roles) == 1 else dumped,
                         ensure_ascii=False, indent=2))
        return 0

    _load_dotenv()
    token = os.environ.get("TELEGRAPH_ACCESS_TOKEN", "").strip()

    if not token and not args.dry_run:
        print("❌ TELEGRAPH_ACCESS_TOKEN missing (set it in .env).")
        return 1

    failed = False
    for role in roles:
        content = build_content(role)
        env_var = PAGES[role][2]
        try:
            result = publish(token, role, content, dry_run=args.dry_run)
        except (requests.RequestException, RuntimeError) as exc:
            print(f"❌ {role}: publish failed: {exc}")
            failed = True
            continue

        url = result.get("url")
        print(f"✅ {role}: {result['_action']}: {url} "
              f"({result.get('bytes', '?')} bytes)")

        if not args.dry_run and url:
            _upsert_env_var(ENV_PATH, env_var, url)
            _upsert_env_var(ENV_EXAMPLE_PATH, env_var, url, comment=True)
            print(f"   {env_var} written to .env and .env.example")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())