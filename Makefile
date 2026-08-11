# Developer convenience targets. Mirrors what CI runs
# (.github/workflows/static-checks.yml):
#
#   make check     run the static import check (re-export chains / broken
#                  imports / duplicate definitions)   -> CI: reexport-check
#   make test      install deps, then run the full pytest suite
#                                                     -> CI: tests job
#   make deps      install Python dependencies (pip install -r requirements.txt)
#   make verify    run everything CI gates on: check + test
#   make install-hooks  install the pre-commit hook (git config core.hooksPath)
#
# Python interpreter: prefer the project virtualenv (.venv) — it holds
# pyroblack — and fall back to the plain `python` on PATH (CI installs deps
# into the runner's python, so there is no .venv there).

PYTHON := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python; fi)
PIP    := $(shell if [ -x .venv/bin/pip ]; then echo .venv/bin/pip; else echo pip; fi)

.PHONY: check test deps verify install-hooks

check:
	$(PYTHON) scripts/check_reexports.py

deps:
	$(PIP) install -r requirements.txt

test: deps
	$(PYTHON) -m pytest tests/ -q

verify: check test
	@echo "✅ verify: static check + pytest both passed"

install-hooks:
	git config core.hooksPath .githooks
	@echo "✅ Pre-commit hook installed (core.hooksPath = .githooks)"
	@echo "   It runs '$(PYTHON) scripts/check_reexports.py' before each commit."
