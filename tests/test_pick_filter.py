#!/usr/bin/env python3
"""
Test: search pick filter view (in-place filtering, per-season picks,
resolution filters)

Pins the reworked search "Pick" flow (the old quality-chooser list was
replaced by filtering the search result message in place):

1. Pure helpers (features/search.py):
   - normalize_resolution maps quality strings to 720p/1080p/2160p
   - pick_callback builds the 6-part choose: callback data (the legacy
     5-part format is still accepted by the callback parser)
   - group_seasons / filter_copies power the season + resolution filters

2. Search result rendering:
   - build_search_page keeps dedup + formatting (shared by the initial send,
     the page:/back: callbacks and history searches)
   - build_search_keyboard: single-copy groups -> Get [n]; multi-copy groups
     -> Pick [n]; series with several seasons additionally get one
     Pick[n][Sxx] button per season - long-running series page through their
     shortcuts (S◀ / S▶) so deep seasons have one-click picks too

3. The pick filter view (build_pick_view / render_pick_view):
   - clicking Pick edits the message in place to ONLY the chosen title's
     copies (no separate quality-chooser list any more)
   - movies list every copy; series dedupe per episode (best copy wins)
   - [720p]/[1080p]/[2160p] resolution filter buttons narrow the copies
   - season buttons filter a series to one season
   - "<- Back" restores the full search results page

All handlers run against injected fakes - no real DB or Telegram access.
"""

import asyncio
import os
import sys
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Ensure project root on path so `features` is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from pyrogram.types import LinkPreviewOptions

import features.callbacks as callbacks
from features.search import (
    MAX_PICK_LINES,
    build_pick_view,
    build_search_keyboard,
    build_search_page,
    build_title_info_block,
    filter_copies,
    group_seasons,
    is_series,
    normalize_resolution,
    pick_callback,
)


# ------------------------------------------------------------------ #
# Fakes                                                               #
# ------------------------------------------------------------------ #

class FakeCallbackMsg:
    """callback_query.message - records edit_text() calls."""

    def __init__(self):
        self.edits = []

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


class FakeCallbackQuery:
    """callback_query - records answer() and edit_message_text() calls."""

    def __init__(self, data, user_id=42):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeCallbackMsg()
        self.answers = []
        self.edits = []

    async def answer(self, text, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


def movie(quality="1080p", mid=1, title="Inception", year=2010, rip="BluRay"):
    return {"title": title, "year": year, "type": "Movie", "quality": quality,
            "rip": rip, "file_size": 100, "channel_id": -1001, "message_id": mid}


def episode(season, episode, quality="1080p", mid=1, title="Show", year=2000):
    return {"title": title, "year": year, "type": "Series", "quality": quality,
            "rip": "Web", "season": season, "episode": episode,
            "file_size": 100, "channel_id": -1002, "message_id": mid}


def _series_copies(num_seasons, eps_per=2):
    """A long-running series: every season gets `eps_per` episodes."""
    copies = []
    mid = 1
    for s in range(1, num_seasons + 1):
        for e in range(1, eps_per + 1):
            copies.append(episode(s, e, mid=mid))
            mid += 1
    return copies


def _run_callback(cbq, cached):
    """Drive callback_handler with DB-free patches + a fake bulk_downloads."""
    async def run():
        with ExitStack() as stack:
            stack.enter_context(patch.object(callbacks, "bulk_downloads", cached))
            stack.enter_context(patch.object(callbacks, "has_accepted_terms",
                                             AsyncMock(return_value=True)))
            stack.enter_context(patch.object(callbacks, "should_process_command_for_user",
                                             AsyncMock(return_value=True)))
            stack.enter_context(patch("features.premium_management.is_feature_premium_only",
                                      AsyncMock(return_value=False)))
            await callbacks.callback_handler(None, cbq)
    asyncio.run(run())


def _flat_buttons(keyboard):
    """Flatten an InlineKeyboardMarkup into {label: callback_data}."""
    if keyboard is None:
        return {}
    return {b.text: b.callback_data for row in keyboard.inline_keyboard for b in row}


# ------------------------------------------------------------------ #
# Pure helpers                                                        #
# ------------------------------------------------------------------ #

def test_normalize_resolution():
    assert normalize_resolution("720p") == "720p"
    assert normalize_resolution("1080p") == "1080p"
    assert normalize_resolution("2160p") == "2160p"
    assert normalize_resolution("4K") == "2160p"
    assert normalize_resolution("2160") == "2160p"
    assert normalize_resolution("UHD") == "2160p"
    assert normalize_resolution("480p") is None
    assert normalize_resolution(None) is None
    assert normalize_resolution("") is None


def test_pick_callback_format():
    assert pick_callback("ab12cd34", 2) == "choose:ab12cd34:2:::"
    assert pick_callback("ab12cd34", 2, season=3) == "choose:ab12cd34:2:S03::"
    assert pick_callback("ab12cd34", 2, resolution="1080p") == "choose:ab12cd34:2::1080p:"
    assert pick_callback("ab12cd34", 2, season=3, resolution="2160p") == "choose:ab12cd34:2:S03:2160p:"
    assert pick_callback("ab12cd34", 2, season_page=2) == "choose:ab12cd34:2:::2"
    assert pick_callback("ab12cd34", 2, season=11, season_page=1) == "choose:ab12cd34:2:S11::1"
    assert pick_callback("ab12cd34", 2, season=11, resolution="1080p",
                         season_page=1) == "choose:ab12cd34:2:S11:1080p:1"


def test_pick_callback_and_back_prefix_for_genre():
    """Non-search surfaces reuse the pick view via a custom callback prefix."""
    assert pick_callback("gid1", 2, prefix="genre_pick") == "genre_pick:gid1:2:::"
    assert pick_callback("gid1", 2, season=3, prefix="genre_pick") == "genre_pick:gid1:2:S03::"

    text, kb = build_pick_view("gid1", 0, [movie("1080p", mid=1), movie("720p", mid=2)],
                               prefix="genre_pick", back_prefix="genre_back")
    buttons = _flat_buttons(kb)
    assert buttons.get("[1080p]") == "genre_pick:gid1:0::1080p:"
    assert buttons.get("[720p]") == "genre_pick:gid1:0::720p:"
    assert buttons.get("← Back") == "genre_back:gid1"


def test_group_seasons_and_filter_copies():
    copies = [episode(3, 1), episode(1, 1), episode(3, 2), movie(quality="1080p")]
    assert is_series(copies) is True
    assert group_seasons(copies) == [1, 3]

    season_one = filter_copies(copies, season=1)
    assert len(season_one) == 1 and season_one[0]["episode"] == 1

    res = filter_copies([movie("720p"), movie("1080p")], resolution="1080p")
    assert len(res) == 1 and res[0]["quality"] == "1080p"

    both = filter_copies([episode(2, 1, "720p"), episode(2, 2, "1080p")],
                         season=2, resolution="1080p")
    assert len(both) == 1 and both[0]["episode"] == 2


# ------------------------------------------------------------------ #
# Search page rendering                                               #
# ------------------------------------------------------------------ #

def test_build_search_page_dedup_and_format():
    results = [movie("720p", mid=1), movie("1080p", mid=2),
               episode(1, 1, mid=3)]
    text, button_data, groups, total_pages = build_search_page(results, "incep", 1)

    assert total_pages == 1
    assert 'Search : incep' in text
    # Titles Found: 2 per-title groups, 0 exact (no exact_ids passed) | 2 fuzzy
    assert "Titles Found: 2 (0 Exact | 2 Fuzzy)" in text
    assert "Files Found: 3 (Movie - 2 | Series - 1)" in text
    assert "Hint: Use\nPick button below to select title, see, and get all relative files." in text
    # One line per title with file count + latest-file info (latest = highest
    # message_id here since no indexed_at is set).
    assert "1. Inception > 2 files > Latest: 1080p | 100B | Blu-ray" in text
    assert "2. Show > 1 file > Latest: S01E01 | 1080p | 100B | WebRip" in text
    assert len(groups) == 2
    assert button_data[0]["group_size"] == 2 and button_data[0]["group_index"] == 0
    assert button_data[1]["group_size"] == 1 and button_data[1]["group_index"] == 1


def test_build_search_page_exact_fuzzy_header_counts():
    """Exact counts come from exact_ids (title starts with the query)."""
    results = [movie("1080p", mid=1, title="Lucky"),
               movie("720p", mid=2, title="Who is Lucky"),
               movie("1080p", mid=3, title="Money Luck")]
    exact_ids = {"l1"}
    results[0]["_id"] = "l1"
    results[1]["_id"] = "l2"
    results[2]["_id"] = "l3"

    text, _, _, _ = build_search_page(results, "Lucky", 1, exact_ids=exact_ids)
    assert "Titles Found: 3 (1 Exact | 2 Fuzzy)" in text
    assert "Files Found: 3 (Movie - 3 | Series - 0)" in text

    # No exact_ids -> everything counts as fuzzy
    text2, _, _, _ = build_search_page(results, "Lucky", 1)
    assert "Titles Found: 3 (0 Exact | 3 Fuzzy)" in text2


def test_build_search_keyboard_movie_pick_and_get():
    results = [movie("720p", mid=1), movie("1080p", mid=2)]

    async def build(sid, res):
        _, bd, grp, _ = build_search_page(res, "x", 1)
        with patch("features.premium_management.is_feature_premium_only",
                   AsyncMock(return_value=False)):
            return await build_search_keyboard(sid, len(res), 1, 1, grp, bd, 42, res)

    kb = asyncio.run(build("sid1234", results))
    buttons = _flat_buttons(kb)
    assert buttons.get("Pick [1]") == "choose:sid1234:0:::"
    # Every title gets BOTH Pick and Get; Get points at the LATEST copy
    # (highest message_id here, since neither copy has indexed_at).
    assert buttons.get("Get [1]") == "get_file:-1001:2"
    assert buttons.get("Get All (2)") is not None

    # Single-copy group -> plain Get button AND a Pick button
    kb2 = asyncio.run(build("sid9999", [movie("1080p", mid=9)]))
    buttons2 = _flat_buttons(kb2)
    assert buttons2.get("Get [1]") == "get_file:-1001:9"
    assert buttons2.get("Pick [1]") == "choose:sid9999:0:::"


def test_build_search_keyboard_series_season_picks():
    results = [episode(1, 1, mid=1), episode(1, 2, mid=2), episode(2, 1, mid=3)]
    _, button_data, groups, _ = build_search_page(results, "show", 1)

    async def run():
        with patch("features.premium_management.is_feature_premium_only",
                   AsyncMock(return_value=False)):
            return await build_search_keyboard("sid1234", 3, 1, 1, groups, button_data, 42, results)
    kb = asyncio.run(run())

    buttons = _flat_buttons(kb)
    assert buttons.get("Pick[1][S01]") == "choose:sid1234:0:S01::"
    assert buttons.get("Pick[1][S02]") == "choose:sid1234:0:S02::"
    assert buttons.get("Pick [1]") == "choose:sid1234:0:::"


# ------------------------------------------------------------------ #
# Pick filter view                                                    #
# ------------------------------------------------------------------ #

def test_build_search_keyboard_season_paging():
    """Results-list season shortcuts page per group (S◀/S▶) for long series.

    NOTE: build_search_page slices a page to RESULTS_PER_PAGE (9) copies, so a
    single group can hold at most 9 distinct seasons - the results paging thus
    covers S06-S09 on page 1 (deeper seasons are one Pick-click away in the
    pick view, which pages without that cap)."""
    results = [episode(s, 1, mid=s) for s in range(1, 10)]  # S01..S09, one group
    _, button_data, groups, _ = build_search_page(results, "show", 1)

    async def run(season_pages=None):
        with patch("features.premium_management.is_feature_premium_only",
                   AsyncMock(return_value=False)):
            return await build_search_keyboard("sid1234", 9, 1, 1, groups,
                                               button_data, 42, results,
                                               season_pages=season_pages)

    # Page 0: S01-S05 + S▶ (no S◀)
    b = _flat_buttons(asyncio.run(run()))
    assert b.get("Pick[1][S01]") == "choose:sid1234:0:S01::"
    assert b.get("Pick[1][S05]") == "choose:sid1234:0:S05::"
    assert b.get("Pick[1][S06]") is None
    assert b.get("S▶") == "page:sid1234:1:0:1"
    assert b.get("S◀") is None

    # Page 1: S06-S09 + S◀ only (no next page)
    b1 = _flat_buttons(asyncio.run(run({0: 1})))
    assert b1.get("Pick[1][S06]") == "choose:sid1234:0:S06::"
    assert b1.get("Pick[1][S09]") == "choose:sid1234:0:S09::"
    assert b1.get("Pick[1][S01]") is None
    assert b1.get("S◀") == "page:sid1234:1:0:0"
    assert b1.get("S▶") is None


def test_build_search_keyboard_clamps_stale_season_page():
    """An out-of-range stored season page clamps to the last valid page."""
    results = [episode(s, 1, mid=s) for s in range(1, 10)]  # S01..S09
    _, button_data, groups, _ = build_search_page(results, "show", 1)

    async def run(sp):
        with patch("features.premium_management.is_feature_premium_only",
                   AsyncMock(return_value=False)):
            return await build_search_keyboard("sid1234", 9, 1, 1, groups,
                                               button_data, 42, results,
                                               season_pages=sp)
    # 99 clamps to the last page (1) instead of an empty shortcut row
    b = _flat_buttons(asyncio.run(run({0: 99})))
    assert b.get("Pick[1][S06]") == "choose:sid1234:0:S06::"
    assert b.get("Pick[1][S09]") == "choose:sid1234:0:S09::"
    assert b.get("S◀") == "page:sid1234:1:0:0"
    assert b.get("S▶") is None


def test_build_search_keyboard_few_seasons_no_paging():
    """Groups with <= MAX_SEASON_BUTTONS seasons get no S◀/S▶ buttons."""
    results = [episode(1, 1, mid=1), episode(1, 2, mid=2), episode(2, 1, mid=3)]
    _, button_data, groups, _ = build_search_page(results, "show", 1)

    async def run():
        with patch("features.premium_management.is_feature_premium_only",
                   AsyncMock(return_value=False)):
            return await build_search_keyboard("sid1234", 3, 1, 1, groups,
                                               button_data, 42, results)
    b = _flat_buttons(asyncio.run(run()))
    assert b.get("Pick[1][S01]") is not None
    assert b.get("Pick[1][S02]") is not None
    assert b.get("S◀") is None and b.get("S▶") is None


def test_page_callback_season_paging():
    """page: with a group index advances that group's season shortcuts in place."""
    results = [episode(s, 1, mid=s) for s in range(1, 10)]  # S01..S09, one group
    cached = {"sid1234": {"user_id": 42, "results": results, "query": "show",
                          "page": 1, "created_at": datetime.now(timezone.utc)}}
    cbq = FakeCallbackQuery(data="page:sid1234:1:0:1", user_id=42)
    _run_callback(cbq, cached)

    assert cbq.edits, "season paging must re-render the results page"
    text, kwargs = cbq.edits[0]
    assert 'Search : show' in text
    buttons = _flat_buttons(kwargs["reply_markup"])
    assert buttons.get("Pick[1][S06]") == "choose:sid1234:0:S06::"
    assert buttons.get("Pick[1][S09]") == "choose:sid1234:0:S09::"
    assert buttons.get("Pick[1][S01]") is None  # advanced to page 1
    assert buttons.get("S◀") == "page:sid1234:1:0:0"
    assert buttons.get("S▶") is None
    assert any(a[0] == "🎬 More seasons" for a in cbq.answers)
    assert cached["sid1234"]["season_pages"] == {0: 1}  # state persisted


def test_page_callback_legacy_3_part_data():
    """Plain page navigation (3-part data) still works and resets no state."""
    results = [movie("1080p", mid=1), movie("1080p", mid=2)]
    cached = {"sid1234": {"user_id": 42, "results": results, "query": "q",
                          "page": 1, "created_at": datetime.now(timezone.utc)}}
    cbq = FakeCallbackQuery(data="page:sid1234:1", user_id=42)
    _run_callback(cbq, cached)

    assert cbq.edits
    text, _ = cbq.edits[0]
    assert "Titles Found: 1 (0 Exact | 1 Fuzzy)" in text
    assert "season_pages" not in cached["sid1234"]


def test_build_pick_view_movie_lists_every_copy():
    copies = [movie("720p", mid=1), movie("1080p", mid=2)]
    text, kb = build_pick_view("sid1234", 0, copies)

    assert "🎞️ **Inception** (2010)" in text
    assert "2 copies" in text
    # Pick-view lines carry Title (Year) - Size | Rip | Resolution in a code block
    assert "1. Inception (2010) - 100B | Blu-ray | 720p" in text
    assert "2. Inception (2010) - 100B | Blu-ray | 1080p" in text
    assert "```" in text

    buttons = _flat_buttons(kb)
    assert buttons.get("Get [1]") == "get_file:-1001:1"
    assert buttons.get("Get [2]") == "get_file:-1001:2"
    assert buttons.get("[720p]") == "choose:sid1234:0::720p:"
    assert buttons.get("[1080p]") == "choose:sid1234:0::1080p:"
    assert buttons.get("[2160p]") is None  # only resolutions present are shown
    assert buttons.get("← Back") == "back:sid1234"


def test_build_pick_view_movie_resolution_filter():
    copies = [movie("720p", mid=1), movie("1080p", mid=2)]
    text, kb = build_pick_view("sid1234", 0, copies, resolution="720p")

    assert "· 720p" in text
    assert "1 copy" in text
    assert "1. Inception (2010) - 100B | Blu-ray | 720p" in text
    assert "| 1080p" not in text

    buttons = _flat_buttons(kb)
    assert buttons.get("[720p] ✓") == "choose:sid1234:0:::"  # active -> toggle off
    assert buttons.get("[1080p]") == "choose:sid1234:0::1080p:"


def test_build_pick_view_series_seasons_and_episode_dedup():
    copies = [
        episode(1, 1, "1080p", mid=1),
        episode(1, 1, "720p", mid=2),   # duplicate of S01E01 -> best wins
        episode(1, 2, "1080p", mid=3),
        episode(2, 1, "1080p", mid=4),
        episode(2, 2, "720p", mid=5),
    ]
    text, kb = build_pick_view("sid1234", 0, copies)

    assert "🎞️ **Show** (2000)" in text
    assert "5 copies across 2 seasons" in text
    # Episode lines dedupe (best copy wins) with the pick-view format
    assert "1. Show (2000) - S01E01 | 100B | WebRip | 1080p 🔁+1" in text
    assert "2. Show (2000) - S01E02 | 100B | WebRip | 1080p" in text
    assert "3. Show (2000) - S02E01 | 100B | WebRip | 1080p" in text
    assert "4. Show (2000) - S02E02 | 100B | WebRip | 720p" in text

    buttons = _flat_buttons(kb)
    assert buttons.get("S01") == "choose:sid1234:0:S01::"
    assert buttons.get("S02") == "choose:sid1234:0:S02::"
    # best copy of S01E01 (1080p) drives the Get button
    assert buttons.get("Get [S01E01]") == "get_file:-1002:1"

    # Season filter narrows the list to one season
    text2, kb2 = build_pick_view("sid1234", 0, copies, season=2)
    assert "· S02" in text2
    assert "2 copies" in text2
    assert "S01E01" not in text2
    buttons2 = _flat_buttons(kb2)
    assert buttons2.get("S02 ✓") == "choose:sid1234:0:::"  # active -> toggle off


def test_build_pick_view_caps_long_episode_lists():
    copies = [episode(1, i, mid=i) for i in range(1, MAX_PICK_LINES + 20)]
    text, kb = build_pick_view("sid1234", 0, copies)
    assert f"showing first {MAX_PICK_LINES}" in text
    get_count = sum(1 for row in kb.inline_keyboard for b in row
                    if b.text.startswith("Get ["))
    assert get_count == MAX_PICK_LINES


def test_build_pick_view_series_without_season_lists_copies():
    """A series group with no season/episode metadata must still render its
    copies (regression: the episode-key filter used to drop them entirely)."""
    copies = [
        {"title": "Pack", "year": 2001, "type": "Series", "quality": "1080p",
         "rip": "Web", "file_size": 100, "channel_id": -1002, "message_id": 1},
        {"title": "Pack", "year": 2001, "type": "Series", "quality": "720p",
         "rip": "Web", "file_size": 100, "channel_id": -1002, "message_id": 2},
    ]
    text, kb = build_pick_view("sid1234", 0, copies)
    assert "2 copies" in text
    assert "1. Pack (2001) - 100B | WebRip | 1080p" in text
    assert "2. Pack (2001) - 100B | WebRip | 720p" in text
    buttons = _flat_buttons(kb)
    assert buttons.get("Get [1]") == "get_file:-1002:1"
    assert buttons.get("Get [2]") == "get_file:-1002:2"


def test_build_pick_view_season_paging():
    """Long-running series page through the seasons instead of capping at 10:
    page 1 shows S01-S10 + a next-page button, page 2 shows the rest + prev."""
    copies = _series_copies(15)  # S01..S15

    text, kb = build_pick_view("sid1234", 0, copies)
    buttons = _flat_buttons(kb)
    assert buttons.get("S01") == "choose:sid1234:0:S01::"
    assert buttons.get("S10") == "choose:sid1234:0:S10::"
    assert buttons.get("S11") is None  # page 2
    assert buttons.get("S▶") == "choose:sid1234:0:::1"  # next page (season cleared)
    assert buttons.get("S◀") is None
    assert "S01–S10 shown (page 1/2)" in text

    # Page 2: S11..S15 + prev paging, no next
    text2, kb2 = build_pick_view("sid1234", 0, copies, season_page=1)
    buttons2 = _flat_buttons(kb2)
    assert buttons2.get("S11") == "choose:sid1234:0:S11::1"
    assert buttons2.get("S15") == "choose:sid1234:0:S15::1"
    assert buttons2.get("S16") is None
    assert buttons2.get("S◀") == "choose:sid1234:0:::"  # page 0 encodes empty
    assert buttons2.get("S▶") is None
    assert "S11–S15 shown (page 2/2)" in text2


def test_build_pick_view_season_paging_snaps_to_active_season():
    """A season filter whose season lives on another page snaps the view there."""
    copies = _series_copies(15)
    text, kb = build_pick_view("sid1234", 0, copies, season=13)
    buttons = _flat_buttons(kb)
    # The active S13 button toggles the season filter OFF (no S13 in data),
    # staying on page 2; a non-active S13 would clear to page 0.
    assert buttons.get("S13 ✓") == "choose:sid1234:0:::1"
    assert buttons.get("S◀") == "choose:sid1234:0:::"  # page 0 encodes empty
    assert buttons.get("S▶") is None
    assert "S11–S15 shown (page 2/2)" in text


def test_build_pick_view_resolution_filter_keeps_season_page():
    """Filtering by resolution from season page 2 must not jump back to page 1
    (regression: the resolution row used to drop the season page)."""
    copies = _series_copies(15)
    text, kb = build_pick_view("sid1234", 0, copies, season_page=1)
    buttons = _flat_buttons(kb)
    assert buttons.get("[1080p]") == "choose:sid1234:0::1080p:1"


def test_choose_callback_season_paging():
    """The choose: callback carries the season page through to the render."""
    groups = [_series_copies(15)]
    cached = {"sid1234": {"user_id": 42, "results": groups[0], "groups": groups,
                          "query": "show", "page": 1,
                          "created_at": datetime.now(timezone.utc)}}
    cbq = FakeCallbackQuery(data="choose:sid1234:0:::1", user_id=42)  # page 2
    _run_callback(cbq, cached)

    text, _ = cbq.message.edits[0]
    assert "S11–S15 shown (page 2/2)" in text


def test_choose_callback_legacy_5_part_data():
    """Pre-paging choose: callbacks (5 parts, no page) still render."""
    groups = [[episode(1, 1, mid=1), episode(2, 1, mid=2)]]
    cached = {"sid1234": {"user_id": 42, "results": groups[0], "groups": groups,
                          "query": "show", "page": 1,
                          "created_at": datetime.now(timezone.utc)}}
    cbq = FakeCallbackQuery(data="choose:sid1234:0::", user_id=42)
    _run_callback(cbq, cached)

    assert cbq.message.edits
    text, _ = cbq.message.edits[0]
    assert "🎞️ **Show** (2000)" in text


def test_filter_copies_coerces_string_seasons():
    """Seasons stored as strings still match the int season filters."""
    copies = [episode(2, 1, mid=1), episode(3, 1, mid=2)]
    copies[0]["season"] = "2"  # string season in the DB
    assert len(filter_copies(copies, season=2)) == 1
    assert group_seasons(copies) == [2, 3]


def test_build_search_page_latest_copy_wins_by_indexed_at():
    """The Latest: line and the Get [n] button target the most recently
    indexed copy of the title (not the best quality)."""
    from datetime import datetime, timedelta, timezone

    newer = movie("720p", mid=1)
    older = movie("1080p", mid=2)
    naive = movie("2160p", mid=3)  # naive timestamp must not crash the sort
    now = datetime.now(timezone.utc)
    newer["indexed_at"] = now
    older["indexed_at"] = now - timedelta(days=2)
    naive["indexed_at"] = datetime(2020, 1, 1)  # naive, clearly oldest
    results = [newer, older, naive]  # same title "Inception" -> one group

    text, button_data, groups, _ = build_search_page(results, "incep", 1)
    assert "1. Inception > 3 files > Latest: 720p | 100B | Blu-ray" in text
    assert button_data[0]["channel_id"] == -1001
    assert button_data[0]["message_id"] == 1  # the NEWER (720p) copy


def test_build_title_info_block_renders_meta():
    """Title(s) Information lines carry year + rating/genres/IMDb when the
    TMDb meta is available, and degrade to year-only without one."""
    groups = [[movie("1080p", mid=1, title="Lucky", year=2025)],
              [movie("1080p", mid=2, title="No Meta", year=2010)]]
    metas = {0: {"rating": 6.8, "genres": ["Animation", "Action"],
                 "imdb_id": "tt1234567"},
             1: None}

    block = build_title_info_block(groups, 1, metas)
    assert "Title(s) Information" in block
    assert "1. Lucky (Movie) - 2025 . ⭐️ 6.8 · 🎭 Animation, Action" in block
    assert "[IMDb](https://imdb.com/title/tt1234567)" in block
    assert "2. No Meta (Movie) - 2010" in block
    assert ". ⭐️" not in block.split("2. No Meta")[1]  # no stray separator


def test_page_callback_preserves_title_info():
    """Pagination must NOT clear the Title(s) Information block: metas for
    previously-seen pages are reused and only the new page's titles fetch."""
    results = [movie("1080p", mid=i, title=f"T{i}", year=2000 + i)
               for i in range(1, 11)]  # 10 distinct titles -> 2 pages (9 + 1)
    cached = {
        "sid1234": {
            "user_id": 42,
            "results": results,
            "groups": [[r] for r in results],
            "query": "t",
            "page": 1,
            "exact_ids": set(),
            "metas": {i: None for i in range(9)},  # page 1 already fetched
            "created_at": datetime.now(timezone.utc),
        }
    }
    cbq = FakeCallbackQuery(data="page:sid1234:2", user_id=42)

    async def run():
        with ExitStack() as stack:
            stack.enter_context(patch.object(callbacks, "bulk_downloads", cached))
            stack.enter_context(patch.object(callbacks, "has_accepted_terms",
                                             AsyncMock(return_value=True)))
            stack.enter_context(patch.object(callbacks, "should_process_command_for_user",
                                             AsyncMock(return_value=True)))
            stack.enter_context(patch("features.premium_management.is_feature_premium_only",
                                      AsyncMock(return_value=False)))
            # Only the missing page-2 index (9) should be fetched.
            stack.enter_context(patch("features.search._fetch_metas",
                                      AsyncMock(return_value={9: None})))
            await callbacks.callback_handler(None, cbq)
    asyncio.run(run())

    assert cbq.edits
    text, _ = cbq.edits[0]
    assert "Title(s) Information" in text, "title info must survive pagination"
    assert "10. T10 (Movie) - 2010" in text
    assert "Page 2/2" in text
    assert cached["sid1234"]["metas"][9] is None  # merged into the stored metas


# ------------------------------------------------------------------ #
# Callback wiring (choose: / back:)                                  #
# ------------------------------------------------------------------ #

def test_choose_callback_filters_in_place():
    cached = {
        "sid1234": {
            "user_id": 42,
            "results": [movie("720p", mid=1), movie("1080p", mid=2)],
            "groups": [[movie("720p", mid=1), movie("1080p", mid=2)]],
            "query": "incep",
            "page": 1,
            "created_at": datetime.now(timezone.utc),
        }
    }
    cbq = FakeCallbackQuery(data="choose:sid1234:0:::", user_id=42)
    _run_callback(cbq, cached)

    assert cbq.message.edits, "pick must edit the search message in place"
    text, kwargs = cbq.message.edits[0]
    assert "🎞️ **Inception** (2010)" in text
    assert "```" in text  # pick list renders as a code block (default parse mode)
    assert "parse_mode" not in kwargs
    assert isinstance(kwargs["link_preview_options"], LinkPreviewOptions)
    assert kwargs["link_preview_options"].is_disabled is True
    assert any(a[0] == "✅ Filtered to copies" for a in cbq.answers)


def test_choose_callback_season_filter_flow():
    groups = [[episode(1, 1, mid=1), episode(2, 1, mid=2)]]
    cached = {
        "sid5678": {"user_id": 42, "results": groups[0], "groups": groups,
                    "query": "show", "page": 1,
                    "created_at": datetime.now(timezone.utc)},
    }
    cbq = FakeCallbackQuery(data="choose:sid5678:0:S02::", user_id=42)
    _run_callback(cbq, cached)

    text, _ = cbq.message.edits[0]
    assert "· S02" in text
    assert "S01E01" not in text


def test_choose_callback_ownership_guard():
    cached = {
        "sid1234": {"user_id": 42, "groups": [[movie("1080p", mid=1)]],
                    "results": [movie("1080p", mid=1)], "query": "q", "page": 1,
                    "created_at": datetime.now(timezone.utc)},
    }
    cbq = FakeCallbackQuery(data="choose:sid1234:0:::", user_id=99)  # foreign user
    _run_callback(cbq, cached)

    assert any(a[0] == "🚫 This search belongs to another user." for a in cbq.answers)
    assert not cbq.message.edits


def test_back_callback_restores_search_page():
    results = [movie("720p", mid=1), movie("1080p", mid=2)]
    cached = {
        "sid1234": {"user_id": 42, "results": results,
                    "groups": [results], "query": "incep", "page": 1,
                    "created_at": datetime.now(timezone.utc)},
    }
    cbq = FakeCallbackQuery(data="back:sid1234", user_id=42)
    _run_callback(cbq, cached)

    assert cbq.edits, "back must re-render the search results page"
    text, kwargs = cbq.edits[0]
    assert 'Search : incep' in text
    assert "Titles Found: 1 (0 Exact | 1 Fuzzy)" in text
    assert kwargs["link_preview_options"].is_disabled is True
    assert any(a[0] == "← Back to results" for a in cbq.answers)


def test_back_callback_ownership_guard():
    cached = {"sid1234": {"user_id": 42, "results": [], "query": "q", "page": 1,
                          "created_at": datetime.now(timezone.utc)}}
    cbq = FakeCallbackQuery(data="back:sid1234", user_id=99)
    _run_callback(cbq, cached)

    assert any(a[0] == "❌ You can only navigate your own searches" for a in cbq.answers)
    assert not cbq.edits


# ------------------------------------------------------------------ #
# Standalone runner                                                   #
# ------------------------------------------------------------------ #

def main():
    tests = [
        test_normalize_resolution,
        test_pick_callback_format,
        test_pick_callback_and_back_prefix_for_genre,
        test_group_seasons_and_filter_copies,
        test_build_search_page_dedup_and_format,
        test_build_search_page_exact_fuzzy_header_counts,
        test_build_search_page_latest_copy_wins_by_indexed_at,
        test_build_title_info_block_renders_meta,
        test_page_callback_preserves_title_info,
        test_build_search_keyboard_movie_pick_and_get,
        test_build_search_keyboard_series_season_picks,
        test_build_search_keyboard_season_paging,
        test_build_search_keyboard_clamps_stale_season_page,
        test_build_search_keyboard_few_seasons_no_paging,
        test_page_callback_season_paging,
        test_page_callback_legacy_3_part_data,
        test_build_pick_view_movie_lists_every_copy,
        test_build_pick_view_movie_resolution_filter,
        test_build_pick_view_series_seasons_and_episode_dedup,
        test_build_pick_view_caps_long_episode_lists,
        test_build_pick_view_series_without_season_lists_copies,
        test_build_pick_view_season_paging,
        test_build_pick_view_season_paging_snaps_to_active_season,
        test_build_pick_view_resolution_filter_keeps_season_page,
        test_choose_callback_season_paging,
        test_choose_callback_legacy_5_part_data,
        test_filter_copies_coerces_string_seasons,
        test_choose_callback_filters_in_place,
        test_choose_callback_season_filter_flow,
        test_choose_callback_ownership_guard,
        test_back_callback_restores_search_page,
        test_back_callback_ownership_guard,
    ]

    # All tests are sync defs that drive asyncio.run() internally.
    for t in tests:
        t()
    print("✅ pick filter view tests passed")
    print("   - Pick filters the search result in place (no chooser list)")
    print("   - series get Pick[n][Sxx] per-season buttons")
    print("   - [720p]/[1080p]/[2160p] resolution filters")
    print("   - <- Back restores the search results page")


if __name__ == "__main__":
    main()
