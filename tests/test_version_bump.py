"""
Tests for the version-bump tooling:

- scripts/bump_version.py        — reads/validates/bumps BOT_VERSION in
  features/config.py and syncs LATEST_RELEASE.
- scripts/check_version_bump.py  — pre-commit gate: a staged commit that adds
  a new feature (new cmd_/handle_ handler, new router entry, or a new module
  under features/) must also bump the version constant.

These tests exercise the pure logic and the CLI with monkeypatched file paths —
no repo files are touched, no git commands are run.
"""

import os
import sys

# Ensure project root is on the path so the scripts package is importable
# when this file is run standalone (python tests/test_version_bump.py).
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import scripts.bump_version as bump
import scripts.check_version_bump as gate

CONFIG_TEMPLATE = '''\
# Canonical bot version (single source of truth).
BOT_VERSION = "{version}"
'''


def _config_text(version="1.1.0"):
    return CONFIG_TEMPLATE.format(version=version)


# ---------------------------------------------------------------- #
# bump_version.py — parsing / bumping logic                        #
# ---------------------------------------------------------------- #

def test_read_version():
    assert bump.read_version(_config_text("1.2.3")) == "1.2.3"


def test_read_version_missing_raises():
    try:
        bump.read_version("BOT_NAME = \"x\"\n")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_bump_parts():
    assert bump.bump("1.1.0", "minor") == "1.2.0"
    assert bump.bump("1.1.0", "patch") == "1.1.1"
    assert bump.bump("1.9.9", "minor") == "1.10.0"
    assert bump.bump("2.5.3", "major") == "3.0.0"
    assert bump.bump("1.1.0", "major") == "2.0.0"


def test_set_version_rewrites_line():
    out = bump.set_version(_config_text("1.1.0"), "2.3.4")
    assert 'BOT_VERSION = "2.3.4"' in out
    assert 'BOT_VERSION = "1.1.0"' not in out


def test_set_version_invalid_rejected():
    for bad in ("abc", "1.2", "1.2.3.4", "v1.2.3"):
        try:
            bump.set_version(_config_text(), bad)
            assert False, f"expected ValueError for {bad}"
        except ValueError:
            pass


def test_cli_dry_run_writes_nothing(tmp_path, monkeypatch):
    config = tmp_path / "config.py"
    release = tmp_path / "LATEST_RELEASE"
    config.write_text(_config_text("1.1.0"))
    monkeypatch.setattr(bump, "CONFIG_PATH", config)
    monkeypatch.setattr(bump, "RELEASE_PATH", release)

    assert bump.main(["--dry-run"]) == 0
    assert "1.1.0" in config.read_text()
    assert not release.exists()


def test_cli_patch_bump_writes_files(tmp_path, monkeypatch):
    config = tmp_path / "config.py"
    release = tmp_path / "LATEST_RELEASE"
    config.write_text(_config_text("1.1.0"))
    monkeypatch.setattr(bump, "CONFIG_PATH", config)
    monkeypatch.setattr(bump, "RELEASE_PATH", release)

    assert bump.main(["--patch"]) == 0
    assert 'BOT_VERSION = "1.1.1"' in config.read_text()
    assert release.read_text().strip() == "1.1.1"


def test_cli_set_writes_exact(tmp_path, monkeypatch):
    config = tmp_path / "config.py"
    release = tmp_path / "LATEST_RELEASE"
    config.write_text(_config_text("1.1.0"))
    monkeypatch.setattr(bump, "CONFIG_PATH", config)
    monkeypatch.setattr(bump, "RELEASE_PATH", release)

    assert bump.main(["--set", "3.0.0"]) == 0
    assert 'BOT_VERSION = "3.0.0"' in config.read_text()


# ---------------------------------------------------------------- #
# check_version_bump.py — pre-commit gate logic                    #
# ---------------------------------------------------------------- #

HANDLER_DIFF = [
    "+",
    "+    async def cmd_random(client, message):",
    "+        pass",
]
ROUTER_DIFF = [
    "+    elif command == 'genres':",
    "+        await cmd_genres(client, message)",
]
NAME_STATUS_FEATURE = [
    "A\tfeatures/foo.py",
    "M\tfeatures/commands.py",
]
NAME_STATUS_TESTS_ONLY = [
    "M\ttests/test_version_bump.py",
]

# A non-feature diff: plain function edit, no new handlers/router entries.
BORING_DIFF = [
    "-        print(\"old\")",
    "+        print(\"new\")",
]


def test_gate_passes_without_feature_changes():
    ok, reasons = gate.check("\n".join(BORING_DIFF),
                             "\n".join(NAME_STATUS_TESTS_ONLY), "")
    assert ok and not reasons


def test_gate_fails_new_handler_without_bump():
    ok, reasons = gate.check("\n".join(HANDLER_DIFF),
                             "\n".join(NAME_STATUS_FEATURE), "")
    assert not ok
    assert any("handler/router" in r for r in reasons)


def test_gate_fails_router_entry_without_bump():
    ok, reasons = gate.check("\n".join(ROUTER_DIFF),
                             "\n".join(NAME_STATUS_FEATURE), "")
    assert not ok


def test_gate_passes_new_handler_with_version_bump():
    version_diff = '-BOT_VERSION = "1.1.0"\n+BOT_VERSION = "1.2.0"\n'
    ok, _ = gate.check("\n".join(HANDLER_DIFF),
                       "\n".join(NAME_STATUS_FEATURE), version_diff)
    assert ok


def test_gate_fails_new_module_without_bump():
    ok, reasons = gate.check("", "A\tfeatures/new_module.py", "")
    assert not ok
    assert any("new_module.py" in r for r in reasons)


def test_gate_ignores_new_files_outside_features():
    ok, _ = gate.check("", "A\tscripts/bump_version.py\nA\ttests/test_x.py", "")
    assert ok


def test_added_files_parser():
    files = gate.added_files("M\tfeatures/commands.py\nA\tfeatures/foo.py\nA\ttests/t.py")
    assert files == ["features/foo.py", "tests/t.py"]


def test_version_bumped_detector():
    # Realistic diff: version line in the MIDDLE of a diff, not at position 0
    # (regression: without re.MULTILINE the ^[+-] only matched string start).
    real_diff = (
        "diff --git a/features/config.py b/features/config.py\n"
        "index 111..222 100644\n"
        "--- a/features/config.py\n"
        "+++ b/features/config.py\n"
        "@@ -10 +10 @@\n"
        "-BOT_VERSION = \"1.1.0\"\n"
        "+BOT_VERSION = \"1.2.0\"\n"
    )
    assert gate.version_bumped(real_diff)
    assert gate.version_bumped("+__version__ = \"1.1.0\"\n")
    assert not gate.version_bumped("BOT_VERSION = \"1.1.0\"\n")


def main():
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


if __name__ == "__main__":
    main()
