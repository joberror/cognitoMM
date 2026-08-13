#!/usr/bin/env python3
"""
bump_version.py — bump the canonical bot version.

The single source of truth for the bot version is the BOT_VERSION constant in
``features/config.py`` (re-exported as ``features.__version__`` and surfaced on
the webapp ``/`` endpoint). This script edits that constant and syncs the
``LATEST_RELEASE`` file.

Usage:
    scripts/bump_version.py             # minor bump: 1.1.0 -> 1.2.0
    scripts/bump_version.py --patch     # patch bump: 1.1.0 -> 1.1.1
    scripts/bump_version.py --major     # major bump: 1.1.0 -> 2.0.0
    scripts/bump_version.py --set 2.3.4 # exact version
    scripts/bump_version.py --dry-run   # print old -> new without writing

A new feature (new command, new handler, new feature module) should ship with
a minor bump; bugfixes use a patch bump. The pre-commit hook
(scripts/check_version_bump.py) fails feature commits that forget the bump.
"""

import argparse
import re
import sys
from pathlib import Path

# Repo root regardless of where the script is invoked from.
ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "features" / "config.py"
RELEASE_PATH = ROOT / "LATEST_RELEASE"

# Matches:  BOT_VERSION = "1.2.3"
VERSION_RE = re.compile(r'^BOT_VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"', re.M)
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def read_version(config_text: str) -> str:
    """Extract the current version from config.py source text."""
    m = VERSION_RE.search(config_text)
    if not m:
        raise ValueError("BOT_VERSION = \"x.y.z\" not found in features/config.py")
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"


def bump(current: str, part: str) -> str:
    """Return current version with `part` (major|minor|patch) incremented."""
    major, minor, patch = (int(x) for x in current.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"unknown bump part: {part}")


def set_version(config_text: str, new_version: str) -> str:
    """Rewrite the BOT_VERSION line in config.py source text."""
    if not SEMVER_RE.match(new_version):
        raise ValueError(f"invalid version {new_version!r} (expected X.Y.Z)")
    if not VERSION_RE.search(config_text):
        raise ValueError("BOT_VERSION = \"x.y.z\" not found in features/config.py")
    return VERSION_RE.sub(f'BOT_VERSION = "{new_version}"', config_text, count=1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Bump the canonical bot version (features/config.py + LATEST_RELEASE)."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--patch", action="store_true", help="increment patch (bugfix)")
    group.add_argument("--major", action="store_true", help="increment major")
    group.add_argument("--set", metavar="X.Y.Z", help="set an exact version")
    parser.add_argument("--dry-run", action="store_true",
                        help="print old -> new without writing any files")
    args = parser.parse_args(argv)

    if args.set:
        if not SEMVER_RE.match(args.set):
            parser.error(f"invalid version {args.set!r} (expected X.Y.Z)")
        new_version = args.set
    else:
        part = "major" if args.major else ("patch" if args.patch else "minor")
        try:
            current = read_version(CONFIG_PATH.read_text(encoding="utf-8"))
        except ValueError as e:
            parser.error(str(e))
        new_version = bump(current, part)

    current = read_version(CONFIG_PATH.read_text(encoding="utf-8"))

    if args.dry_run:
        print(f"would bump: {current} -> {new_version}")
        return 0

    text = set_version(CONFIG_PATH.read_text(encoding="utf-8"), new_version)
    CONFIG_PATH.write_text(text, encoding="utf-8")
    RELEASE_PATH.write_text(new_version + "\n", encoding="utf-8")
    print(f"✅ bumped: {current} -> {new_version} "
          f"(updated features/config.py + LATEST_RELEASE)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
