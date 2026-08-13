---
title: CognitoMM
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: docker
pinned: false
---

# CognitoMM Telegram Bot

[![CI](https://github.com/joberror/cognitoMM/actions/workflows/static-checks.yml/badge.svg)](https://github.com/joberror/cognitoMM/actions/workflows/static-checks.yml) [![Deploy](https://github.com/joberror/cognitoMM/actions/workflows/deploy.yml/badge.svg)](https://github.com/joberror/cognitoMM/actions/workflows/deploy.yml)

This is a Telegram bot hosted on Hugging Face Spaces.

## Features

**🎬 Search & discover**
- `/search <title>` — smart search (exact + fuzzy, type/episode filters).
  Duplicate copies are deduplicated — the best quality is shown first, with a
  `Pick [n]` quality chooser to grab another copy.
- `/f <title>` — quick search · inline mode `@yourbot <query>` (poster thumbnails)
- `/recent` — newly indexed content · `/trending` — TMDb trending
- `/genres` — browse by TMDb genre (counts; `/genres <name>` lists titles)
- `/random` — surprise me: a random indexed title (poster when available)
- `/request <title>` / `/request_list` — request missing titles (rate-limited)

**👤 Your library**
- `/watch <title>` / `/unwatch <title>` — watchlist; you get a DM the moment a
  watched title (or a new copy) is indexed
- `/watchlist` — your watched titles · `/my_history` — your searches
- `/my_stat` — usage + premium info · `/premium` — premium info/management
- `/help` — full command menu

**👑 Admin**
- `/logs [n]` — recent audit-log entries (default 10, max 50)
- `/enrich [n]` — backfill TMDb metadata (poster/genres/rating/IMDb)
- `/enrich_status` — TMDb backfill progress (enriched / pending / no-match)
- `/add_channel` / `/remove_channel` / `/manage_channel` / `/index_channel`
  `/toggle_indexing` — channel management & indexing
- `/update_db` — reconcile a channel (also runs on a background schedule)
- `/manual_deletion <title>` · `/indexing_stats` · `/reset_stats`
- `/stat` / `/quickstat` — statistics dashboard (incl. prune stats, CSV export)
- `/broadcast` · `/ban_user` / `/unban_user` · `/promote` / `/demote`
- `/reset_channel` · `/reset` (full wipe, confirmed)

When `TMDB_API` is configured, search/recent/trending results carry posters,
ratings, genres, and IMDb links; newly indexed entries are enriched
automatically (`TMDB_ENRICH_INDEX=true`). See `info/commands.md` for the full
command reference and `.env` options.

## Developer tools

```bash
make check          # run the static import check (re-export chains / broken imports / duplicate definitions)
make test           # install deps, then run the full pytest suite (mirrors CI's tests job)
make verify         # run everything CI gates on: check + test
make install-hooks  # install the pre-commit hook (runs `make check` + version-bump check)
make bump           # bump the bot version (minor) before committing a new feature
make bump-patch     # bump the bot version (patch) for small changes / bugfixes
make bump-major     # bump the bot version (major)
```

`make install-hooks` sets `git config core.hooksPath .githooks`; the versioned
hook at `.githooks/pre-commit` runs `scripts/check_reexports.py` **and**
`scripts/check_version_bump.py` whenever `features/*.py` or `main.py` are
staged. The same checks run in CI on every push/PR via
`.github/workflows/static-checks.yml`.

## Versioning

The bot version lives in one place: `BOT_VERSION` in `features/config.py`
(re-exported as `features.__version__`, shown on the webapp `/` endpoint and in
the startup banner). **A new feature must ship with a version bump** — the
pre-commit hook rejects commits that add a new command/handler/module without
one:

```bash
make bump          # new feature  → 1.2.0
make bump-patch    # bugfix       → 1.2.1
```

`make bump` also writes the new version to `LATEST_RELEASE`. Override at
deploy time with the `BOT_VERSION` env var if needed.

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
