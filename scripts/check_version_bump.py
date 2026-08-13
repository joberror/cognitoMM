#!/usr/bin/env python3
"""
check_version_bump.py — pre-commit gate: a new feature must ship with a bump.

Detects "new feature" signals in the STAGED diff under the app's scan targets
(features/ and main.py):

  1. new handler definitions added anywhere: `def cmd_*` / `def handle_*`
  2. new command-router entries: `elif command == '...':`
  3. new files added under features/ (a new module = new app surface)

If any signal is present, the staged diff must also touch the version constant
(BOT_VERSION in features/config.py, or __version__). Otherwise the commit is
rejected with instructions.

Why: the user-visible bot version (webapp `/` endpoint, startup banner) should
track feature additions. Bump with `make bump` (minor, default), `make
bump-patch`, `make bump-major`, or `scripts/bump_version.py --set X.Y.Z`.

Escape hatch (not recommended): SKIP_VERSION_CHECK=1 environment variable.

Wired in from `.githooks/pre-commit`; run standalone to check the current
staging area (e.g. `make check` companions in CI can call it too).
"""

import os
import re
import subprocess
import sys
from pathlib import Path

# New handler definition added: e.g. "  async def cmd_random(...):"
HANDLER_RE = re.compile(r"^\+\s*(?:async\s+)?def\s+(?:cmd|handle)_")
# New router branch added: e.g. "    elif command == 'genres':"
ROUTER_RE = re.compile(r"^\+\s*elif\s+command\s*==")
# A version line changed in the staged diff (config.py BOT_VERSION or
# __init__.py __version__). re.M is REQUIRED: the diff text starts with
# 'diff --git ...', so without line-anchoring the ^[+-] never matches.
VERSION_RE = re.compile(r"^[+-].*(?:BOT_VERSION|__version__)", re.M)


def added_files(name_status_text: str) -> list:
    """Return paths of newly-added files (status 'A') in the name-status text."""
    out = []
    for line in name_status_text.splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        status, path = parts[0], parts[-1]
        if status.startswith("A"):
            out.append(path)
    return out


def new_feature_lines(diff_text: str) -> list:
    """Return added diff lines that look like new handlers or router entries."""
    out = []
    for line in diff_text.splitlines():
        if HANDLER_RE.match(line) or ROUTER_RE.match(line):
            out.append(line)
    return out


def version_bumped(version_diff_text: str) -> bool:
    """True if the staged diff touches the version constant."""
    return bool(VERSION_RE.search(version_diff_text))


def check(diff_text: str, name_status_text: str, version_diff_text: str):
    """Evaluate the gate. Returns (ok, reasons) where reasons lists violations."""
    added = added_files(name_status_text)
    feature_lines = new_feature_lines(diff_text)

    # New module under features/ is app-surface change (feature or refactor
    # that ships a new version either way).
    new_modules = [p for p in added if p.startswith("features/")]

    if not feature_lines and not new_modules:
        return True, []

    if version_bumped(version_diff_text):
        return True, []

    reasons = []
    if feature_lines:
        reasons.append(f"new handler/router lines added ({len(feature_lines)})")
    if new_modules:
        reasons.append(f"new module(s) added: {', '.join(new_modules)}")
    return False, reasons


def _git(args: list) -> str:
    root = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    proc = subprocess.run(
        ["git", "-C", root, *args],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout


def main(argv=None) -> int:
    if os.environ.get("SKIP_VERSION_CHECK") == "1":
        print("⏭️  Version-bump check skipped (SKIP_VERSION_CHECK=1)")
        return 0

    try:
        diff_text = _git(["diff", "--cached", "--unified=0", "--", "features/", "main.py"])
        name_status = _git(["diff", "--cached", "--name-status", "--", "features/", "main.py"])
        version_diff = _git(
            ["diff", "--cached", "--unified=0", "--",
             "features/config.py", "features/__init__.py"]
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠️  Not a git repo / git unavailable — skipping version-bump check")
        return 0

    ok, reasons = check(diff_text, name_status, version_diff)
    if ok:
        print("✅ Version-bump check passed (no new feature, or version bumped).")
        return 0

    print("❌ New feature detected but the bot version was NOT bumped in this commit:")
    for r in reasons:
        print(f"   • {r}")
    print()
    print("   Bump the version before committing:")
    print("     make bump          # minor bump (new feature)")
    print("     make bump-patch    # patch bump (small change / bugfix)")
    print("   then stage it and commit again:")
    print("     git add features/config.py LATEST_RELEASE")
    print("   (bypass with SKIP_VERSION_CHECK=1 — not recommended)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
