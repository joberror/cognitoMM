# CognitoMM — Codebase Notes

> Quick-reference for understanding, editing, and extending the bot.
> Last reviewed against the current `main` branch.

---

## 1. What is this?

A production **Telegram movie bot** (hosted on Hugging Face Spaces) that:

- Monitors Telegram channels for movie/series uploads (auto-indexing + manual indexing)
- Extracts rich metadata from filenames/captions (`features/metadata_parser.py` — the single canonical parser module: `MovieFilenameParser` engine + `parse_metadata` API)
- Stores everything in **MongoDB Atlas** (async via **Motor**)
- Lets users **search** (exact + fuzzy), **request** missing titles, **download files** via inline buttons with **auto-deletion**, **premium tiers**, admin **broadcast**, and a **stats dashboard**
- Serves a Flask **health endpoint** for keep-alive/monitoring

**Stack:** Python 3.11 · **Pyroblack** (Pyrogram fork) · Motor/PyMongo · FuzzyWuzzy · TMDb API · Flask · aiohttp · Docker

---

## 2. Repository layout

```
main.py                     # Entry point → features.bot.run_bot()
features/                   # All bot logic (the real codebase)
tests/                      # Standalone test scripts (python tests/test_*.py)
info/                       # Historical design docs (mostly outdated sketches)
TERMS_AND_PRIVACY.md        # Terms shown on first /start
file_deletions.json         # Runtime-persisted auto-deletion records (auto-generated)
Dockerfile / docker-compose.yml / run.sh / .github/workflows/deploy.yml
pyproject.toml              # codeflash config (module root: features, tests-root: tests)
```

---

## 3. Startup flow (`main.py` → `features/bot.py`)

```
run_bot()
├─ start_webapp()              # Flask on 0.0.0.0:7860, background daemon thread
└─ asyncio.run(main())
   ├─ ensure_indexes()         # 17 MongoDB indexes (see database.py)
   ├─ initialize_premium_features()
   ├─ CognitoBot() async context
   │  ├─ get_me() → verify bot, set config.client = app   # client starts as None!
   │  ├─ logger.set_client(app, LOG_CHANNEL); start_capturing()
   │  └─ handlers:
   │     ├─ MessageHandler(handle_command, filters.regex(r"^/"))   → commands.py
   │     ├─ MessageHandler(on_message)                             → indexing.py (auto-index + user input routing)
   │     ├─ InlineQueryHandler(inline_handler)                     → search.py
   │     ├─ CallbackQueryHandler(callback_handler)                 → callbacks.py
   │     ├─ RawUpdateHandler(handle_raw_update)                    → deletion_events.py (if available)
   │     └─ start_deletion_monitor()                               → file_deletion.py
   └─ await stop_event.wait()   # Ctrl+C / KeyboardInterrupt → flush logger
```

### `CognitoBot`
Subclasses Pyroblack `Client` and adds `iter_messages(chat_id, limit, offset)` (borrowed from Auto-Filter-Bot) — fetches messages in batches of 200 via `get_messages` — used by the manual indexing process.

---

## 4. Module map

| Module | Lines | Role / key symbols |
|---|---|---|
| `features/bot.py` | 175 | `CognitoBot`, `run_bot()`, `main()` — startup + handler registration |
| `features/config.py` | 103 | All env vars + **global in-memory state**: `bulk_downloads`, `file_deletions`, `file_deletions_lock`, `indexing_lock`, `INDEX_EXTENSIONS`, `message_queue`, `queue_processor_task`, `user_input_events`, `TempData`/`temp_data`, `client` |
| `features/database.py` | 128 | Motor client (60s timeouts), 10 collections, `ensure_indexes()`, helpers `get_user_doc/is_admin/is_banned/has_accepted_terms/log_action` |
| `features/commands.py` | 2571 | `handle_command()` dispatcher + all command handlers (see §6) |
| `features/callbacks.py` | 1380 | `callback_handler()` — all inline-button flows (see §7) |
| `features/indexing.py` | 486 | `start_indexing_process`, `save_file_to_db`, `index_message`, `process_message_queue`, `on_message` (queue-based auto-indexing) |
| `features/metadata_parser.py` | 1018 | Single canonical parser module: `ParsedMedia` + `MovieFilenameParser` (deep filename engine — regex dictionaries for resolutions/sources/codecs/audio/bit-depth/HDR/languages/subtitles/editions; the engine owns ALL parsing incl. quality, CH-suffixed channels, bit depth, rip/source, audio/video codecs, HDR, publisher, context-aware multi-year release-year/title selection, IMDB IDs and x-dimension resolutions; `parse_metadata` is a pure mapper with zero fallback logic) |
| `features/search.py` | 380 | `perform_search`, `send_search_results` (pagination), `inline_handler` — live `/search`/`/recent` handlers live in `commands.py`; grouping helpers imported from `utils.py` |
| `features/utils.py` | 363 | `wait_for_user_input`/`set_user_input` (client.listen replacement), `cleanup_expired_bulk_downloads`, `get_readable_time`, `format_file_size`, `construct_final_caption`, `resolve_chat_ref`, recent-content grouping helpers (`group_recent_content`/`format_movie_group`/`format_series_group`/`format_recent_output`), access-control re-exports |
| `features/user_management.py` | 169 | Admin/banned/terms checks, `log_action`, `should_process_command`, `require_not_banned` |
| `features/request_management.py` | 169 | Rate limits (3 pending / 1 per day / 20 global per day), duplicate check (fuzzy ≥85%), IMDB link validation, queue position |
| `features/tmdb_integration.py` | 427 | `search_tmdb`, `get_imdb_id`, trending movies/shows, new releases, `get_random_background_image`; 30-min in-memory cache |
| `features/premium_management.py` | 446 | Premium users CRUD + expiry handling + feature toggles (defaults: `recent`, `request`, `get_all`) |
| `features/premium_commands.py` | 309 | Multi-step interactive premium admin flows (user input handlers) |
| `features/broadcast.py` | 469 | `cmd_broadcast`, recipient query, rate-limited send loop with progress edits, summary, `broadcasts_col` logging |
| `features/file_deletion.py` | 287 | Auto-deletion of sent files: `track_file_for_deletion`, `check_files_for_deletion`, disk persistence (`file_deletions.json`), `start_deletion_monitor` |
| `features/deletion_events.py` | 153 | `handle_raw_update` — heuristic real-time deletion detection (limited; see gotchas) |
| `features/webapp.py` | 55 | Flask `/` and `/health` endpoints |
| `features/logger.py` | 194 | `TelegramLogger` — captures stdout/stderr, buffers, flushes to `LOG_CHANNEL` every 3s; ignores `[DIAGNOSTIC]`/`[INDEXED]` lines |
| `features/__init__.py` | 113 | Re-exports the public API across modules |

---

## 5. Database (MongoDB via Motor)

Collections (all in `database.py`):

| Collection | Purpose |
|---|---|
| `movies` | Indexed content — one doc per channel message. `_id` = `f"{chat_id}_{message_id}"` (in `save_file_to_db`) OR auto ObjectId (in `index_message`) |
| `users` | `user_id`, `role` (`user`/`admin`/`banned`), `terms_accepted`, `search_history[]`, `download_count`, `download_history[]`, `inline_search_count`, `last_seen` |
| `channels` | `channel_id`, `channel_title`, `enabled`, `added_by`, `added_at` |
| `settings` | key/value store (e.g. `{k: "auto_indexing", v: bool}`) |
| `logs` | `log_action()` audit trail: `action`, `by`, `target`, `extra`, `ts` |
| `requests` | User requests: `user_id`, `title`, `year`, `status` (pending/completed), `request_date` |
| `user_request_limits` | `user_id`, `last_request_date` (for per-day limit) |
| `premium_users` | `user_id`, `expiry_date`, `added_date`, `added_by`, `last_updated`, `last_updated_by` |
| `premium_features` | `feature_name`, `description`, `enabled` (premium-only flag), `added_date`, `added_by` |
| `broadcasts` | Broadcast history: `broadcast_id`, `admin_id`, `message_text`, totals, error breakdown, timestamps |

**Indexes** created by `ensure_indexes()`: title, year, quality, type, (channel_id+message_id), user_id, channel_id, request user_id/status/date, limits user_id, premium user_id/feature_name, broadcast id/admin_id/started_at/status. The user/channel/limits/premium/broadcast-id indexes are **unique**.

**`movies` doc shape** (from `index_message`): `title`, `year`, `rip`, `source`, `quality`, `extension`, `resolution`, `audio`, `imdb`, `type`, `season`, `episode`, `file_size`, `upload_date`, `channel_id`, `channel_title`, `message_id`, `caption`, `indexed_at`, plus all extra parsed fields (edition, language, tags, flags, etc.).

---

## 6. Commands (`commands.py` — `handle_command` router)

Routing notes: strips `@botname`, `/f` is an alias for `/search`, `-e` flag = exact match only, ban + terms checks run before dispatch (only `/start` exempt), admins bypass terms.

**User:**
- `/start` — terms gate → welcome photo + Support/Tutorial buttons
- `/help` — user + admin help (if admin)
- `/search <t>` / `/f <t>` / `/f -e <t>` — smart search (exact + fuzzy) / exact only
- `/my_history` — search history grouped by date with copyable command links
- `/my_stat` — per-user stats dashboard (`collect_user_stats` + `format_user_stats_output`)
- `/recent` — last batch update (10-min window around latest `indexed_at`); premium-gated if enabled
- `/trending` — TMDb trending movies/shows/new releases with category buttons
- `/request` — submit a title request (rate limited, TMDb verification)

**Admin:**
- `/stat`, `/quickstat` — full/quick stats dashboard
- `/broadcast` — send message to all eligible users
- `/request_list` — paginated request queue management
- `/premium` — premium user/feature management (interactive)
- `/mc` (alias `/manage_channel`) — unified channel manager with action buttons
- `/add_channel`, `/remove_channel` — register/unregister channels (accepts id / t.me slug / @username)
- `/index_channel` — interactive channel indexing (link/forward → skip count → confirm)
- `/toggle_indexing` — auto-index on/off
- `/reset_channel` — delete a channel's indexed data (confirm flow)
- `/promote`, `/demote`, `/ban_user`, `/unban_user` — user control
- `/update_db` — interactive DB sync: pick channel + message range → remove orphans, index new files (progress bar + ETA)
- `/manual_deletion` — search & batch-delete indexed entries (selection buttons)
- `/indexing_stats`, `/reset_stats` — indexing diagnostic counters
- `/reset` — wipe ALL indexed movies (CONFIRM gate)

**Help text** (`USER_HELP` / `ADMIN_HELP`) is defined in `commands.py` and rendered by `cmd_help`.

---

## 7. Callback flows (`callbacks.py` — `callback_handler`)

Routing order (important — first match wins):

| Callback prefix | Flow |
|---|---|
| `terms#` | `terms#accept` / `terms#decline` — sets `terms_accepted`, bypasses access control |
| `help` | Renders help menu |
| `get_file:{ch}:{msg}` | Fetch media from channel → `send_cached_media` with `construct_final_caption` → `track_file_for_deletion` (5-min auto-delete) → tracks download |
| `page:{search_id}:{n}` | Search pagination (state in `bulk_downloads`) |
| `index#` | `index#yes#{chat}#{last_id}#{skip}` starts `start_indexing_process`; `index#cancel` sets `temp_data.CANCEL = True` |
| `mc#` | Channel manager actions (`add/remove/index/update/reset/monitoring`) — builds a `PseudoMessage` and invokes the command handlers; `monitoring` toggles auto-indexing and re-renders |
| `bulk:{bulk_id}` | Sends up to 10 stored files, each tracked for auto-deletion (15-min bulk notice) |
| `hsearch#` / `hsearch_exact#` | Re-runs a search from `/my_history` |
| `mdel#` | Manual deletion session: toggle selection, confirm delete, cancel |
| `req_done:` / `req_page:` / `req_all_done:` | Request queue admin actions (notify user on completion) |
| `premium:` | Premium menu: `add_users`, `edit_users`, `remove_users`, `manage_features`, `add_feature`, `back` |
| `premium_toggle:{feature}` | Toggle premium-only feature |
| `stats_export:` | Send stats as JSON or CSV document |
| `trending:` | Switch trending category (movies/shows/releases) |

All callbacks (except `terms#`) require `should_process_command_for_user` + terms acceptance (admins exempt).

---

## 8. Data flows (memorize)

### Indexing
```
channel post → on_message (indexing.py)
  ├─ user input routing (user_input_events key "chatid_userid"; premium_* input_type → premium_commands)
  ├─ commands (^/) → let through to command handler
  └─ auto_index enabled? → message_queue.append(msg) → process_message_queue (sequential!)
       → index_message(msg)
         ├─ chat must be channel/supergroup/forum
         ├─ channel must exist in channels_col and be enabled
         ├─ only video or video-mime document
         ├─ duplicate guard: movies_col.find({channel_id, message_id})
         └─ parse_metadata(caption, filename) → insert → log_action("indexed_message")
```
Diagnostic counters in `indexing_stats` track attempts/successes/duplicates/errors (view via `/indexing_stats`).

### Search
```
/search → cmd_search → perform_search(query, exact, threshold)
  ├─ exact: regex ^escaped$ (i)
  └─ normal: regex contains + fuzzy partial_ratio ≥ FUZZY_THRESHOLD (68) over up to 500 docs
→ send_search_results: 9/page, "Get [n]" buttons, prev/next, "Get All" (premium-gated)
→ state in bulk_downloads keyed by 8-char UUID (callback data ≤ 64 bytes)
```

### File delivery + auto-delete
```
get_file/bulk → client.get_messages(channel, msg) → send_cached_media(file_id, caption)
→ track_file_for_deletion(user_id, message_id) → file_deletions dict + file_deletions.json
→ start_deletion_monitor loop (every 60s):
     2-min warning message if not notified
     delete via client.delete_messages at delete_at (default +5 min)
     "Auto-Deleted" notification
```

### Terms gate
```
/start → has_accepted_terms? → yes: welcome photo+buttons
                              → no: TERMS_AND_PRIVACY.md (split at 4000 chars) + accept/decline buttons
terms#accept → users_col $set terms_accepted: true, terms_accepted_at, last_seen
handle_command + callbacks enforce: banned check → terms check (admins bypass)
```

### Requests
```
/request → is_admin? (bypass) → check_rate_limits (3 pending / 1 per day / 20 global)
        → validate_imdb_link → search_tmdb suggestion → save to requests_col (pending)
        → update_user_limits
/request_list → paginated admin view → req_done / req_all_done → status=completed → notify user
```

### Broadcast
```
/broadcast → interactive message → confirm YES → get_broadcast_recipients()
  (terms_accepted: true, role ≠ banned; test mode overrides with BROADCAST_TEST_USERS)
→ execute_broadcast: send with 1/BROADCAST_RATE_LIMIT delay, progress edits every 100 users
→ summary + log_broadcast → broadcasts_col
```

### Premium
```
/premium → menu → add/edit/remove user (interactive inputs via premium_commands.py)
        → manage_features → toggle premium-only flags (recent/request/get_all)
Gate checks inline: is_feature_premium_only(name) && !is_premium_user && !is_admin → blocked
```

---

## 9. ⚠️ Gotchas / landmines for future edits

1. ~~**`temp_data` shadowing bug (`config.py`)**~~ ✅ **FIXED** — the stray `class temp_data: CANCEL = False` that shadowed the `TempData()` instance was removed; `temp_data` now stays bound to the instance.
2. **`client` is `None` at import time** — always import `from .config import client` *inside* a function; it's set in `bot.main()` after auth.
3. **Duplicated helper code** — ✅ **CONSOLIDATED** — file-deletion functions are canonical in `file_deletion.py`, access-control helpers in `user_management.py`, `get_readable_time`/size formatters and the recent-content grouping helpers (`group_recent_content`/`format_movie_group`/`format_series_group`/`format_recent_output`) are canonical in `utils.py` (all re-exported for backward compat; `search.py`/`commands.py` import them from `utils.py`). ✅ **Re-export chains audited** — an AST scan verified no module imports a symbol from another module that merely re-exports it (fixed: `commands.py` now pulls `INDEX_EXTENSIONS`/`indexing_lock`/`message_queue` from `config.py` and `indexing_stats` from `statistics_store.py` instead of via `indexing.py`; `search.py` pulls `cleanup_expired_bulk_downloads` from `utils.py` and `channels_col` from `database.py`). The `file_deletion.py` re-export of `cleanup_expired_bulk_downloads` is intentionally kept (test-pinned backward compat). ✅ **Dead duplicate handlers removed** — `search.py`'s `cmd_search`/`cmd_recent` (never routed; live ones are in `commands.py`) were deleted. 🔒 **Enforced in CI** — `scripts/check_reexports.py` (stdlib-only AST scan, runs in `.github/workflows/static-checks.yml` on push/PR and as `tests/test_reexport_check.py`) fails the build if any relative intra-package import resolves through a re-exporting module, references an undefined name, targets a missing module, OR defines the same module-level function/class in two modules (duplicate definition). ✅ **Role/log helpers consolidated** — `get_user_doc`/`is_admin`/`is_banned`/`has_accepted_terms`/`log_action` are canonical in `user_management.py`; `database.py` no longer defines them (its `log_action` diverged: logger-based vs `user_management`'s direct `send_message`). `database.py` re-exports them lazily via a **PEP 562 module `__getattr__`** (a top-level re-export would be circular: `user_management` imports `database` collections at module level). All callers (`premium_management.py`, `__init__.py`) now import from `.user_management`.
4. **Dead/broken code** — ✅ **REMOVED** — `search.py`'s `cmd_search`/`cmd_recent` were never routed (the live `/search` and `/recent` are in `commands.py`) and have been deleted; the duplicate-definition gate in `check_reexports.py` now prevents such copies from returning. ✅ **FIXED (tests)** — the parser tests now import `parse_metadata` from `features.metadata_parser` with project-root `sys.path` setup.
5. ~~**Premium field-name mismatch**~~ ✅ **FIXED** — `statistics.py` now reads `expiry_date`/`added_date`/`added_by`, matching what `premium_management.py` writes.
6. **Circular-import convention** — intra-package imports (`from .module import x`) at top level; runtime deps (`client`, `settings_col`, `indexing_stats`, etc.) imported lazily inside functions.
7. **Timezones** — most code uses `datetime.now(timezone.utc)`; helpers defensively convert naive datetimes. `index_message` uses `datetime.utcfromtimestamp()` for `upload_date` (naive) — keep in mind when comparing.
8. ~~**`require_not_banned` (`utils.py`) doesn't await**~~ ✅ **FIXED** — the decorator now `await`s `check_banned(message)`; the `user_management.py` copy was already correct.
9. **Deletion detection** — real-time channel message deletions do NOT reach bots (Telegram API limitation); `handle_raw_update` only works for groups/supergroups. **`prune_orphaned_index_entries()` in `indexing.py` is the primary mechanism** — it verifies indexed entries by fetching channel messages and removes missing/empty/malformed ones (FloodWait-safe). ✅ **Wired** as a periodic background task: `start_orphan_prune_monitor()` (every 30 min) is started in `bot.py`. ⚠️ Only safe while the bot retains access to all indexed channels.
10. **Callback data size** — bulk search/download state is stored in `bulk_downloads` keyed by short UUIDs because callback data has a 64-byte limit.
11. **Queue processor** — `message_queue` (deque, maxlen 100) serializes auto-indexing to avoid duplicate-key races; `queue_processor_task` is started once.
12. **Message edit flood** — progress edits are wrapped in try/except and throttled (every 10 msgs or 3s in `update_db`; every 30 msgs in indexing).

---

## 10. Conventions

- Async everywhere (Pyroblack + Motor); `await` all DB calls (`to_list(length=None)` for full results)
- `snake_case` functions/vars, type hints on public functions, docstrings on modules/functions
- Emoji-rich Telegram UI; HTML parse mode for fancy messages, markdown elsewhere
- Errors are caught, printed to console (logger picks them up), and surfaced as friendly Telegram messages
- Audit actions via `log_action()` (writes `logs_col` + forwards to `LOG_CHANNEL` if set)
- Tests are **standalone scripts**: `python tests/test_xxx.py` → exit 0/1 (also pytest-compatible per codeflash config)

---

## 11. Environment variables (`config.py`)

| Var | Default | Notes |
|---|---|---|
| `API_ID` | 0 | required |
| `API_HASH` | "" | required |
| `BOT_TOKEN` | "" | required |
| `BOT_ID` | 0 | optional, auto-detected |
| `MONGO_URI` | "" | required for DB |
| `MONGO_DB` | moviebot | |
| `ADMINS` | "" | comma-separated IDs |
| `LOG_CHANNEL` | None | optional, e.g. -100… |
| `FUZZY_THRESHOLD` | 68 | fuzzy search cutoff |
| `AUTO_INDEXING` | True | default auto-index state |
| `TMDB_API` | "" | TMDb key (trending/requests) |
| `START_MESSAGE` | welcome text | /start caption |
| `SUPPORT_LINK` | https://t.me/ | Support button |
| `BROADCAST_RATE_LIMIT` | 25 | msgs/sec |
| `BROADCAST_PROGRESS_INTERVAL` | 100 | progress edit cadence |
| `BROADCAST_TEST_MODE` | False | use test users |
| `BROADCAST_TEST_USERS` | "" | comma-separated IDs |
| `PORT` | 7860 | Flask port (webapp.py) |

---

## 12. Testing & deployment

- **Run tests:** `python tests/test_<name>.py` (exit code 0 = pass, 1 = fail)
- **Lint/typecheck:** no configured linters; follow PEP 8 + the rules in `.agent/rules/python-code-guide.md`
- **CI:** `.github/workflows/static-checks.yml` runs on push/PR and delegates to the Makefile (so CI and `make` can't drift) — `reexport-check` job: `make check` (stdlib-only, fails on re-export chains / broken / unknown-module imports / duplicate definitions); `tests` job: `make test` (installs deps, then runs the full pytest suite; no live MongoDB/Telegram needed — tests use fakes/mocks)
- **Local gates:** `make check` (static import check), `make test` (installs deps, then runs pytest — mirrors CI's `tests` job), `make verify` (runs `check` + `test`, i.e. everything CI gates on), `make install-hooks` (installs the pre-commit hook via `git config core.hooksPath .githooks`; hook runs the static check when `features/*.py`/`main.py` are staged — see `.githooks/pre-commit`)
- **Deploy:** GitHub Actions (`.github/workflows/deploy.yml`) syncs `main` → HF Space `iamjoberror/bot-media` (needs `HF_TOKEN` secret)
- **Docker:** `Dockerfile` (python:3.11-slim, port 7860, `python main.py`); `docker-compose.yml` adds a MongoDB service; `run.sh` is the local dev launcher (pyenv, session cleanup)
- **Known stale bits:** ✅ **FIXED** — parser tests now import `parse_metadata` from `features.metadata_parser` (with `sys.path` setup); `test_orphan_prune.py` now exercises the real `prune_orphaned_index_entries()` in `features/indexing.py` (implemented so the documented orphan-prune mechanism actually exists).
