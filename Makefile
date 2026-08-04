# Developer convenience targets.
#
#   make check          run the static import check (re-export chains /
#                       broken imports / duplicate definitions)
#   make test           run the full pytest suite
#   make install-hooks  install the pre-commit hook (git config core.hooksPath)

.PHONY: check test install-hooks

check:
	python scripts/check_reexports.py

test:
	python -m pytest tests/ -q

install-hooks:
	git config core.hooksPath .githooks
	@echo "✅ Pre-commit hook installed (core.hooksPath = .githooks)"
	@echo "   It runs 'python scripts/check_reexports.py' before each commit."
