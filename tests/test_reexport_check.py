"""
Tests for the static re-export / broken-import check (scripts/check_reexports.py).

Two responsibilities:
1. The CURRENT repo is clean — every relative intra-package import resolves to
   the module that defines the symbol (its canonical home). This pins the
   consolidation work (no re-export chains, no dead `from ..main import X`).
2. The SCANNER ITSELF works — it must detect synthetic re-export chains,
   broken imports, and unknown-module imports in a scratch fixture.

Standalone (python tests/test_reexport_check.py) and pytest-compatible.
"""

import os
import sys
import tempfile
import importlib.util

# Ensure project root is on the path so the scripts package is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

SCRIPT_PATH = os.path.join(ROOT_DIR, "scripts", "check_reexports.py")


def _load_scanner():
    spec = importlib.util.spec_from_file_location("check_reexports", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scanner = _load_scanner()


def _write(root, rel_path, content):
    path = os.path.join(root, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def test_current_repo_is_clean():
    """Both gates pass on the current repo: no re-export chains / broken /
    unknown-module imports, and no duplicate module-level definitions."""
    violations = scanner.scan(ROOT_DIR) + scanner.scan_duplicates(ROOT_DIR)
    assert violations == [], "scanner found violations:\n" + "\n".join(violations)


def test_scanner_detects_reexport_chain():
    """b.py re-imports a symbol from a.py; c.py importing it via b is a chain."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "features/a.py", "shared = 1\n")
        _write(tmp, "features/b.py", "from .a import shared\n")
        _write(tmp, "features/c.py", "from .b import shared\n")
        violations = scanner.scan(tmp)
        assert any("RE-EXPORT CHAIN" in v and "features/c.py" in v for v in violations), violations


def test_scanner_detects_broken_import():
    """Importing a name that neither defines nor imports it is broken."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "features/a.py", "x = 1\n")
        _write(tmp, "features/b.py", "from .a import nonexistent\n")
        violations = scanner.scan(tmp)
        assert any("BROKEN IMPORT" in v and "nonexistent" in v for v in violations), violations


def test_scanner_detects_unknown_module():
    """Importing from a module that doesn't exist is flagged."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "features/a.py", "from .ghost import x\n")
        violations = scanner.scan(tmp)
        assert any("UNKNOWN MODULE" in v and "ghost" in v for v in violations), violations


def test_scanner_allows_absolute_and_submodule_imports():
    """Third-party/absolute imports and `from . import module` are not chains."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "features/a.py", "import os\nfrom datetime import datetime\ndef defined_here(): pass\n")
        _write(tmp, "features/b.py", "from . import a\nfrom .a import defined_here\n")
        violations = scanner.scan(tmp)
        assert violations == [], violations


def test_scanner_allows_aliased_imports():
    """`from .x import helper as h` looks up helper in the source, not the alias."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "features/a.py", "def helper(): pass\n")
        _write(tmp, "features/b.py", "from .a import helper as h\n")
        violations = scanner.scan(tmp)
        assert violations == [], violations


def test_scanner_names_canonical_home_for_chain():
    """RE-EXPORT CHAIN messages name the canonical module to import from."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "features/canon.py", "shared = 1\n")
        _write(tmp, "features/mid.py", "from .canon import shared\n")
        _write(tmp, "features/leaf.py", "from .mid import shared\n")
        violations = scanner.scan(tmp)
        chain = [v for v in violations if "RE-EXPORT CHAIN" in v]
        assert len(chain) == 1, violations
        assert "features/canon.py" in chain[0] or "features.canon" in chain[0], chain[0]


def test_scanner_treats_pep562_getattr_reexport_as_chain():
    """A PEP 562 __getattr__ + names tuple is a re-export, not a broken import."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "features/canon.py", "def log_action(): pass\n")
        _write(
            tmp,
            "features/reexp.py",
            "_HELPERS = ('log_action',)\n"
            "def __getattr__(name):\n"
            "    if name in _HELPERS:\n"
            "        from . import canon\n"
            "        return getattr(canon, name)\n"
            "    raise AttributeError(name)\n",
        )
        _write(tmp, "features/leaf.py", "from .reexp import log_action\n")
        violations = scanner.scan(tmp)
        chain = [v for v in violations if "RE-EXPORT CHAIN" in v and "leaf.py" in v]
        assert len(chain) == 1, violations


# -------------------------
# Duplicate-definition check
# -------------------------

def test_duplicate_check_flags_same_helper_in_two_modules():
    """A helper defined in two modules is a duplicate-definition violation."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "features/a.py", "def format_size(x): return x\n")
        _write(tmp, "features/b.py", "def format_size(x): return x\n")
        violations = scanner.scan_duplicates(tmp)
        dup = [v for v in violations if "DUPLICATE DEFINITION" in v and "format_size" in v]
        assert len(dup) == 1, violations
        assert "a.py" in dup[0] and "b.py" in dup[0], dup[0]


def test_duplicate_check_ignores_unique_names():
    """Names defined in only one module are not flagged."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "features/a.py", "def unique_a(): pass\n")
        _write(tmp, "features/b.py", "def unique_b(): pass\n")
        violations = scanner.scan_duplicates(tmp)
        assert violations == [], violations


def test_duplicate_check_ignores_class_methods():
    """Two classes may each define the same method name (e.g. __str__)."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "features/a.py", "class One:\n    def __str__(self): return 'one'\n")
        _write(tmp, "features/b.py", "class Two:\n    def __str__(self): return 'two'\n")
        violations = scanner.scan_duplicates(tmp)
        assert violations == [], violations


def test_duplicate_check_ignores_module_dunders():
    """Each module may define its own __getattr__ (PEP 562), not a duplicate."""
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "features/a.py", "def __getattr__(name): raise AttributeError(name)\n")
        _write(tmp, "features/b.py", "def __getattr__(name): raise AttributeError(name)\n")
        violations = scanner.scan_duplicates(tmp)
        assert violations == [], violations


def test_duplicate_check_skips_allowlisted():
    """ALLOWED_DUPLICATES entries are exempt."""
    old = scanner.ALLOWED_DUPLICATES
    try:
        scanner.ALLOWED_DUPLICATES = {"features.b:format_size"}
        with tempfile.TemporaryDirectory() as tmp:
            _write(tmp, "features/a.py", "def format_size(x): return x\n")
            _write(tmp, "features/b.py", "def format_size(x): return x\n")
            violations = scanner.scan_duplicates(tmp)
            assert violations == [], violations
    finally:
        scanner.ALLOWED_DUPLICATES = old


if __name__ == "__main__":
    checks = [
        test_current_repo_is_clean,
        test_scanner_detects_reexport_chain,
        test_scanner_detects_broken_import,
        test_scanner_detects_unknown_module,
        test_scanner_allows_absolute_and_submodule_imports,
        test_scanner_allows_aliased_imports,
        test_scanner_names_canonical_home_for_chain,
        test_scanner_treats_pep562_getattr_reexport_as_chain,
        test_duplicate_check_flags_same_helper_in_two_modules,
        test_duplicate_check_ignores_unique_names,
        test_duplicate_check_ignores_class_methods,
        test_duplicate_check_ignores_module_dunders,
        test_duplicate_check_skips_allowlisted,
    ]
    failures = 0
    for fn in checks:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
    sys.exit(1 if failures else 0)
