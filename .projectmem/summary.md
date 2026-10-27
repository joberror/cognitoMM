# projectmem - Code-Health

_Last updated: 2026-10-23_

## Project purpose
--- title: CognitoMM emoji: 🤖 colorFrom: blue colorTo: purple sdk: docker pinned: false ---

## Recent issues
- [DONE] #legacy_ee4c Legacy issue: fix: build premium payments charge_id unique index -> fix: build premium payments charge_id unique index (fixed)
- [DONE] #legacy_d8e9 Legacy issue: Merge pull request #16 from joberror/fix/cors-vulnerability-13519515393229990490 -> Merge pull request #16 from joberror/fix/cors-vulnerability-13519515393229990490 (fixed)
- [DONE] #legacy_c8dd Legacy issue: feat: comprehensive code health audit fixes -> feat: comprehensive code health audit fixes (fixed)
- [DONE] #legacy_9a57 Legacy issue: fix: remove circular import via lazy __getattr__ in database.py -> fix: remove circular import via lazy __getattr__ in database.py (fixed)
- [DONE] #legacy_5bd9 Legacy issue: fix: resolve TERMS_AND_PRIVACY.md path from module directory -> fix: resolve TERMS_AND_PRIVACY.md path from module directory (fixed)
- [DONE] #legacy_1c18 Legacy issue: Merge pull request #17 from joberror/fix-nosql-injection-manual-deletion-4136562116857209932 -> Merge pull request #17 from joberror/fix-nosql-injection-manual-deletion-4136562116857209932 (fixed)
- [DONE] #legacy_0e88 Legacy issue: 🔒 Fix NoSQL Injection via RegExp Search in manual_deletion command -> 🔒 Fix NoSQL Injection via RegExp Search in manual_deletion command (fixed)

## Decisions
- No decisions logged yet.

## Notes
- test: format percentage division by zero handling
- Merge pull request #18 from joberror/test-format-percentage-7455801531571327889
- test: add test coverage for format_number edge cases
- Merge pull request #19 from joberror/test/statistics-format-number-edge-cases-12337536621354980617
- security: validate IMDb ID format in caption to prevent HTML injection
- health: track background tasks for graceful shutdown
- health: add thread safety for _bot_info_cache
- perf: batch premium checks in /stat to eliminate N+1 queries
- perf: batch insert in indexing to eliminate N+1 round-trips
- perf: concurrent broadcast sends with semaphore rate limiting

## Key files
- `features/database_scan.py`
- `features/webapp.py`
- `features/commands.py`
- `tests/test_statistics_format.py`
- `database.py`
- `features/database.py`
- `tests/test_consolidation.py`
- `features/utils.py`
- `features/bot.py`
- `features/statistics.py`
- `features/indexing.py`
- `features/broadcast.py`
- `features/__init__.py`
- `features/callbacks.py`
- `features/config.py`
- `features/deletion_events.py`
- `features/file_deletion.py`
- `features/metadata_parser.py`
- `features/premium_commands.py`
- `features/premium_management.py`

## Open questions
- None logged yet.
