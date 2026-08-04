#!/usr/bin/env python3
"""
Static check: re-export chains, broken imports, and duplicate definitions.

Two gates, both run by default:

1. RE-EXPORT / BROKEN-IMPORT check — for every relative intra-package import
   `from .X import name`, the symbol must be DEFINED by X (its canonical home).
   - RE-EXPORT CHAIN: X only re-imports `name` from elsewhere — importers
     should pull it from the canonical home directly (CODEBASE_NOTES #3).
   - BROKEN IMPORT: X neither defines nor imports `name` (e.g. the old
     `from ..main import channels_col`).
   - UNKNOWN MODULE: the source module doesn't exist.

2. DUPLICATE-DEFINITION check — a module-level function/class with the same
   name must not be defined in two different modules (e.g. a helper copy).
   Class METHODS are not flagged (two classes may both define `__str__` etc.)
   and neither are dunder names (each module may have its own `__getattr__`).

Notes on what is NOT flagged:
- Absolute imports (`from datetime import ...`, third-party packages) target
  modules outside the in-repo graph.
- `from . import module` imports a submodule, not a symbol.
- PEP 562 lazy re-exports (`__getattr__` + a names tuple, e.g. the
  user-management helpers in database.py) ARE modeled: importing such a name
  from the re-exporting module is reported as a RE-EXPORT CHAIN with the
  canonical home named in the message.

Stdlib-only (ast/glob/os) so it runs in CI without installing anything.

Usage:
    python scripts/check_reexports.py            # scan repo (uses this file's dir)
    python scripts/check_reexports.py <root>     # scan an explicit project root

Exit code: 0 = clean, 1 = violations found.
"""

import ast
import glob
import os
import sys

# Modules to scan (relative to project root). main.py is included because it
# participates in the import graph.
SCAN_TARGETS = ("features", "main.py")

# Intentional re-export chains that are allowed to stay. Key format:
# "<importing_module>:<imported_name>". Keep empty unless there's a deliberate
# backward-compat re-export that importers must keep using.
ALLOWED_CHAINS = set()

# Intentional duplicate module-level definitions that are allowed to stay.
# Key format: "<module>:<name>". Keep empty — duplicates should be
# consolidated instead of allowlisted.
ALLOWED_DUPLICATES = set()


def _module_path(root, filepath):
    """Convert an absolute file path to a dotted module name relative to root.
    Returns (mod, is_init) where is_init marks a package __init__.py."""
    rel = os.path.relpath(filepath, root)
    is_init = rel.endswith("__init__.py")
    mod = rel[:-3].replace(os.sep, ".")
    if is_init:
        mod = mod[: -len(".__init__")]
    return mod, is_init


def _module_package(mod, is_init):
    """Return the package context for resolving this module's relative imports.

    A package __init__.py belongs to itself (its module name IS the package),
    so `from .config import X` in features/__init__.py resolves to
    features.config. A regular module belongs to its parent package.
    """
    if is_init:
        return mod
    if "." in mod:
        return mod.rsplit(".", 1)[0]
    return None


def _resolve_source(mod, package, node):
    """Resolve the absolute module name a relative ImportFrom points at.

    Only called for `from .x import Y` / `from ..x import Y` (level >= 1 with a
    module). Absolute imports and `from . import X` are skipped by the caller.
    """
    parts = package.split(".") if package else []
    up = node.level - 1
    base = ".".join(parts[: len(parts) - up]) if len(parts) >= up else ""
    return f"{base}.{node.module}" if base else node.module


def _lazy_reexport_names(tree):
    """Names exposed via a PEP 562 module __getattr__.

    Recognizes the pattern: a module-level tuple/list/set of string constants
    assigned near a `def __getattr__` (e.g. database.py's
    `_USER_MANAGEMENT_HELPERS = ("get_user_doc", ...)`). Returns the set of
    names so the scanner can treat them as re-exports rather than broken.
    """
    names = set()
    has_getattr = any(
        isinstance(n, ast.FunctionDef) and n.name == "__getattr__"
        for n in ast.walk(tree)
    )
    if not has_getattr:
        return names
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Tuple, ast.List, ast.Set)):
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    names.add(elt.value)
    return names


def _collect_symbols(filepath, mod, is_init):
    """Return (defined, imported_from) for a module file.

    `defined`       = names the module itself creates (defs, classes, assigns,
                      `import X` bindings).
    `imported_from` = {name: source_module} for names pulled in via
                      `from ... import ...`, plus PEP 562 lazy re-exports
                      (source_module = "<__getattr__>"). Relative import
                      sources are resolved to absolute dotted module names so
                      violation messages name the canonical home precisely.
    """
    defined = set()
    imported_from = {}
    package = _module_package(mod, is_init)
    with open(filepath, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=filepath)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    defined.add(t.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                defined.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # Resolve the source module to its absolute name (relative imports)
            # or keep the absolute name as-is (level 0 / submodule imports).
            if node.level >= 1 and node.module is not None:
                src = _resolve_source(mod, package, node)
            else:
                src = node.module or "<package>"
            for alias in node.names:
                if alias.name != "*":
                    imported_from.setdefault(alias.asname or alias.name, src)
    # PEP 562 lazy re-exports behave like re-exports for the purpose of this check
    for name in _lazy_reexport_names(tree):
        imported_from.setdefault(name, "<__getattr__>")
    return defined, imported_from


def _collect_targets(root):
    """Return the absolute paths of all modules in the scan targets."""
    targets = []
    for t in SCAN_TARGETS:
        path = os.path.join(root, t)
        if os.path.isdir(path):
            targets.extend(sorted(glob.glob(os.path.join(path, "**", "*.py"), recursive=True)))
        elif os.path.isfile(path):
            targets.append(path)
    return targets


def _module_level_defs(filepath):
    """Return {name: lineno} of module-level functions/classes (not methods)."""
    defs = {}
    with open(filepath, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=filepath)
    for node in tree.body:  # top level only — skips class methods
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("__") and node.name.endswith("__"):
                continue  # dunders (e.g. __getattr__) are legitimately per-module
            defs[node.name] = node.lineno
    return defs


def scan_duplicates(root):
    """Flag module-level functions/classes defined in two or more modules."""
    violations = []
    by_name = {}
    for filepath in _collect_targets(root):
        mod, _ = _module_path(root, filepath)
        rel = os.path.relpath(filepath, root)
        for name, lineno in _module_level_defs(filepath).items():
            if f"{mod}:{name}" in ALLOWED_DUPLICATES:
                continue
            by_name.setdefault(name, []).append((rel, lineno))
    for name, locs in sorted(by_name.items()):
        if len(locs) > 1:
            loc_str = ", ".join(f"{rel}:{lineno}" for rel, lineno in locs)
            violations.append(
                f"DUPLICATE DEFINITION: `{name}` defined in {loc_str} — consolidate "
                f"into one canonical module"
            )
    return violations


def scan(root):
    """Scan a project root; return a list of violation strings (empty = clean)."""
    violations = []

    targets = _collect_targets(root)

    # First pass: map every module -> (defined, imported_from)
    symbols = {}
    for filepath in targets:
        mod, is_init = _module_path(root, filepath)
        symbols[mod] = _collect_symbols(filepath, mod, is_init)

    # Second pass: check every RELATIVE intra-package import against the source
    # module. Absolute imports (level 0) target stdlib/third-party packages that
    # aren't part of the in-repo graph, and `from . import X` (module is None)
    # imports a submodule rather than a symbol — neither forms a re-export chain.
    for filepath in targets:
        mod, is_init = _module_path(root, filepath)
        package = _module_package(mod, is_init)
        with open(filepath, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=filepath)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level == 0 or node.module is None:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                # The symbol imported from the source is alias.name; the asname
                # is only the local binding in THIS module and must not be used
                # to look up the source's symbols.
                symbol = alias.name
                if f"{mod}:{symbol}" in ALLOWED_CHAINS:
                    continue
                src = _resolve_source(mod, package, node)
                src_defined, src_imported_from = symbols.get(src, (set(), {}))
                if symbol in src_defined:
                    continue  # canonical home — fine
                if src not in symbols:
                    violations.append(
                        f"{os.path.relpath(filepath, root)}:{node.lineno}  UNKNOWN MODULE: "
                        f"`{symbol}` imported from `{src}`, which does not exist"
                    )
                elif symbol in src_imported_from:
                    canonical = src_imported_from[symbol]
                    if canonical == "<__getattr__>":
                        hint = f"which lazily re-exports it via __getattr__ — import from the defining module directly"
                    else:
                        hint = f"which only re-imports it from {canonical} — import from {canonical} directly"
                    violations.append(
                        f"{os.path.relpath(filepath, root)}:{node.lineno}  RE-EXPORT CHAIN: "
                        f"`{symbol}` imported from `{src}`, {hint}"
                    )
                else:
                    violations.append(
                        f"{os.path.relpath(filepath, root)}:{node.lineno}  BROKEN IMPORT: "
                        f"`{symbol}` imported from `{src}`, but `{src}` neither defines "
                        f"nor imports it"
                    )
    return violations


def main(argv):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if len(argv) > 1:
        root = argv[1]

    violations = scan(root) + scan_duplicates(root)
    if violations:
        print("❌ Static check FAILED:")
        for v in violations:
            print(f"  - {v}")
        print("\nFix: import each symbol from the module that DEFINES it (its canonical")
        print("home), and consolidate duplicate definitions into one module.")
        return 1
    print("✅ Static check passed (imports resolve to canonical homes, no duplicate")
    print("   module-level definitions).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
