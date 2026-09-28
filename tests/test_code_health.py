#!/usr/bin/env python3
"""
Test: code-health gates (module split + lint tooling).

Pins cluster 9:

1. The /request domain lives in features/request_commands.py and is imported
   into commands.py's router (single canonical definition; commands.py must
   NOT redefine send_request_list_page).
2. The ruff lint gate is configured and clean (skipped when ruff is not
   installed, e.g. a bare interpreter without `make deps`).
3. The Makefile exposes `lint` and `verify` runs check + lint + test.

No live services.
"""

import os
import shutil
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def test_request_domain_split():
    import features.commands as commands
    import features.request_commands as request_commands

    # The canonical handlers live in request_commands...
    for name in ("cmd_request", "cmd_request_list", "send_request_list_page"):
        assert hasattr(request_commands, name), name
    # ...commands.py re-imports the router-facing handlers (identity preserved)...
    assert commands.cmd_request is request_commands.cmd_request
    assert commands.cmd_request_list is request_commands.cmd_request_list
    # ...and no longer re-exports the admin page renderer (moved, not copied).
    assert not hasattr(commands, "send_request_list_page")


def test_pyproject_ruff_config():
    with open(os.path.join(ROOT_DIR, "pyproject.toml"), encoding="utf-8") as f:
        text = f.read()
    assert "[tool.ruff]" in text, "ruff config missing"
    assert 'select = ["F", "E9"]' in text, "expected the conservative F/E9 ruleset"
    assert "features/utils.py" in text, "re-export hub ignore missing"


def test_makefile_has_lint():
    with open(os.path.join(ROOT_DIR, "Makefile"), encoding="utf-8") as f:
        makefile = f.read()
    assert "lint:" in makefile and "ruff check" in makefile, "make lint missing"
    assert "verify: check lint test" in makefile, "verify must include lint"


def test_ruff_is_clean_if_available():
    if shutil.which("ruff") is None:
        try:
            import ruff  # noqa: F401
        except ImportError:
            print("   (ruff not installed - skipping live lint)")
            return
    # Prefer `python -m ruff` so the same interpreter/venv is used.
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "features", "main.py", "scripts"],
        cwd=ROOT_DIR, capture_output=True, text=True)
    assert proc.returncode == 0, f"ruff reported issues:\n{proc.stdout}\n{proc.stderr}"


_TESTS = [
    test_request_domain_split,
    test_pyproject_ruff_config,
    test_makefile_has_lint,
    test_ruff_is_clean_if_available,
]


def main() -> int:
    failures = 0
    for fn in _TESTS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
            import traceback
            traceback.print_exc()
    print(f"\n{len(_TESTS) - failures}/{len(_TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
