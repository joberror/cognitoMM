---
title: CognitoMM
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

# CognitoMM Telegram Bot

This is a Telegram bot hosted on Hugging Face Spaces.

## Developer tools

```bash
make check          # run the static import check (re-export chains / broken imports / duplicate definitions)
make test           # run the full pytest suite
make install-hooks  # install the pre-commit hook (runs `make check` before each commit)
```

`make install-hooks` sets `git config core.hooksPath .githooks`; the versioned
hook at `.githooks/pre-commit` runs `scripts/check_reexports.py` whenever
`features/*.py` or `main.py` are staged. The same check runs in CI on every
push/PR via `.github/workflows/static-checks.yml`.
