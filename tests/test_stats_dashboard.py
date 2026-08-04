#!/usr/bin/env python3
"""
Test: Orphan Prune stats exposure in the statistics module

Verifies features/statistics.py surfaces prune_stats in all three views:

1. format_stats_output() - the /stat dashboard renders the
   "Orphan Prune (channel cleanup)" block: header, Runs, formatted Last Run,
   FloodWait pause suffix, Last Error line, Verified/Deleted/Access-Skipped,
   Total Deleted, and the Indexing "Errors" line continues the tree (┠)
   exactly once. Without prune data the block is hidden and the "Errors"
   line closes the tree (┖) exactly once.
2. format_quick_stats_output() - /quickstat shows two compact prune lines,
   hidden until the first run.
3. export_stats_csv() - CSV export includes a full Prune category, also
   hidden until the first run.

These are pure formatting functions, so no DB/Telegram access is needed.
"""

import sys
import os
import asyncio

# Ensure project root on path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from features.statistics import format_stats_output, format_quick_stats_output, export_stats_csv

# ---------------------------
# Fixtures
# ---------------------------

BASE_STATS = {
    "bot_info": {"bot_name": "Test Bot", "bot_username": "testbot", "bot_id": 1},
    "indexing_stats": {
        "total_attempts": 5,
        "successful_inserts": 4,
        "duplicate_errors": 0,
        "other_errors": 1,
    },
    "total_users": 1,
    "active_users_7d": 1,
    "premium_users": 0,
    "admin_users": 0,
    "banned_users": 0,
    "total_content": 1,
    "total_movies": 1,
    "total_series": 0,
    "total_logs": 0,
    "db_estimated_size": 1000,
    "pending_requests": 0,
    "completed_requests": 0,
    "total_searches": 0,
    "avg_searches_per_day": 0,
}

PRUNE_STATS = {
    "runs": 3,
    "total_deleted": 12,
    "total_skipped_access": 2,
    "last_run": "2026-08-03T12:00:00+00:00",
    "last_duration": 1.23,
    "last_verified": 100,
    "last_deleted": 4,
    "last_skipped_access": 1,
    "last_paused": True,
    "last_error": "cursor failed: boom",
}


def _errors_lines(lines):
    """Lines that render the Indexing Performance 'Errors' metric."""
    return [l for l in lines if "• Errors:" in l]


# ---------------------------
# Test Cases
# ---------------------------

def test_block_with_data():
    out = format_stats_output({**BASE_STATS, "prune_stats": dict(PRUNE_STATS)})
    lines = out.split("\n")

    assert any("Orphan Prune (channel cleanup)" in l for l in lines), "block header missing"
    assert any("Runs: 3" in l for l in lines)
    assert any("Last Run: 2026-08-03 12:00 UTC · 1.23s, FloodWait Paused" in l for l in lines)
    assert any("⚠️ Last Error: cursor failed: boom" in l for l in lines)
    assert any(
        "Verified 100" in l and "Deleted 4" in l and "Access-Skipped 1" in l
        for l in lines
    ), "verified/deleted/access-skipped line missing"
    assert any("Total Deleted: 12" in l for l in lines)

    # Indexing Errors line continues the tree into the prune block, exactly once
    errors_lines = _errors_lines(lines)
    assert len(errors_lines) == 1, f"Errors line must appear exactly once: {errors_lines}"
    assert errors_lines[0].startswith("┠"), "Errors should use ┠ when prune block follows"


def test_block_without_data():
    out = format_stats_output({**BASE_STATS, "prune_stats": {}})
    lines = out.split("\n")

    assert not any("Orphan Prune" in l for l in lines), "prune block should be hidden"
    # Indexing Errors line closes the tree, exactly once
    errors_lines = _errors_lines(lines)
    assert len(errors_lines) == 1, f"Errors line must appear exactly once: {errors_lines}"
    assert errors_lines[0].startswith("┖"), "Errors should use ┖ when no prune block"


def test_block_without_pause_or_error():
    stats = dict(PRUNE_STATS)
    stats["last_paused"] = False
    stats["last_error"] = None
    out = format_stats_output({**BASE_STATS, "prune_stats": stats})
    lines = out.split("\n")

    assert any("Orphan Prune (channel cleanup)" in l for l in lines)
    assert not any("FloodWait Paused" in l for l in lines), "pause suffix should be absent"
    assert not any("Last Error" in l for l in lines), "error line should be absent"
    # Last Run still rendered without the pause suffix
    assert any("Last Run: 2026-08-03 12:00 UTC · 1.23s" in l for l in lines)


def test_block_appears_on_first_run_error():
    # last_run set but runs == 0: the very first prune run failed
    stats = {
        "runs": 0,
        "total_deleted": 0,
        "total_skipped_access": 0,
        "last_run": "2026-08-03T12:00:00+00:00",
        "last_duration": 0.5,
        "last_verified": 0,
        "last_deleted": 0,
        "last_skipped_access": 0,
        "last_paused": False,
        "last_error": "boom",
    }
    out = format_stats_output({**BASE_STATS, "prune_stats": stats})

    assert "Orphan Prune (channel cleanup)" in out, "block should appear once last_run is set"
    assert "Runs: 0" in out
    assert "⚠️ Last Error: boom" in out


def test_quickstats_with_and_without_prune_data():
    out_with = format_quick_stats_output({**BASE_STATS, "prune_stats": dict(PRUNE_STATS)})
    assert "Prune Runs:      3 | Total Deleted: 12" in out_with, "quick stats prune line missing"
    assert "100 verified · 4 deleted · 1 skipped" in out_with, "quick stats last-prune line missing"

    # Hidden both when prune_stats is empty AND when the key is absent entirely
    out_empty = format_quick_stats_output({**BASE_STATS, "prune_stats": {}})
    assert "Prune" not in out_empty, "prune line should be hidden before first run"
    out_absent = format_quick_stats_output(dict(BASE_STATS))
    assert "Prune" not in out_absent, "prune line should be hidden when key is absent"


def test_csv_export_with_and_without_prune_data():
    async def collect():
        csv_with = await export_stats_csv({**BASE_STATS, "prune_stats": dict(PRUNE_STATS)})
        csv_without = await export_stats_csv({**BASE_STATS, "prune_stats": {}})
        csv_absent = await export_stats_csv(dict(BASE_STATS))
        return csv_with, csv_without, csv_absent

    csv_with, csv_without, csv_absent = asyncio.run(collect())

    # With prune data: full category present
    assert "Prune,Runs,3" in csv_with
    assert "Prune,Total Deleted,12" in csv_with
    assert "Prune,Access-Skipped (Total),2" in csv_with
    assert "Prune,Last Run,2026-08-03T12:00:00+00:00" in csv_with
    assert "Prune,Last Verified,100" in csv_with
    assert "Prune,Last Deleted,4" in csv_with
    assert "Prune,Last Access-Skipped,1" in csv_with
    assert "Prune,Last Paused (FloodWait),True" in csv_with
    assert "Prune,Last Error,cursor failed: boom" in csv_with

    # Without prune data: no Prune rows at all (empty dict OR absent key)
    assert "Prune," not in csv_without, "prune rows should be hidden before first run"
    assert "Prune," not in csv_absent, "prune rows should be hidden when key is absent"


def main():
    test_block_with_data()
    test_block_without_data()
    test_block_without_pause_or_error()
    test_block_appears_on_first_run_error()
    test_quickstats_with_and_without_prune_data()
    test_csv_export_with_and_without_prune_data()
    print("✅ Stats dashboard prune block tests passed")
    print("   - with data: header, runs, last run, pause suffix, error, totals")
    print("   - without data: block hidden, Errors closes tree exactly once")
    print("   - no pause/error: no suffix/error lines emitted")
    print("   - first-run error: block visible with Runs: 0 + error shown")
    print("   - /quickstat: compact prune lines present/hidden")
    print("   - CSV export: Prune category rows present/hidden")


if __name__ == "__main__":
    main()
