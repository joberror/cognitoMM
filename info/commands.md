# 🎬 CognitoMM — Command Reference

This reference matches the **live** command handlers in `features/commands.py`
(router: `handle_command`). Earlier drafts of this file described commands that
no longer exist (`/search_type`, `/metadata`, `/my_prefs`, `/list_channels`,
`/reparse`, `/stats_db`, `/clear_db`, ...) — those were removed or renamed
during refactors. If a command is missing here, it doesn't exist; add it to the
router + this file together.

## 👤 User commands

| Command | Description |
|---|---|
| `/start` | Welcome, terms acceptance |
| `/help` | Show this menu (user + admin sections) |
| `/f <title>` | Quick search |
| `/search <title>` | Smart search (exact + fuzzy); `-e` flag for exact only. Code-block result list — one line per title with file count + latest file (`1. Lucky > 2 files > Latest: 1080p | 2.5GB | WebRip`), header with `Titles Found: N (X Exact | Y Fuzzy)` / `Files Found: N (Movie - X | Series - Y)`, and a TMDb Title(s) Information block below (⭐ · 🎭 · IMDb) that survives pagination. Every title gets `Pick [n]` (in-place filter; series also `Pick[n][Sxx]`) + `Get [n]` (latest file) |
| `/recent` | Newly indexed content (last batch) — plain HTML listing with MOVIES/SERIES sections; **tap a line to copy the `Title (year)` string, ready for `/search`** |
| `/trending` | TMDb trending movies / shows / new releases (buttons) — `/search`-style lines with ⭐ ratings + clickable IMDb/TMDb links |
| `/random` | Random indexed title (poster when available; caption uses the `/search` bracket info) |
| `/genres` | List TMDb genres with counts; `/genres <name>` browses a genre in the `/search` per-title + latest-file layout with a `Files Found: N (Movie - X | Series - Y)` header split (paginated, 12/page with `← Prev`/`Next →`, `🔤 A–Z`/`🆕 Newest`/`⭐ Top Rated` sort toggle). Each title appears ONCE: movies `1. Die Hard > 1 file > Latest: 1080p`, series `1. Breaking Bad > 4 files > 2 seasons [5] · 3 eps [35] > Latest: S01E02 | 720p ⭐8.9` — brackets are the real TMDb totals (DB counts outside). Every title gets `Pick [n]` (in-place filter view, series also `Pick[n][Sxx]` season shortcuts that page via `S◀`/`S▶` for >5 seasons) + `Get [n]` (latest copy) |
| `/request <title>` | Request a missing title (TMDb search, rate-limited) |
| `/request_list` | View/manage your requests |
| `/my_history` | Your search history (plain HTML, tap-to-copy queries, bracket = search time, grouped by date) |
| `/my_stat` | Your usage + premium info |
| `/watch <title>` | Add a title to your watchlist (notified when indexed) |
| `/unwatch <title>` | Remove from watchlist |
| `/watchlist` | Show your watched titles (plain HTML, tap-to-copy titles with year/type brackets) |
| `/premium` | Premium info / management (admin-gated actions inside) |
| Inline mode | `@yourbot <query>` — search straight from any chat (poster thumbnails) |

## 👑 Admin commands

| Command | Description |
|---|---|
| `/stat` | Full statistics dashboard (incl. prune stats) |
| `/quickstat` | Quick key numbers |
| `/broadcast <message>` | Message all users |
| `/request_list` | Manage user requests |
| `/premium` | Manage premium users + premium-gated features |
| `/mc` / `manage_channel` | Unified channel manager |
| `/add_channel <link\|id\|@username>` | Register a channel |
| `/remove_channel <link\|id>` | Unregister a channel |
| `/index_channel` | Index a channel (forward a post / link, interactive) |
| `/toggle_indexing` | Auto-indexing on/off |
| `/reset_channel` | Clear a channel's index (confirm) |
| `/update_db` | Reconcile a channel's messages vs the index (interactive) |
| `/manual_deletion <title>` | Delete indexed entries by title |
| `/indexing_stats` | Diagnose indexing skips |
| `/reset_stats` | Reset indexing counters |
| `/logs [n]` | View the most recent audit-log entries from `logs_col` (default 10, max 50) |
| `/enrich [n]` | Backfill TMDb metadata (poster/genres/rating/IMDb) for entries missing it |
| `/enrich_status` | Show how many indexed titles still lack TMDb metadata (enriched / pending / no-match) |
| `/reset` | WIPE all indexed data (confirm) |
| `/promote <user_id>` / `/demote <user_id>` | Grant/remove admin role |
| `/ban_user <user_id>` / `/unban_user <user_id>` | Ban/unban a user |

## 🔧 Config (`.env`)

See `DEPLOYMENT.md` for the full table. Feature-specific extras:

| Var | Default | Notes |
|---|---|---|
| `TMDB_API` | "" | Enables trending, requests, and TMDb enrichment (posters/genres/ratings) |
| `TMDB_ENRICH_INDEX` | `true` | Enrich newly indexed entries with TMDb metadata (cached per title) |
| `DB_RESCAN_ENABLED` | `true` | Scheduled incremental rescan (background `/update_db`) |
| `DB_RESCAN_INTERVAL_MINUTES` | `360` | Rescan cadence (every 6 hours) |
| `KEEP_ALIVE_URL` | — | Public URL self-pinged to keep managed hosts awake (HF auto-derives) |
| `KEEP_ALIVE_INTERVAL` | `240` | Self-ping seconds |
| `KEEP_ALIVE_ENABLED` | `true` | `false` disables the self-keep-alive |
| `CLEAN_SESSIONS` | `0` | `1` wipes `.session` files at startup (`run.sh` only) |

## 📦 MongoDB collections (schemas used by commands)

- `movies_col` — indexed entries: `title`, `year`, `type`, `quality`, `rip`,
  `season`, `episode`, `file_size`, `channel_id`, `channel_title`,
  `message_id`, `indexed_at`, plus optional TMDb enrichment fields
  `tmdb_poster`, `tmdb_rating`, `tmdb_genres`, `tmdb_overview`, `imdb_id`.
- `users_col` — `role`, `terms_accepted`, `search_history`,
  `download_history`, `watchlist` (array of `{title, title_key, year, type,
  added_at}`).
- `logs_col` — audit log: `{action, by, target, extra, ts}` (viewable with
  `/logs`).
- `settings_col` — key/value (`k`/`v`): `auto_indexing`, per-channel scan
  cursors `scan_cursor:<channel_id>`.
- `channels_col` — registered channels (`enabled` flag).
- `requests_col` / `user_request_limits_col` — request feature.
- `premium_users_col` / `premium_features_col` — premium system.

## 💡 Notes

- Search results deduplicate copies of the same title (best quality shown).
  `Pick [n]` filters the message in place to that title's copies (series get
  per-season `Pick[n][Sxx]` buttons; long-running series page through the
  seasons — `S◀`/`S▶` buttons in both the results list and the pick view, 10
  seasons per page); `[720p]/[1080p]/[2160p]`
  resolution filters narrow further and `← Back` restores the full results. Results carry
  TMDb ratings/genres/IMDb links when `TMDB_API` is configured.
- Watchlist notifications are sent the moment a new copy of a watched title is
  indexed (DM with a Get button).
- The scheduled rescan, orphan prune monitor, and keep-alive all run as
  background tasks started in `features/bot.py`.
