# CognitoMM — Codebase Notes

> Quick-reference for understanding, editing, and extending the bot.
> Last reviewed against the current `main` branch.

---

## 1. What is this?

A production **Telegram movie bot** (hosted on Hugging Face Spaces) that:

- Monitors Telegram channels for movie/series uploads (auto-indexing + manual indexing)
- Extracts rich metadata from filenames/captions (`features/metadata_parser.py` — the single canonical parser module: `MovieFilenameParser` engine + `parse_metadata` API)
- Stores everything in **MongoDB Atlas** (async via **Motor**)
- Lets users **search** (exact + fuzzy), **browse** (recent / trending / genres / random), **request** missing titles, **watch** titles for availability (TMDb-verified, with a DM on index), **download files** via inline buttons with **auto-deletion**, **buy premium** with Telegram Stars, and see a **stats dashboard**
- Admin **broadcast**, channel management, premium/feature administration, DB reconciliation, and TMDb backfill
- Serves a Flask **health endpoint** for keep-alive/monitoring

**Stack:** Python 3.12 (`.python-version`; `Dockerfile` uses `python:3.12-slim`) · **Pyroblack** (Pyrogram fork) · Motor/PyMongo · FuzzyWuzzy · TMDb API · Flask · aiohttp · Docker

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
   ├─ ensure_indexes()         # 25 MongoDB indexes (see database.py)
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
| `features/bot.py` | 225 | `CognitoBot`, `run_bot()`, `main()` — startup, handler registration, background monitors (deletion, orphan prune, rescan, premium expiry, keep-alive) |
| `features/config.py` | 175 | All env vars + `BOT_VERSION` + **global in-memory state**: `bulk_downloads`, `file_deletions`, `file_deletions_lock`, `indexing_lock`, `INDEX_EXTENSIONS`, `message_queue`, `queue_processor_task`, `user_input_events`, `TempData`/`temp_data`, `client` |
| `features/database.py` | 174 | Motor client (60s timeouts), 11 collections, `ensure_indexes()` (25 indexes), lazy PEP 562 re-exports of the user-management helpers |
| `features/commands.py` | 2644 | `handle_command()` dispatcher + most command handlers (see §6) |
| `features/request_commands.py` | 563 | `/request` user flow + `/request_list` admin queue (`cmd_request`, `cmd_request_list`, `send_request_list_page`); imported into the commands.py router |
| `features/watchlist.py` | 489 | `/watch` `/unwatch` `/watchlist` — TMDb resolution, disambiguation picker, status rendering, UPDATE (see §8 *Watchlist*); imported into the commands.py router |
| `features/broadcast.py` | 469 | `cmd_broadcast`, recipient query, rate-limited send loop with progress edits, summary, `broadcasts_col` logging; imported into the commands.py router |
| `features/callbacks.py` | 1638 | `callback_handler()` — all inline-button flows (see §7) |
| `features/indexing.py` | 693 | `start_indexing_process`, `save_file_to_db`, `index_message`, `process_message_queue`, `on_message` (queue-based auto-indexing), `prune_orphaned_index_entries` + monitor |
| `features/metadata_parser.py` | 1062 | Single canonical parser module: `ParsedMedia` + `MovieFilenameParser` (deep filename engine — regex dictionaries for resolutions/sources/codecs/audio/bit-depth/HDR/languages/subtitles/editions; the engine owns ALL parsing incl. quality, CH-suffixed channels, bit depth, rip/source, audio/video codecs, HDR, publisher, context-aware multi-year release-year/title selection, IMDB IDs and x-dimension resolutions; `parse_metadata` is a pure mapper with zero fallback logic) |
| `features/search.py` | 1307 | `perform_search` (returns `{results, exact_ids}`), `send_search_results` (per-title pages + Title(s) Information), `render_search_page` (pagination keeps the info block), `build_pick_view`/`render_pick_view`, `inline_handler` — live `/search`/`/recent` handlers live in `commands.py`; line formatters live in `utils.py` (`format_latest_info`, `format_pick_line`, `series_label`, `format_rip_label`) |
| `features/statistics.py` | 1247 | `collect_comprehensive_stats`, `collect_quick_stats`, `collect_user_stats` + their formatters (dashboard rendering) |
| `features/tmdb_integration.py` | 950 | `search_tmdb`, `get_imdb_id`, `enrich_title` (6h cache), trending/new-releases, **and the watchlist layer**: `search_watch_candidates`, `derive_movie_status`/`derive_series_status`, `fetch_title_status`, `get_movie_release_types`, `is_ambiguous_title` |
| `features/utils.py` | 588 | `wait_for_user_input`/`set_user_input` (client.listen replacement), `cleanup_expired_bulk_downloads`, `get_readable_time`, `format_file_size`, `construct_final_caption`, `resolve_chat_ref`, quality dedup (`quality_rank`/`pick_best_quality`), recent-content grouping helpers, access-control re-exports |
| `features/user_management.py` | 723 | Admin/banned/terms checks, `log_action`, `should_process_command`, the shared role-action core (`resolve_targets` → `apply_role_action` + guards, used by `/user` and the 4 text aliases), plus the watchlist store: `add_to_watchlist`, `remove_from_watchlist`, `get_watchlist`, `watchlist_capacity`, `update_watchlist_status`, `notify_watchlist` (+ `_notify_cooldowns` floodgate) |
| `features/user_commands.py` | 731 | `/user` unified user manager: filters (All/Free/⭐/👑/🚫/Active/Recent), `last_seen`-sorted pagination with Super Admins pinned, header counts derived from the same queries as the list views, prompt → preview → confirm action flow (state in `bulk_downloads`), `usr#` callbacks, HTML-escaped rendering |
| `features/request_management.py` | 329 | Rate limits (3 pending / 1 per day / 20 global per day), duplicate check (TMDb-first, fuzzy ≥85% fallback), IMDB link validation, queue position, `upvote_request`, `fulfill_matching_requests` |
| `features/database_scan.py` | 358 | `start_db_rescan_monitor`, `incremental_rescan`, `scan_message_range`, per-channel cursor persistence |
| `features/premium_management.py` | 696 | Premium users CRUD + expiry handling + feature toggles (defaults: `recent`, `request`, `get_all`), daily download quota, expiry-warning monitor; `is_premium_user` short-circuits config `ADMINS` then falls back to the `is_admin` role |
| `features/premium_payments.py` | 208 | Telegram Stars purchases: plan menu/keyboard, invoice send, pre-checkout validation, idempotent payment activation |
| `features/premium_commands.py` | 306 | Multi-step interactive premium admin flows (user input handlers) |
| `features/reliability.py` | 130 | `retry_on_flood` (FloodWait-aware backoff, injectable sleep/rng) + `struct_log` |
| `features/keepalive.py` | 137 | `start_keep_alive` — HF Spaces self-ping to `/health` (see §12.2) |
| `features/statistics_store.py` | 41 | `indexing_stats` / `prune_stats` — the diagnostic counter dicts (imported from here, not from `indexing.py`, which rebinds them) |
| `features/file_deletion.py` | 298 | Auto-deletion of sent files: `track_file_for_deletion` (tier retention + warn lead), `check_files_for_deletion`, disk persistence (`file_deletions.json`), `start_deletion_monitor` |
| `features/deletion_events.py` | 170 | `handle_raw_update` — heuristic real-time deletion detection (limited; see gotchas) |
| `features/webapp.py` | 226 | Flask `/` and `/health` endpoints |
| `features/logger.py` | 236 | `TelegramLogger` — captures stdout/stderr, buffers, flushes to `LOG_CHANNEL` every 3s; ignores `[DIAGNOSTIC]`/`[INDEXED]` lines; `warm_up_peer` |
| `features/__init__.py` | 129 | Re-exports the public API across modules |

---

## 5. Database (MongoDB via Motor)

Collections (all in `database.py`):

| Collection | Purpose |
|---|---|
| `movies` | Indexed content — one doc per channel message. `_id` = `f"{chat_id}_{message_id}"` (in `save_file_to_db`) OR auto ObjectId (in `index_message`) |
| `users` | `user_id`, `role` (`user`/`admin`/`banned`), `terms_accepted`, `search_history[]`, `download_count`, `download_history[]`, `inline_search_count`, `last_seen`, plus `watchlist[]` — TMDb-verified entries `{title, title_key, year, type, tmdb_id, imdb_id, status, poster_url, seasons, episodes, added_at, status_checked_at}` (detail fields only present when actually resolved; `title_key` is the lowercased title used for matching + `$pull` removal) |
| `channels` | `channel_id`, `channel_title`, `enabled`, `added_by`, `added_at` |
| `settings` | key/value store: `{k: "auto_indexing", v: bool}`, per-channel cursors `scan_cursor:<channel_id>` |
| `logs` | `log_action()` audit trail: `action`, `by`, `target`, `extra`, `ts` |
| `requests` | User requests: `user_id`, `title`, `year`, `tmdb_id`, `status` (pending/completed), `votes`, `voters[]`, `request_date`, `completed_at`/`completed_by` |
| `user_request_limits` | `user_id`, `last_request_date` (for per-day limit) |
| `premium_users` | `user_id`, `expiry_date`, `added_date`, `added_by`, `last_updated`, `last_updated_by` |
| `premium_features` | `feature_name`, `description`, `enabled` (premium-only flag), `added_date`, `added_by` |
| `premium_payments` | Stars purchases: `user_id`, `plan_key`, `days`, `stars`, `charge_id` (unique), `status`, `created_at` |
| `broadcasts` | Broadcast history: `broadcast_id`, `admin_id`, `message_text`, totals, error breakdown, timestamps |

**Indexes** created by `ensure_indexes()` — 25 in total: movies `title`, `title` (text), `year`, `quality`, `type`, `(channel_id+message_id)`, `tmdb_id`; users `user_id`, `last_seen` (dashboard page sort), `role` (status filters), `terms_accepted_at` (Recent 30-day join window); channels `channel_id`; requests `user_id`/`status`/`request_date`/`tmdb_id`; limits `user_id`; premium `user_id`/`feature_name`/`expiry_date` (active-premium scan); payments `charge_id`; broadcasts `broadcast_id`/`admin_id`/`started_at`/`status`. The ones listed in `UNIQUE_INDEX_DESCRIPTIONS` (users user_id, channels channel_id, limits user_id, premium user_id + feature_name, payments charge_id, broadcasts broadcast_id) are **unique**. The movies text index needs `language_override` pointed at an unused field — see the comment block in `ensure_indexes()`.

**`movies` doc shape** (from `index_message`): `title`, `year`, `rip`, `source`, `quality`, `extension`, `resolution`, `audio`, `imdb`, `type`, `season`, `episode`, `file_size`, `upload_date`, `channel_id`, `channel_title`, `message_id`, `caption`, `indexed_at`, plus all extra parsed fields (edition, language, tags, flags, etc.). TMDb enrichment later `$set`s `tmdb_poster`/`tmdb_rating`/`tmdb_genres`/`tmdb_overview`/`imdb_id` and persists `tmdb_id` — **`tmdb_id` is the canonical identity** shared by watchlist matching and request fulfilment.

---

## 6. Commands (`commands.py` — `handle_command` router)

Routing notes: strips `@botname`, `/f` is an alias for `/search` and `/mc` an alias for `/manage_channel`, `-e` flag = exact match only, ban + terms checks run before dispatch (only `/start` exempt), admins bypass terms. An unknown command replies `❓ Unknown command`.

**Not all handlers live in `commands.py`.** The router is the single entry point, but three domain modules own their own command surface and are re-imported into it (the re-export gate — §9 gotcha 3 — enforces this: the canonical definition must live in the domain module, and `commands.py` only imports it):

| Domain module | Commands |
|---|---|
| `request_commands.py` | `/request`, `/request_list` |
| `watchlist.py` | `/watch`, `/unwatch`, `/watchlist` |
| `broadcast.py` | `/broadcast` |

A handler in `commands.py` that starts `async def cmd_` is *usually* routed from the `elif command == '...'` chain, but a few are reached only from a callback (`cmd_manage_channel` is also invoked by `mc#`, `cmd_premium` by `premium:`), so the router is not the only caller. The live router dispatches **40 command strings** (38 commands + 2 aliases: `/f` and `/mc`). Note that `scripts/check_reexports.py` gates *imports* and duplicate definitions — it does **not** verify that a command is routed, so an orphan handler fails silently.

**User commands:**

| Command | Behaviour |
|---|---|
| `/start` | Terms gate → welcome photo + Support/Tutorial buttons. The only command exempt from the ban and terms checks. |
| `/help` | `USER_HELP` menu; admins also get `ADMIN_HELP`. |
| `/search <t>`, `/f <t>`, `/f -e <t>` | Smart search (exact + fuzzy) / exact only. Appendable filters: `year`, `quality` (`480p/720p/1080p/2160p/4k`), `type` (`movie/series`) and the library facets `lang:`, `subs:`, `audio:`, `hdr`/`hdr:dv`. See §8 *Search*. |
| `/recent` | Last batch (10-min window around the newest `indexed_at`). Premium-gated when the `recent` feature flag is on (admins bypass). Plain HTML, one consolidated line per title (`N. <code>Title (year)</code> [qualities]` / `[S01E01-02]`) — tapping copies the full `Title (year)` string for `/search`. |
| `/trending` | TMDb trending movies / shows / new releases with category buttons (`trending:` callback). Lines are NOT inside a code fence so IMDb/TMDb links stay clickable. Needs `TMDB_API`. |
| `/random` | A random indexed title (uniform pick via `count_documents` + `skip`); sends the poster photo when the entry has one. |
| `/genres`, `/genres <name>` | Browse by stored `tmdb_genres`. No arg → genre list with counts; with a name → paginated 12/page browse of that genre, one deduped line per title, with `🔤 A–Z` / `🆕 Newest` / `⭐ Top Rated` sort toggle, `Pick [n]` and `Get [n]` per title. Depends on `/enrich` having backfilled `tmdb_genres`. |
| `/request` | Submit a missing-title request. Rate limited (3 pending / 1 per day / 20 global per day), TMDb-verified, premium-gated when the `request` flag is on. See §8 *Requests*. |
| `/watch <title>` | TMDb-verified watchlist add — see §8 *Watchlist*. 5 free / 20 premium. |
| `/unwatch <title>` | Remove a watchlist entry (title match is case-insensitive via `title_key`). |
| `/watchlist` | List watched titles as `Title: M / 2026 / Released · IMDb` (M = movie, S = series) with `🔄 UPDATE ALL` + per-title 🔄 buttons. See §8 *Watchlist*. |
| `/my_history` | Search history grouped by date, numbered plain-HTML lines with tap-to-copy `<code>` queries (bracket = search time). |
| `/my_stat` | Per-user usage dashboard (`collect_user_stats` + `format_user_stats_output`). |
| `/buy_premium` | Telegram Stars purchase menu: plan buttons (`buyplan:<key>`) → invoice → activation on payment. Replies with a "purchases unavailable" notice when `PREMIUM_STARS_ENABLED=false` or no plans are configured, and shows the current quota status for users who already have premium. |

**Admin commands:**

| Command | Behaviour |
|---|---|
| `/stat`, `/quickstat` | Full dashboard / quick key numbers (incl. prune stats). |
| `/logs [n]` | Recent `logs_col` entries in-chat (default 10, max 50). |
| `/enrich [n]`, `/enrich_status` | Backfill TMDb poster/genres/rating/IMDb for indexed entries (default 30, max 200) / report how many entries still lack TMDb metadata. Both no-op with a notice when `TMDB_ENRICH_INDEX=false`. |
| `/request_list` | Paginated pending-request queue, most-voted first. |
| `/premium` | Premium user + feature-flag management (interactive buttons). |
| `/broadcast` | Send a message to all eligible users — see §8 *Broadcast*. |
| `/mc` (alias `/manage_channel`) | Unified channel manager with action buttons. |
| `/add_channel`, `/remove_channel` | Register/unregister a channel (accepts raw id / t.me slug / @username). |
| `/index_channel` | Interactive indexing: link or forwarded post → skip count → confirm. |
| `/toggle_indexing` | Auto-indexing on/off (global). |
| `/reset_channel` | Delete one channel's indexed data (confirm flow). |
| `/update_db` | Interactive DB reconcile: pick channel + message range → remove orphans, index new files (progress bar + ETA). Also run on the `DB_RESCAN_INTERVAL_MINUTES` timer by the `database_scan.py` monitor (see the *Scheduled rescan* bullet in §8). |
| `/queue` | Live ops snapshot: index-queue depth vs cap (with a near-capacity drop warning), processor liveness, orphan-prune stats, auto-indexing flag, per-channel rescan cursors. |
| `/manual_deletion` | Search and batch-delete indexed entries (selection buttons). |
| `/indexing_stats`, `/reset_stats` | Indexing diagnostic counters / reset them. |
| `/user` | Unified user manager: paginated list (10/page, sorted by `last_seen` DESC, Super Admins pinned to the top of page 1) with All/Free/⭐/👑/🚫/Active(7d)/Recent(30d) filters, live names via one batched `get_users`, and Search / Ban / Unban / Demote / Promote buttons (prompt → preview → confirm). Private chat only. |
| `/promote`, `/demote`, `/ban_user`, `/unban_user` | Hidden text aliases for the same role actions — no preview, immediate summary. |
| `/reset` | Wipe **all** indexed movies (CONFIRM gate). |

`/request_list` is admin-only despite the name reading like a personal list — it returns `🚫 Admins only.` for regular users; users track their own requests through the auto-fulfill DM.

**Premium gating** is per-feature, not per-command: `is_feature_premium_only(name)` is checked inline (currently `recent`, `request`, `get_all`) and admins always pass. A feature flag is only meaningful once toggled in `/premium` → Manage Features; the defaults in `DEFAULT_PREMIUM_FEATURES` start enabled.

**Help text** (`USER_HELP` / `ADMIN_HELP`) is defined in `commands.py` and rendered by `cmd_help`. It is a **hand-maintained duplicate** of the tables above — adding a command without updating the help block leaves it undiscoverable in the menu. `/start` (obvious) and `/unwatch` (documented in the `/watch` line) are the only routed commands absent from both blocks; `/manage_channel` appears only as its `/mc` alias. Everything else is in sync, and `ADMIN_HELP` covers all routed admin commands; the four role aliases (`/promote`, `/demote`, `/ban_user`, `/unban_user`) are hidden from the menu on purpose — `/user` is their dashboard.

---

## 7. Callback flows (`callbacks.py` — `callback_handler`)

Routing order (important — first match wins):

| Callback prefix | Flow |
|---|---|
| `terms#` | `terms#accept` / `terms#decline` — sets `terms_accepted`, bypasses access control |
| `help` | Renders help menu |
| `buyplan:{key}` | Send a Telegram Stars invoice for a premium plan |
| `choose:{sid}:{gi}:{season}:{res}:{page}` | `Pick [n]` — in-place filter of a `/search` message down to one title's copies. 6-part is current; the legacy 5-part form is still parsed. Series season page via `S◀`/`S▶` |
| `watchpick:{token}:{idx}` | `/watch` disambiguation picker — store the chosen TMDb candidate, edit the message in place. `idx == "cancel"` aborts. State in `bulk_downloads` (`type: "watch_pick"`), ownership-checked |
| `watchupd:all:{uid}` / `watchupd:one:{uid}:{title_key}` | `/watchlist` 🔄 buttons — re-read status from TMDb. `uid` is the list owner, checked against the clicker so a forwarded message can't refresh someone else's list |
| `get_file:{ch}:{msg}` | Fetch media from channel → `send_cached_media` with `construct_final_caption` → `track_file_for_deletion` (tier retention) → counts against the daily quota |
| `page:{search_id}:{n}` | Search pagination (state in `bulk_downloads`); also `page:{sid}:{page}:{gi}:{sp}` advances a group's season page, and the legacy 3-part form is still parsed |
| `back:` | Restore the full `/search` results from a pick view |
| `index#` | `index#yes#{chat}#{last_id}#{skip}` starts `start_indexing_process`; `index#cancel` sets `temp_data.CANCEL = True` |
| `mc#` | Channel manager actions (`add/remove/index/update/reset/monitoring`) — builds a `PseudoMessage` and invokes the command handlers; `monitoring` toggles auto-indexing and re-renders |
| `usr#` | `/user` dashboard (see §6) — `usr#pg#{page}#{filter}` paginate/filter, `usr#act#{action}` opens the target prompt → preview, `usr#cnf#{token}` / `usr#can#{token}` confirm/cancel (state in `bulk_downloads`, ownership-checked), `usr#all` resets to All; admin and Super-Admin gates re-checked on every press |
| `bulk:{bulk_id}` | Sends up to 10 stored files, each tracked for auto-deletion (bulk retention) |
| `getpack:{sid}:{gi}:{season}:{res}` | Pick-view `📦 Get All` — delivers up to `MAX_PACK_FILES` (20) copies of the active season/resolution slice |
| `hsearch#` / `hsearch_exact#` | Re-runs a search from `/my_history` |
| `mdel#` | Manual deletion session: toggle selection, confirm delete, cancel |
| `req_done:` / `req_page:` / `req_all_done:` | Request queue admin actions (notify user on completion) |
| `genre_page:` / `genre_pick:` / `genre_back:` | `/genres <name>` browse — pagination (with a `sort` variant), in-place `Pick [n]`, and Back to the exact page |
| `premium:` | Premium menu: `add_users`, `edit_users`, `remove_users`, `manage_features`, `add_feature`, `back` |
| `premium_toggle:{feature}` | Toggle premium-only feature |
| `stats_export:` | Send stats as JSON or CSV document |
| `trending:` | Switch trending category (movies/shows/releases) |

All callbacks (except `terms#` and `help`) require `should_process_command_for_user` + terms acceptance (admins exempt). Every prefix that carries state in `bulk_downloads` re-checks ownership against the clicker (`group_data.get("user_id") != user_id` → refuse), because callback data travels with a forwarded message.

---

## 8. Data flows (memorize)### Feature cluster (added 2026-08)

- **Quality dedup + pick filter (`utils.py` / `search.py`)** —
  `quality_rank` / `pick_best_quality`; the pick view dedupes per episode
  (best copy wins, 🔁+N marker). `Pick [n]` filters the
  message in place to that title's copies (`choose:` → `render_pick_view` in
  `search.py`); series get per-season `Pick[n][Sxx]` buttons, and the pick view
  adds `[720p]/[1080p]/[2160p]` resolution filters + `← Back` (`back:` →
  `render_search_page`). Long-running series page through the seasons: the
  results list pages each group's `Pick[n][Sxx]` shortcuts (`S◀`/`S▶`;
  `page:{sid}:{page}:{gi}:{sp}` re-renders the same results page with that
  group's season page advanced — the legacy 3-part `page:{sid}:{page}` is
  still parsed), and the pick view pages its season buttons (10 per page,
  `S◀`/`S▶`; callback format `choose:{sid}:{gi}:{season}:{res}:{page}` —
  the legacy 5-part form is still parsed for backward compatibility).
- **TMDb enrichment (`tmdb_integration.py`)** — `enrich_title` (search +
  details API, cached 6h per title+year; no-op without `TMDB_API`). Newly
  indexed entries get `tmdb_poster`/`tmdb_rating`/`tmdb_genres`/
  `tmdb_overview`/`imdb_id` (gate: `TMDB_ENRICH_INDEX`). Search results show a
  ⭐/🎭/IMDb details block; inline results use poster `thumbnail_url` and
  `/search`-style bracket titles (`Title [1080p.1999]` via `format_search_info`);
  `/enrich` backfills older entries.
- **Watchlist (`watchlist.py` + `user_management.py` + `tmdb_integration.py`)**
  — the whole `/watch` surface lives in its own module (like
  `request_commands.py`); `commands.py` only re-imports `cmd_watch` /
  `cmd_unwatch` / `cmd_watchlist` for its router.
  - **Resolution** — `search_watch_candidates` (`tmdb_integration.py`) queries
    BOTH the movie and tv search endpoints (a watch target is a film or a show
    and users rarely say which), merges, then `_rank_watch_candidates` sorts
    exact-title matches first, then by popularity, deduping per
    `(type, tmdb_id)`. Each shown candidate gets an IMDb ID plus a derived
    status. `is_ambiguous_title` decides whether to ask: anything but a
    single exact **movie** match goes to the picker (remakes, a film and a
    show sharing a name, a fuzzy-only hit, or a lone Series — a user typing
    "Fargo" may have meant the film).
  - **Statuses** — `derive_movie_status` / `derive_series_status` turn TMDb
    fields into the six display states (`Released` / `In Cinemas` /
    `Upcoming` / `Continuing` / `Ended` / `Unknown`). *In Cinemas* is decided
    from `/release_dates` release types: a film with no wide-theatrical (type
    3) entry but a premiere/limited (types 1-2) date inside
    `WATCHLIST_IN_CINEMAS_DAYS` is still in its festival run. Series use TMDb
    `status`, with `next_episode_to_air` overriding a stale *Ended*.
  - **Picker** — state goes in `config.bulk_downloads` under
    `type: "watch_pick"` with a 12-hex token; `watchpick:{token}:{idx}`
    resolves it (ownership-checked, cancel + expiry handled). The message is
    edited in place by `store_watch_pick`.
  - **Capacity** — `watchlist_capacity` returns 5 free / 20 premium (admins get
    the premium cap). Checked in `cmd_watch` BEFORE any TMDb call, so a full
    list costs nothing.
  - **Storage** — entries carry `tmdb_id` + `imdb_id` + `status` +
    `poster_url` (+ `seasons`/`episodes` for series); only resolved fields are
    written, so a TMDb-less entry has no null placeholders. Matching stays
    TMDb-ID-first with normalized-title fallback.
  - **UPDATE** — `watchupd:all:{uid}` and `watchupd:one:{uid}:{title_key}`.
    `refresh_watchlist_statuses` re-reads each entry via `fetch_title_status`
    and patches with `update_watchlist_status` (positional `$set`); entries
    with no TMDb ID are skipped (no identity to query, so no status to derive)
    and the user is told. Rate-limited per user by
    `WATCHLIST_REFRESH_COOLDOWN_SECONDS`; the callback is answered BEFORE the
    lookups so a 20-entry refresh can't blow Telegram's 15s window. Button
    data carries the list owner's id so a forwarded message can't refresh
    someone else's list.
  - **Floodgate** — `notify_watchlist` DMs watchers on the first copy of a
    title, then records `(uid, identity) -> (sent_at, count)` in
    `_notify_cooldowns`; copies arriving inside
    `WATCHLIST_NOTIFY_COOLDOWN_SECONDS` for the SAME identity are absorbed, so
    a full season dropping at once produces one message per watcher. The key is
    per title (TMDb ID when known, else normalized title), so two different
    titles landing together each still notify, and a failed send is not
    recorded so a transient Telegram error doesn't burn the user's window.
  - **Rendering** — `1. Death of a Unicorn: M / 2026 / Released · IMDb`
    (M/S letters, tap-to-copy `<code>` titles, series season/episode counts).
- **Scheduled rescan (`database_scan.py`)** — `start_db_rescan_monitor`
  (started in `bot.py`) runs `incremental_rescan` per channel every
  `DB_RESCAN_INTERVAL_MINUTES`; cursor stored in `settings_col`
  (`scan_cursor:<channel_id>`), first run bounded to the last 1000 msgs.
- **Admin `/logs [n]`** — recent `logs_col` entries in-chat. **`/queue`** —
  live ops snapshot: index-queue depth vs the deque cap (with a
  near-capacity drop warning), queue-processor liveness (read via the
  `config` module because `indexing.py` rebinds the global), orphan-prune
  stats, auto-indexing flag and per-channel rescan cursors. **`/random`** —
  random indexed title (poster photo when available). **`/genres`** — browse
  by stored `tmdb_genres` (aggregation with counts; `$regex` array match).
  `/genres <name>` is paginated (12/page) with a `🔤 A–Z`/`🆕 Newest`/`⭐
  Top Rated` sort toggle (title asc / indexed_at desc / tmdb_rating desc),
  rendered in a code-block listing using the `/search` per-title +
  latest-file layout (⭐ rating kept at the end): `N. Title > N files >
  [series aggregates] > Latest: <latest-info>` where the latest info is the
  most recently indexed copy (`latest_copy` in utils.py, same rule as
  /search's `Get [n]`). The header carries a `Files Found: N (Movie - X |
  Series - Y)` split (`_genre_files_split`, computed once with the title
  count and stored in the browse state - same Movie/Series rule as /search)
  plus the shared Pick/Get `SEARCH_HINT` block (search.py constant, used by
  both /search and /genres so the copy can't drift).
  Titles are DEDUPLICATED — each appears exactly once:
  movies `1. Die Hard > 1 file > Latest: 1080p`, series
  `1. Breaking Bad > 4 files > 2 seasons [5] · 3 eps [35] > Latest:
  S01E02 | 720p` where the bracket values are the REAL TMDb totals
  (surfaced by `enrich_title` in tmdb_integration.py) and the DB counts
  outside use distinct seasons + distinct (season, episode) pairs so
  duplicate-quality copies don't inflate them (aggregation
  `_genre_title_pipeline` — one distinct-title page per render; real counts
  via `_genre_real_counts`):
  Every genre line gets a `Pick [n]` button (reusing `build_pick_view` from
  search.py via the `genre_pick:`/`genre_back:` callbacks - series also get
  `Pick[n][Sxx]` season shortcuts in the results, paged via `S◀`/`S▶` for
  >5 seasons through 6-part `genre_page:` data + a `season_pages` map in the
  state, mirroring /search) plus `Get [n]` (latest copy); the browse state
  stores `page` + the page's `entries` so Back from a pick view restores the
  exact page:
  `send_genre_page` in commands.py renders every page (shared by the
  initial send and the `genre_page:` callback — 3-part legacy and 4-part
  `page+sort` data both accepted), state stored as a typed `genre_list`
  entry in `bulk_downloads` with per-user ownership like the request list.

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
/search → cmd_search → perform_search(query, exact, threshold)  (search.py)
  ├─ exact: regex ^escaped$ (i)
  └─ normal: regex contains + fuzzy partial_ratio ≥ FUZZY_THRESHOLD (68) over up to 500 docs
  returns {results, exact_ids} — exact = title STARTS WITH the query
  (is_exact_title; word-boundary guard so "Luckily" is not exact for "Lucky")
→ send_search_results: per-title groups (group_by_title), 9 titles/page
  code-block list: Search : X / Titles Found: N (X Exact | Y Fuzzy) /
  Files Found: N (Movie - X | Series - Y) + per-title lines
  `N. Title > M files > Latest: <latest-info>` (latest = most recently indexed
  copy; format_latest_info in utils.py)
→ TMDb Title(s) Information block (build_title_info_block, ⭐·🎭·IMDb link)
  appended OUTSIDE the code block; metas stored in bulk_downloads[search_id]
  and merged per page so the block survives pagination (render_search_page)
→ keyboard: every title gets Pick [n] (choose:; series add Pick[n][Sxx]
  season shortcuts) AND Get [n] (get_file: of the latest copy); prev/next +
  "Get All" (premium-gated)
→ pick view (build_pick_view): code-block copy list, one line per copy
  `1. Lucky (2025) - 2.5GB | WebRip | 1080p` via format_pick_line (utils.py)
→ state in bulk_downloads keyed by 8-char UUID (callback data ≤ 64 bytes)
```

### File delivery + auto-delete
```
get_file/bulk/getpack → client.get_messages(channel, msg) → send_cached_media(file_id, caption)
→ track_file_for_deletion(user_id, message_id, duration_minutes=<tier retention>)
   (default 5; free FILE_DELETION_MINUTES vs premium PREMIUM_FILE_DELETION_MINUTES;
    bulk packs use BULK_*/PREMIUM_BULK_*) → file_deletions dict + file_deletions.json
→ start_deletion_monitor loop (every 60s):
     warn at delete_at - warn_minutes (stored per record; "N-Minute Warning")
     delete via client.delete_messages at delete_at
     "Auto-Deleted" notification
per-user daily quota gate (check_download_quota) + record_download on delivery
```
**Pick-view "Get All" pack** — the pick view adds a `📦 Get All (N)` button
(`getpack:{sid}:{gi}:{season}:{res}`) for /search pick views with >1 copy; the
callback filters the stored group by the active season/resolution and delivers
up to `MAX_PACK_FILES` (20) copies through the shared `_deliver_bulk_files`
helper (same tracking/quota/notice path as `bulk:`).

### Reliability
```
retry_on_flood(coro_factory, max_retries=, base_delay=, max_delay=, jitter=)
  ├─ FloodWait -> wait the API-reported seconds (clamped), up to max_retries
  ├─ retry_on=(ExcType,) -> exponential backoff for transient errors
  └─ injectable sleep/rng (tests never wait)
```
Used by `CognitoBot.iter_messages` (backfills survive rate limits) and
`scan_message_range` (`flood_retries`/`retry_sleep`; default 0 keeps the
pause-on-FloodWait semantics). `struct_log(event, **fields)` emits grep-able
`[EVENT] event key=value` lines (captured by the logger like any print).

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
        → TMDb picker captures tmdb_id → own-dup check (tmdb exact, else fuzzy ≥85%)
        → global match? → offer free upvote (upvote_request, no quota) vs own request
        → save to requests_col (pending, tmdb_id/votes/voters) → update_user_limits
/request_list → pending sorted by request_priority_key (votes desc, oldest first,
                ▲ counts shown) → req_done / req_all_done → status=completed →
                notify requester + all voters
auto-fulfill → index_message stores tmdb_id at enrich time, then
        fulfill_matching_requests(entry) completes + DMs requester/voters w/ Get
```

### Watchlist
```
/watch <title>
  ├─ capacity gate: watchlist_capacity (5 free / 20 premium, admins = premium)
  │    checked FIRST — a full list spends no TMDb calls
  ├─ search_watch_candidates: TMDb movie + tv search, merged
  │    _rank_watch_candidates → exact title, then popularity; dedupe (type, tmdb_id)
  ├─ no candidates? → add_to_watchlist on the raw string (title-only matching)
  ├─ is_ambiguous_title?  → picker: bulk_downloads[token] = {type: "watch_pick", ...}
  │                         watchpick:{token}:{idx} → store_watch_pick → edit msg in place
  └─ single exact movie   → store_watch_pick immediately
/watchlist → render_watchlist_text "1. Title: M / 2026 / Released · IMDb"
           → render_watchlist_keyboard: 🔄 per title + 🔄 UPDATE ALL
watchupd:one|all:{uid} → cooldown (WATCHLIST_REFRESH_COOLDOWN_SECONDS)
        → answer() BEFORE the lookups (Telegram's 15s window)
        → refresh_watchlist_statuses → fetch_title_status → update_watchlist_status
        → entries with no tmdb_id are skipped (no identity → no status to derive)
notify (from index_message, post-enrich) → notify_watchlist(entry)
        match tmdb_id first, then title_key fallback
        per-(uid, identity) cooldown → a season batch = ONE DM per watcher
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
/buy_premium → plan buttons (buyplan:<key>) → send_invoice (currency XTR)
  → Telegram pre_checkout_query → handle_pre_checkout (validate payload)
  → successful_payment → handle_successful_payment → activate_payment
     (idempotent per telegram_payment_charge_id; records premium_payments_col)
/premium → menu → add/edit/remove user (interactive inputs via premium_commands.py)
        → manage_features → toggle premium-only flags (recent/request/get_all)
Gate checks inline: is_feature_premium_only(name) && !is_premium_user && !is_admin → blocked
Download quota: check_download_quota on get_file/bulk (free cap vs premium lift;
        day counter on the user doc) · expiry DMs 3d/1d via start_premium_expiry_monitor
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
13. **pyroblack deprecation safety net** — the CI gates turn any deprecated-API usage into a test failure (two mechanisms: `filterwarnings` in `pyproject.toml` + the `_PyrogramDeprecationGuard` logging handler in `tests/conftest.py`), and dedicated pin/guard tests enforce the modern API spellings. See §12.1. When adding send/edit/reply/inline-result code, always use the modern kwargs (`link_preview_options=`, `reply_parameters=`, `thumbnail_*`).
14. **Log sends: `[403 PEER_ID_INVALID]` on fresh sessions** — the `.session` file caches Telegram peer access hashes. On a fresh session (HF rebuild, deleted `.session`), `send_message` to `LOG_CHANNEL` fails until an update from that chat caches the peer — this is why logs only started working after the admin ran a command. The bot handles it automatically now: `logger.warm_up_peer()` (`get_chat()`) runs at startup in `bot.py`, and `flush()` in `logger.py` re-resolves on `PeerIdInvalid` specifically, so it self-heals within seconds of the peer becoming reachable. **Don't delete `.session` files on every restart** — `run.sh` keeps them by default (`CLEAN_SESSIONS=1` to wipe). See §12.2.

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
| `METRICS_TIMEOUT` | 30 | seconds for the metrics scrape (webapp.py) |
| `TMDB_ENRICH_INDEX` | true | enrich new indexed entries with TMDb poster/genres/rating/imdb (powers /genres, posters, watchlist statuses) |
| `DB_RESCAN_ENABLED` | true | scheduled incremental rescan (background /update_db) |
| `DB_RESCAN_INTERVAL_MINUTES` | 360 | rescan cadence (every 6 hours) |
| `KEEP_ALIVE_URL` | None | public URL the bot pings to keep HF Spaces awake; else auto-derived from `SPACE_HOST`/`SPACE_ID` |
| `KEEP_ALIVE_INTERVAL` | 240 | self-ping seconds (must stay below the host's sleep timer, e.g. HF's 15 min) |
| `KEEP_ALIVE_ENABLED` | true | `false` disables the self-keep-alive |
| `CLEAN_SESSIONS` | 0 | `1` wipes `.session` files at startup (`run.sh` only) |
| `BOT_VERSION` | — | overrides `config.BOT_VERSION` on the webapp `/` endpoint |

⚠️ `START_MESSAGE` has a legacy misspelled alias, `START_MESSAGEE`, still honoured as a fallback in `config.py` (`os.getenv("START_MESSAGE", os.getenv("START_MESSAGEE", ...))`). Use the correctly-spelled name; the alias is a compatibility shim, not a second supported var.

**Premium** (all in `config.py`):

| Var | Default | Notes |
|---|---|---|
| `PREMIUM_STARS_ENABLED` | true | `false` makes `/buy_premium` report purchases as unavailable |
| `PREMIUM_PLANS` | `1m:30:50,3m:90:120,6m:180:200,12m:365:350` | `key:days:stars` triples; malformed entries are skipped silently |
| `PREMIUM_STARS_CURRENCY` | `XTR` | hardcoded, not env-driven |
| `PREMIUM_EXPIRY_WARN_DAYS` | `3,1` | days-before-expiry that trigger a reminder DM |
| `FREE_DOWNLOAD_DAILY_LIMIT` | 10 | per-day download cap, free tier |
| `PREMIUM_DOWNLOAD_DAILY_LIMIT` | 0 | `0` = unlimited |

**Auto-deletion retention** (minutes, all in `config.py`):

| Var | Default | Notes |
|---|---|---|
| `FILE_DELETION_MINUTES` | 5 | free tier, single delivery |
| `PREMIUM_FILE_DELETION_MINUTES` | 30 | premium tier, single delivery |
| `BULK_FILE_DELETION_MINUTES` | 15 | free tier, bulk/`Get All` deliveries |
| `PREMIUM_BULK_FILE_DELETION_MINUTES` | 60 | premium tier, bulk deliveries |
| `FILE_DELETION_WARN_MINUTES` | 2 | lead time of the "will be deleted" DM; auto-scaled down when retention is shorter |

**Watchlist** (all in `config.py`; see §8 *Watchlist*):

| Var | Default | Notes |
|---|---|---|
| `WATCHLIST_FREE_LIMIT` | 5 | max watched titles, free tier |
| `WATCHLIST_PREMIUM_LIMIT` | 20 | max watched titles, premium tier (also the admin cap) |
| `WATCHLIST_NOTIFY_COOLDOWN_SECONDS` | 300 | the floodgate — per (user, title) window in which extra DMs are suppressed |
| `WATCHLIST_REFRESH_COOLDOWN_SECONDS` | 60 | floor between UPDATE presses on `/watchlist` |
| `WATCHLIST_PICK_LIMIT` | 5 | candidates shown in the `/watch` disambiguation picker |
| `WATCHLIST_IN_CINEMAS_DAYS` | 21 | how long a limited/premiere theatrical run counts as *In Cinemas* |

---

## 11.5 Versioning (BOT_VERSION)

The bot version has ONE source of truth: `BOT_VERSION` in `features/config.py`
(re-exported as `features.__version__`). It's surfaced on the webapp `/`
endpoint and in the startup banner (`MovieBot is running! (vX.Y.Z)`).

**Policy: every new feature bumps the version.** The pre-commit hook runs
`scripts/check_version_bump.py`, which rejects a staged commit that adds a new
feature — a new `cmd_*`/`handle_*` handler, a new `elif command ==` router
entry, or a new module under `features/` — without a corresponding `BOT_VERSION`
change. Bump with:

```bash
make bump          # minor: new feature (default)
make bump-patch    # patch: small change / bugfix
make bump-major    # major
```

`scripts/bump_version.py` rewrites the constant and writes the new version to
`LATEST_RELEASE`. Deploy-time override: `BOT_VERSION` env var (webapp reads it
first). Bypass the hook with `SKIP_VERSION_CHECK=1` (not recommended).

## 12. Testing & deployment

- **Run tests:** `python tests/test_<name>.py` (exit code 0 = pass, 1 = fail)
- **Lint/typecheck:** no configured linters; follow PEP 8 + the rules in `.agent/rules/python-code-guide.md`
- **CI:** `.github/workflows/static-checks.yml` runs on push/PR and delegates to the Makefile (so CI and `make` can't drift) — `reexport-check` job: `make check` (stdlib-only, fails on re-export chains / broken / unknown-module imports / duplicate definitions); `lint` job: installs pinned ruff (`requirements.txt`) and runs `make lint` (pyflakes F + E9 via `[tool.ruff]` in `pyproject.toml`); `tests` job: `make test` (installs deps, then runs the full pytest suite; no live MongoDB/Telegram needed — tests use fakes/mocks)
- **Local gates:** `make check` (static import check), `make lint` (ruff), `make test` (installs deps, then runs pytest — mirrors CI's `tests` job), `make verify` (runs `check` + `lint` + `test`, i.e. everything CI gates on), `make install-hooks` (installs the pre-commit hook via `git config core.hooksPath .githooks`; hook runs the static check + ruff (when installed) + version-bump check when `features/*.py`/`main.py` are staged — see `.githooks/pre-commit`)
- **Deploy:** GitHub Actions (`.github/workflows/deploy.yml`) syncs `main` → HF Space `iamjoberror/bot-media` (needs `HF_TOKEN` secret)
- **Docker:** `Dockerfile` (python:3.12-slim, port 7860, `python main.py`); `docker-compose.yml` adds a MongoDB service (bind-mounts the project dir, so the `.session` file survives container recreation in the default dev setup); `run.sh` is the local dev launcher (prefers `.venv`, keeps sessions unless `CLEAN_SESSIONS=1`)
- **Known stale bits:** ✅ **FIXED** — parser tests now import `parse_metadata` from `features.metadata_parser` (with `sys.path` setup); `test_orphan_prune.py` now exercises the real `prune_orphaned_index_entries()` in `features/indexing.py` (implemented so the documented orphan-prune mechanism actually exists).

### 12.1 pyroblack deprecation safety net

pyroblack (installed as the `pyrogram` package) deprecates APIs in **two different ways**, so the safety net has **two complementary mechanisms** — both are active for every `pytest` run, including CI:

1. **Python `DeprecationWarning` gate** — `filterwarnings` in `pyproject.toml` turns `DeprecationWarning`s raised from the project's own modules (`^features`, `^main$`, `^scripts`, `^tests`) into test errors. Module-scoped deliberately: pyrogram's own internals (e.g. `asyncio.get_event_loop()` in `pyrogram/utils.py`) and the pre-existing `unittest.case` harness warnings stay as warnings, not errors.
2. **pyroblack log-warning gate** — `_PyrogramDeprecationGuard` in `tests/conftest.py`: a logging `Handler` on the `pyrogram` root logger whose `filter()` raises `AssertionError` when a record contains `"is deprecated"`. This exists because pyroblack announces API deprecations via `log.warning(...)` (logging module), **not** Python warnings — `filterwarnings` cannot see them. Logging *filters* only run on the emitting logger, but *handler* filters run on records propagating to ancestor handlers, so one handler catches every submodule's deprecation log. Known limitation: a broad `except Exception` around a deprecated call in app code would swallow the raised error (documented in the conftest docstring).

On top of the gates, **pin/guard tests** freeze the modern API spellings so regressions fail with a clear message:

- **`tests/test_pyroblack_api_cleanup.py`** (behavioral spy pins) — recorder fakes spy on receiver methods (`reply_text` / `edit_text` / `edit_message_text` / `send_message` / `InlineQueryResultArticle` constructor) and assert the modern kwargs on every call:
  - `forward_origin` in `cmd_index_channel` (fakes expose ONLY `forward_origin`, so reverting to `forward_from_chat` raises `AttributeError` and fails)
  - `thumbnail_url` in the inline handler (constructor spy records kwargs; no deprecated `thumb_*` keys allowed)
  - `link_preview_options` across all 14 call sites in `logger.py` / `search.py` / `callbacks.py` / `commands.py` (spy asserts key presence **and** value semantics — `LinkPreviewOptions.is_disabled is True`), plus a source-level scan pinning the exact per-file counts (logger 1, search 1, callbacks 2, commands 10)
- **`tests/test_pyroblack_api_guards.py`** (source-level guards) — the remaining deprecated kwarg families that the project doesn't use yet must never be introduced: `reply_to_message_id/chat_id/sender_id/story_id=` (→ `reply_parameters=`), `thumb_url/width/height/mime_type=` (→ `thumbnail_*`), `force_document=`, `offset_id=`, `placeholder=`. Scans `features/**`, `main.py`, `scripts/` (recursive; `#` line comments are stripped so prose can't trip it).

**Contributor rules:**

- Send/edit text → `link_preview_options=LinkPreviewOptions(is_disabled=True)` — never `disable_web_page_preview`
- Reply to a message → `reply_parameters=` — never `reply_to_message_id`/`reply_to_chat_id`/`reply_to_sender_id`/`reply_to_story_id`
- Inline results → `thumbnail_url`/`thumbnail_width`/`thumbnail_height`/`thumbnail_mime_type` — never `thumb_*`
- If a pyroblack API is deliberately changed, update the pin counts in `test_pyroblack_api_cleanup.py` / `test_pyroblack_api_guards.py` — do **not** loosen the matchers to "fix" a failing test
- Both test files are standalone scripts (`python tests/test_<name>.py`) and pytest-compatible

### 12.2 HF keep-alive & log-peer warm-up

Two runtime resilience mechanisms, both started in `bot.py`'s `main()`:

**1. Self-keep-alive (`features/keepalive.py`)** — Hugging Face Spaces (free tier) put the container to sleep after a period of inactivity; only traffic to the Space's **public** URL counts as activity, and a sleeping container can't wake itself. `start_keep_alive()` spawns an asyncio task that GETs the public `/health` URL every `KEEP_ALIVE_INTERVAL` (default **240s** — deliberately below HF's 15-minute minimum sleep timer, so the Space never reaches the threshold). URL resolution order: `KEEP_ALIVE_URL` (explicit, used as-is) → `SPACE_HOST` (HF env, `/health` appended) → `SPACE_ID` (HF env, `https://<owner>-<space>.hf.space/health` derived). On non-HF hosts (VPS/Docker/local) no URL is derivable and it's a silent no-op; `KEEP_ALIVE_ENABLED=false` forces it off. Failures are logged and swallowed — the next cycle retries. Pings are console-only (added to the logger's `ignore_patterns`) so they don't spam the log channel. UptimeRobot monitors (`scripts/create_uptimerobot_monitors.py`) remain the external watchdog for cold starts, since the self-ping can't fire while the container is asleep.

**2. Log-peer warm-up (`features/logger.py`)** — `[403 PEER_ID_INVALID]` on log sends happens because the `.session` file caches peer access hashes, and a fresh session (HF rebuild, wiped `.session`) has none for `LOG_CHANNEL`. Two-part fix:

- `warm_up_peer()` — called in `bot.py` after `logger.set_client()`: runs `client.get_chat()` to fetch and cache the peer immediately, so the first flush (3s later) succeeds. Fixes channels/groups outright; for a **user** target it succeeds once the server can resolve the user (they've messaged the bot).
- `flush()` self-heal — on `PeerIdInvalid` **specifically** (`isinstance` check, so other errors keep the old behavior) it re-runs `get_chat()` once per flush, recovering automatically the moment the peer becomes reachable (e.g. the admin sends any command).

Also: `set_client()` casts `LOG_CHANNEL` to `int` (a malformed non-numeric value is kept raw + warned — it must never crash startup), and `run.sh` no longer wipes `*.session` files on every start (`CLEAN_SESSIONS=1` to force a wipe) — deleting the session cache is what caused the recurring PEER_ID_INVALID after every restart.

Pinned by `tests/test_keepalive.py` (URL derivation, mocked-aiohttp ping loop, `start_keep_alive()` gating — 12 tests) and `tests/test_logger_peer_warmup.py` (int cast incl. malformed value, `warm_up_peer`, PEER_ID_INVALID self-heal — 9 tests). Both standalone + pytest-compatible.
