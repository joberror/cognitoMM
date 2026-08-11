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
make test           # install deps, then run the full pytest suite (mirrors CI's tests job)
make verify         # run everything CI gates on: check + test
make install-hooks  # install the pre-commit hook (runs `make check` before each commit)
```

`make install-hooks` sets `git config core.hooksPath .githooks`; the versioned
hook at `.githooks/pre-commit` runs `scripts/check_reexports.py` whenever
`features/*.py` or `main.py` are staged. The same check runs in CI on every
push/PR via `.github/workflows/static-checks.yml`.

## Telegram library (pyroblack)

The bot runs on **pyroblack**, the actively maintained successor to the
hydrogram/Pyrogram family. One thing to know: **pyroblack installs as the
`pyrogram` package** — `pip install pyroblack` provides `import pyrogram`, so
all imports in the codebase read `from pyrogram import ...` (`Client`, `filters`,
`types`, `handlers`, `errors`). There is no separate `pyroblack` import
namespace.

Run the bot with `./run.sh` and the developer gates with `make …` — both
prefer the project virtualenv (`.venv`, which holds pyroblack) and fall back to
the plain `python` on PATH.
