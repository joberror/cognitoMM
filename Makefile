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

.PHONY: check test deps verify install-hooks

check:
	python scripts/check_reexports.py

deps:
	pip install -r requirements.txt

test: deps
	python -m pytest tests/ -q

verify: check test
	@echo "✅ verify: static check + pytest both passed"

install-hooks:
	git config core.hooksPath .githooks
	@echo "✅ Pre-commit hook installed (core.hooksPath = .githooks)"
	@echo "   It runs 'python scripts/check_reexports.py' before each commit."
