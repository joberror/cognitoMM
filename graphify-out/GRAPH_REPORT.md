# Graph Report - cognitoMM  (2026-10-01)

## Corpus Check
- 124 files · ~153,306 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 11 file(s) not represented in the graph (top: (none) 5, .example 2, .nix 1)

## Summary
- 2574 nodes · 5329 edges · 151 communities (108 shown, 43 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 340 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Command Handlers Router
- Request Feature Commands
- Watchlist Notification Floodgate
- Callbacks and User Access Control
- Telegram Logging System
- Bot Startup and Configuration
- Scan Message Range Tests
- User Dashboard Commands
- Update DB Guard Tests
- Features Package Core and Stats Store
- Premium Plans and Download Quota
- Critical Bug Fix Regression Tests
- Real-Time Deletion Event Handling
- Retry Backoff and FloodWait Reliability
- Metadata Parser Consolidation Guards
- Re-Export Chain Static Check
- Index Queue Admin Command
- User Role Actions and Dashboard Tests
- Request Validation and Fuzzy Dedup
- Re-Export Checker Tests
- Statistics Formatting and CSV Export
- Metadata Extraction Parser Tests
- Bulk File Delivery and Stars Invoice
- Link Preview Disabled Assertions
- Premium and Broadcast Command Docs
- Filename Metadata Parser Engine
- Async Cursor and Timezone Test Fakes
- Health Check and Metrics Webapp
- Incremental Database Rescan
- Title Pick Filter View
- UptimeRobot Monitor Setup
- Keep-Alive Task Scheduling
- Search Results Pagination UI
- User Dashboard Page Rendering
- Version Bump Pre-Commit Gate
- Search Pagination Callback Tests
- Premium Admin Command Handlers
- Download Retention Policy Tests
- Broadcast System
- MongoDB Connection and Indexes
- Genre Browse Command Tests
- Stats Provider and Metrics Endpoint
- Version Bump Script
- Stat Output Formatting Docs
- User Action Preview Flow
- Dashboard Target Resolution
- TMDb Backfill Enrichment Tests
- Filename Parser Engine Internals
- Quality Ranking and Feature Tests
- Genre Browse Callback Tests
- Codebase Architecture Notes
- Auto-Delete Cleanup Tests
- Orphan Index Pruning
- Search Filtering and Season Grouping
- Project README Overview
- Router Access Gate Callback Tests
- Users Collection Watchlist Fakes
- CI and Dependabot Configuration
- Genre Details and Pick Line Formatting
- Code Health Gate Tests
- Deprecated Pyroblack API Cleanup
- Python Code Guide Docs
- TMDb Enrichment and Backfill
- Movie Bot System Overview
- Orphan Prune Test Fakes
- Channel Index Command Tests
- Title Info Block and Bulk Cleanup
- Text Index Language Override
- Genre Aggregation Pipeline Tests
- Inline Query Test Fakes
- Deployment and HF Spaces Docs
- Premium Purchase and Quota UI
- Structured Search Query Parser
- Watchlist Feature Tests
- Keep-Alive HTTP Pinger
- Request Feature Docs
- Watchlist Cooldown Test Fakes
- Auto-Delete Test Report Script
- Callback Link Preview Tests
- Search Library Facet Tests
- Watchlist Series Burst Tests
- Broadcast Documentation
- Session Generation and Smoke Test
- Dashboard Preview and Target Parsing
- Background Task Documentation
- Chainable Async Cursor Fakes
- Watchlist Command Tests
- Watchlist Update Tests
- Terms Acceptance System Docs
- Title Extraction Test Script
- Enrich Status and Logs Command Tests
- User Statistics Dashboard Design
- Auto-Delete Report Findings
- Bot Identity Cache for Stats
- Recent Results HTML Formatting
- HTTP Client Error Handling Tests
- Premium Gating and Fuzzy Dedup Docs
- File Deletion Persistence
- Backfill CLI Slice Processing
- Scan Flood Retry Tests
- Server-Side Filter Tests
- Auto-Delete Background Task Tests
- Mongo Search Filter Builder
- Watch Title Ambiguity Picker
- Telegram Logger LPO Value Tests
- Motor Cursor Test Double
- Test Result Accumulator
- Chainable Cursor Double
- Recent Command LPO Tests
- Async Cursor Double
- Antigravity Workflow Rules
- Extended Pyrogram Client
- Enrichment Cache
- Channel Auto-Indexing Docs
- Statistics Command Docs
- Keep-Alive Failure Tolerance Tests
- AIOHTTP Session Test Double
- Get Messages Test Double
- Sent Message Test Double
- Watchlist Capacity Gate Tests
- User Dashboard Keyboard Builder
- Rescan Window Cursor Tests
- Callback Message Test Double
- Active Filter Header Formatting
- Watch Candidate Ranking
- Backfill Dry-Run Mode
- Rescan Empty History Test
- Failing Collection Test Double
- Graphify Skill Workflow Docs
- Run Script CLI
- Merged Module Guard
- Database Duplicate Definition Guard
- MCP Context Engine Config
- Credential Guard Test
- Bit Depth Extraction Guard
- Bracketed Metadata Ownership Guard
- Publisher Field Extraction Guard
- No Fallback Blocks Guard
- IMDB ID Engine Ownership
- Parser Pure Mapper Guard
- Grouping Helper Single Home
- Search Duplicate Definition Guard
- Series Episode Range Formatting
- Engine and API Title Agreement
- Format Size Removal Guard
- Statistics Formatter Removal Guard
- Pillow Dependency

## God Nodes (most connected - your core abstractions)
1. `callback_handler()` - 64 edges
2. `handle_command()` - 47 edges
3. `is_admin()` - 46 edges
4. `Env` - 46 edges
5. `log_action()` - 43 edges
6. `parse_metadata()` - 38 edges
7. `main()` - 33 edges
8. `_install()` - 32 edges
9. `render_user_page()` - 29 edges
10. `run()` - 28 edges

## Surprising Connections (you probably didn't know these)
- `pytest unit, fixture and integration testing` --semantically_similar_to--> `Terms acceptance manual QA protocol`  [INFERRED] [semantically similar]
  .agent/rules/python-code-guide.md → tests/TESTING_GUIDE.md
- `User statistics and profile dashboard feature` --semantically_similar_to--> `/stat admin dashboard`  [INFERRED] [semantically similar]
  .claude/agents/user-stats-dashboard.md → info/commands.md
- `Full pytest suite job` --conceptually_related_to--> `Terms acceptance manual QA protocol`  [AMBIGUOUS]
  .github/workflows/static-checks.yml → tests/TESTING_GUIDE.md
- `Fourteen test scenarios` --references--> `Removed/renamed command discipline`  [AMBIGUOUS]
  tests/TESTING_GUIDE.md → info/commands.md
- `_run()` --calls--> `callback_handler()`  [EXTRACTED]
  tests/test_auto_delete.py → features/callbacks.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Statistics Dashboard Collect-Format-Export Pipeline** — stat_feature_plan_collect_comprehensive_stats, stat_feature_implementation_statistics_module, stat_feature_implementation_parallel_data_collection, stat_feature_implementation_timeout_protection, stat_feature_enhanced_plan_stats_caching, stat_feature_enhanced_plan_export_functionality [INFERRED 0.85]
- **Stat Output Formatting Evolution (Markdown -> HTML -> Box-Drawing)** — formatting_updates_complete_formatting_rollup, formatting_updates_complete_html_parse_mode, my_stat_formatting_update_my_stat_formatting, stat_command_formatting_update_stat_html_formatting, refined_formatting_update_box_drawing_design, stat_feature_update_bot_information_section [EXTRACTED 1.00]
- **Request Feature End-to-End Lifecycle** — request_feature_request_flow, request_feature_admin_actions, request_feature_requests_collection, implementation_summary_request_rate_limiting, implementation_summary_duplicate_detection, implementation_summary_request_pagination, quick_start_requests_rate_limit_constants, tmdb_integration_summary_search_tmdb [INFERRED 0.85]
- **Static Checks CI quality gates** — _github_workflows_static_checks_reexport_check, _github_workflows_static_checks_lint, _github_workflows_static_checks_tests, _github_workflows_static_checks_python_312 [EXTRACTED 1.00]
- **CognitoMM MongoDB collection set** — info_commands_movies_col, info_commands_users_col, info_commands_logs_col, info_commands_settings_col, info_commands_channels_col, info_commands_requests_col, info_commands_premium_users_col [EXTRACTED 1.00]
- **Bot indexing ingest pipeline** — info_architecture_channel_monitoring, info_architecture_metadata_extraction, info_architecture_telegram_file_details, info_architecture_auto_indexing, info_architecture_mongodb_atlas_integration [EXTRACTED 1.00]

## Communities (151 total, 43 thin omitted)

### Community 0 - "Command Handlers Router"
Cohesion: 0.06
Nodes (45): cmd_add_channel(), cmd_ban_user(), cmd_demote(), cmd_enrich(), cmd_enrich_status(), cmd_genres(), cmd_help(), cmd_index_channel() (+37 more)

### Community 1 - "Request Feature Commands"
Cohesion: 0.05
Nodes (28): is_feature_premium_only(), cmd_request(), cmd_request_list(), send_request_list_page(), check_rate_limits(), find_global_match(), get_queue_position(), _request_matches() (+20 more)

### Community 2 - "Watchlist Notification Floodgate"
Cohesion: 0.05
Nodes (26): fulfill_matching_requests(), add_to_watchlist(), _cooldown_active(), _notify_identity(), notify_watchlist(), _watch_key(), FakeUsersCollection, test_notify_watchlist_dms_matching_users() (+18 more)

### Community 3 - "Callbacks and User Access Control"
Cohesion: 0.07
Nodes (25): normalize_content_type(), get_watchlist(), _load_user_roles(), remove_from_watchlist(), role_guard_verdict(), update_watchlist_status(), watchlist_capacity(), cmd_unwatch() (+17 more)

### Community 4 - "Telegram Logging System"
Cohesion: 0.06
Nodes (15): _StreamWrapper, TelegramLogger, FakeClient, main(), run_async(), test_flush_other_errors_do_not_re_resolve(), test_flush_self_heals_on_peer_id_invalid(), test_set_client_accepts_int_channel() (+7 more)

### Community 5 - "Bot Startup and Configuration"
Cohesion: 0.06
Nodes (20): main(), run_bot(), TempData, start_deletion_monitor(), start_orphan_prune_monitor(), add_premium_user(), _day_key(), get_all_premium_users() (+12 more)

### Community 6 - "Scan Message Range Tests"
Cohesion: 0.08
Nodes (19): existing_docs(), FakeClient, FakeCursor, FakeMedia, FakeMoviesCol, FakeMsg, main(), run_scan() (+11 more)

### Community 7 - "User Dashboard Commands"
Cohesion: 0.05
Nodes (25): _active_premium_ids(), _ago(), build_prompt(), can_use_dashboard(), cancel_user_action(), confirm_user_action(), _deliver(), _fetch_page() (+17 more)

### Community 8 - "Update DB Guard Tests"
Cohesion: 0.06
Nodes (17): existing_docs(), FakeChannelsCol, FakeClient, FakeCursor, FakeMessage, FakeMoviesCol, FakeMsg, FakeSent (+9 more)

### Community 9 - "Features Package Core and Stats Store"
Cohesion: 0.06
Nodes (20): cleanup_expired_premium(), toggle_feature(), format_tmdb_result(), check_terms_acceptance(), get_user_doc(), has_accepted_terms(), is_banned(), load_terms_and_privacy() (+12 more)

### Community 10 - "Premium Plans and Download Quota"
Cohesion: 0.08
Nodes (20): _parse_premium_plans(), check_download_quota(), FakeClient, FakeCursor, FakePaymentMessage, FakePaymentsCol, FakePremiumUsersCol, FakeUsersCol (+12 more)

### Community 11 - "Critical Bug Fix Regression Tests"
Cohesion: 0.08
Nodes (19): FakeChannelsCol, main(), make_message(), run_should_process(), _is_admin(), test_access_control_not_duplicated_in_utils(), test_add_channel_end_to_end(), test_admin_allowed_in_random_group() (+11 more)

### Community 12 - "Real-Time Deletion Event Handling"
Cohesion: 0.08
Nodes (13): _extract_channel_id(), _extract_message_ids(), handle_raw_update(), _install_pyrogram_deprecation_guard(), _no_uvloop_policy(), _PyrogramDeprecationGuard, FakeChannelsCollection, FakeMoviesCollection (+5 more)

### Community 13 - "Retry Backoff and FloodWait Reliability"
Cohesion: 0.10
Nodes (20): add_jitter(), compute_delay(), flood_wait_seconds(), FloodWait, is_flood_wait(), jittered_sleep(), retry_on_flood(), struct_log() (+12 more)

### Community 14 - "Metadata Parser Consolidation Guards"
Cohesion: 0.05
Nodes (18): test_construct_final_caption_uses_canonical_formatter(), test_engine_bracket_dts_hd_ma_full_form(), test_engine_hdr_no_dv_false_positive(), test_engine_owns_multi_year_1917(), test_engine_owns_multi_year_2001(), test_engine_owns_same_year_title_year(), test_engine_publisher_coexists_with_rip(), test_engine_publisher_via_bracket_and_underscore() (+10 more)

### Community 15 - "Re-Export Chain Static Check"
Cohesion: 0.09
Nodes (17): _collect_symbols(), _collect_targets(), _lazy_reexport_names(), main(), _module_level_defs(), _module_package(), _module_path(), _resolve_source() (+9 more)

### Community 16 - "Index Queue Admin Command"
Cohesion: 0.11
Nodes (15): cmd_queue(), FakeChannelsCol, FakeCursor, FakeMessage, FakeSettingsCol, _install(), _restore(), run() (+7 more)

### Community 17 - "User Role Actions and Dashboard Tests"
Cohesion: 0.10
Nodes (20): apply_role_action(), _boom(), days_ago(), Env, in_days(), role_of(), test_alias_demote_requires_a_super_admin(), test_alias_skips_guarded_targets_in_the_summary() (+12 more)

### Community 18 - "Request Validation and Fuzzy Dedup"
Cohesion: 0.10
Nodes (11): check_duplicate_request(), validate_imdb_link(), FakeCursor, FakeRequestCollection, _install_fakes(), main(), test_duplicate_detection(), _test_duplicate_detection() (+3 more)

### Community 19 - "Re-Export Checker Tests"
Cohesion: 0.09
Nodes (14): test_current_repo_is_clean(), test_duplicate_check_flags_same_helper_in_two_modules(), test_duplicate_check_ignores_class_methods(), test_duplicate_check_ignores_module_dunders(), test_duplicate_check_ignores_unique_names(), test_duplicate_check_skips_allowlisted(), test_scanner_allows_absolute_and_submodule_imports(), test_scanner_allows_aliased_imports() (+6 more)

### Community 20 - "Statistics Formatting and CSV Export"
Cohesion: 0.12
Nodes (17): create_progress_bar(), export_stats_csv(), format_number(), format_percentage(), format_quick_stats_output(), format_stats_output(), _errors_lines(), main() (+9 more)

### Community 21 - "Metadata Extraction Parser Tests"
Cohesion: 0.12
Nodes (11): compare_field(), main(), print_test_result(), test_case_1_star_wars_visions(), test_case_2_the_witcher(), test_case_3_hazbin_hotel(), test_case_4_dune_dolby_vision(), test_case_5_avatar_dts_hd() (+3 more)

### Community 22 - "Bulk File Delivery and Stars Invoice"
Cohesion: 0.09
Nodes (13): callback_handler(), _deliver_bulk_files(), start_indexing_process(), get_all_premium_features(), send_premium_invoice(), export_stats_json(), get_cached_trending(), get_imdb_id() (+5 more)

### Community 23 - "Link Preview Disabled Assertions"
Cohesion: 0.12
Nodes (14): _assert_link_preview_only(), FakeUserMsg, run_all(), _sent_msgs(), test_cmd_indexing_stats_uses_link_preview_options(), test_cmd_my_history_plain_html_tap_to_copy(), test_cmd_my_history_uses_link_preview_options(), test_cmd_quickstat_uses_link_preview_options() (+6 more)

### Community 24 - "Premium and Broadcast Command Docs"
Cohesion: 0.10
Nodes (26): /broadcast command, /buy_premium command, CognitoMM command reference, /enrich TMDb backfill, /genres command, handle_command router in features/commands.py, Inline query mode, /logs audit view (+18 more)

### Community 25 - "Filename Metadata Parser Engine"
Cohesion: 0.08
Nodes (10): demo(), MovieFilenameParser, test_engine_full_text_scan_sees_brackets_and_underscores(), test_engine_handles_ch_suffixed_channels(), test_engine_m4a_is_audio_codec(), test_engine_owns_multi_year_2012(), test_engine_sets_quality_from_resolution(), test_engine_xdim_resolution() (+2 more)

### Community 26 - "Async Cursor and Timezone Test Fakes"
Cohesion: 0.10
Nodes (8): _as_utc(), FakeCursor, FakeLogsCol, FakePremiumCol, FakeUsersCol, _geq(), _match(), _sort_key()

### Community 27 - "Health Check and Metrics Webapp"
Cohesion: 0.10
Nodes (9): add_cors_headers(), _get_port(), health_check(), index(), metrics(), _MongoJSONProvider, robots_txt(), run_flask() (+1 more)

### Community 28 - "Incremental Database Rescan"
Cohesion: 0.11
Nodes (10): get_channel_scan_cursor(), incremental_rescan(), scan_message_range(), set_channel_scan_cursor(), start_db_rescan_monitor(), index_message(), process_message_queue(), save_file_to_db() (+2 more)

### Community 29 - "Title Pick Filter View"
Cohesion: 0.11
Nodes (15): build_pick_view(), render_pick_view(), _flat_buttons(), movie(), _series_copies(), test_build_pick_view_movie_lists_every_copy(), test_build_pick_view_movie_resolution_filter(), test_build_pick_view_resolution_filter_keeps_season_page() (+7 more)

### Community 30 - "UptimeRobot Monitor Setup"
Cohesion: 0.12
Nodes (14): build_monitors(), create_monitors(), existing_monitor_urls(), _headers(), main(), _request(), test_build_monitors_urls_and_keywords(), test_create_monitors_api_error_raises() (+6 more)

### Community 31 - "Keep-Alive Task Scheduling"
Cohesion: 0.14
Nodes (13): derive_keep_alive_url(), start_keep_alive(), key(), main(), undo(), test_explicit_url_used_as_is(), test_explicit_url_wins_over_hf_vars(), test_no_url_when_nothing_configured() (+5 more)

### Community 32 - "Search Results Pagination UI"
Cohesion: 0.14
Nodes (17): build_search_keyboard(), build_search_page(), group_by_title(), render_search_page(), episode(), test_build_pick_view_caps_long_episode_lists(), test_build_search_keyboard_clamps_stale_season_page(), run() (+9 more)

### Community 33 - "User Dashboard Page Rendering"
Cohesion: 0.13
Nodes (14): render_user_page(), FakeMessage, list_block(), listed_ids(), test_active_filter_uses_a_seven_day_window(), test_alias_is_private_only_and_admin_only(), test_dashboard_is_private_and_admin_only(), test_header_counts_stay_exact_at_scale() (+6 more)

### Community 34 - "Version Bump Pre-Commit Gate"
Cohesion: 0.13
Nodes (14): added_files(), check(), _git(), main(), new_feature_lines(), version_bumped(), test_added_files_parser(), test_gate_fails_new_handler_without_bump() (+6 more)

### Community 35 - "Search Pagination Callback Tests"
Cohesion: 0.14
Nodes (13): FakeCallbackQuery, main(), _run_callback(), test_back_callback_ownership_guard(), test_back_callback_restores_search_page(), test_choose_callback_filters_in_place(), test_choose_callback_legacy_5_part_data(), test_choose_callback_ownership_guard() (+5 more)

### Community 36 - "Premium Admin Command Handlers"
Cohesion: 0.15
Nodes (10): handle_add_premium_feature(), handle_add_premium_user(), handle_edit_premium_user(), handle_premium_user_input(), handle_remove_premium_user(), add_premium_feature(), edit_premium_user(), get_days_remaining() (+2 more)

### Community 37 - "Download Retention Policy Tests"
Cohesion: 0.12
Nodes (11): retention_warn_minutes(), FakeCallbackMsg, FakeCallbackQuery, FakeClient, run(), test_get_retention_minutes_by_tier(), test_getpack_delivers_copies(), test_monitor_uses_stored_warn_minutes() (+3 more)

### Community 38 - "Broadcast System"
Cohesion: 0.14
Nodes (9): cmd_broadcast(), execute_broadcast(), format_progress_message(), format_summary_message(), get_broadcast_recipients(), log_broadcast(), send_broadcast_message(), get_readable_time() (+1 more)

### Community 39 - "MongoDB Connection and Indexes"
Cohesion: 0.13
Nodes (11): ensure_indexes(), __getattr__(), resolve_mongo_uri(), test_empty_uri_no_longer_crashes_client_construction(), test_ensure_indexes_fails_fast_when_uri_missing(), test_resolve_mongo_uri_blank_falls_back_to_localhost(), test_resolve_mongo_uri_empty_falls_back_to_localhost(), test_resolve_mongo_uri_none_falls_back_to_localhost() (+3 more)

### Community 40 - "Genre Browse Command Tests"
Cohesion: 0.11
Nodes (8): FakeMessage, test_cmd_genres_browse_empty_genre(), test_cmd_genres_browse_paginates(), test_cmd_random_caption_uses_bracket_style(), test_genre_results_season_paging(), test_new_commands_are_routed(), _no(), recorder()

### Community 41 - "Stats Provider and Metrics Endpoint"
Cohesion: 0.13
Nodes (9): set_stats_provider(), running_loop(), test_metrics_provider_dict_returns_200_with_data(), provider(), test_metrics_provider_none_returns_500_error(), test_metrics_provider_raises_returns_500(), test_metrics_provider_with_objectid_serializes(), test_metrics_unregistered_returns_stub() (+1 more)

### Community 42 - "Version Bump Script"
Cohesion: 0.16
Nodes (13): bump(), main(), read_version(), set_version(), _config_text(), test_bump_parts(), test_cli_dry_run_writes_nothing(), test_cli_patch_bump_writes_files() (+5 more)

### Community 43 - "Stat Output Formatting Docs"
Cohesion: 0.15
Nodes (16): Datetime Timezone Fix Summary, Complete Formatting Updates Summary, /my_stat HTML Formatting Update, premium_users Collection, Refined Box-Drawing Formatting Update, /stat HTML Formatting Update, asyncio.gather Parallel Data Collection, features/statistics.py Statistics Module (+8 more)

### Community 44 - "User Action Preview Flow"
Cohesion: 0.17
Nodes (13): start_user_action(), _store_pending_action(), FakeCallbackQuery, _queue_input(), _fake_wait(), test_cancel_writes_nothing(), test_confirm_writes_roles_and_shows_the_result_banner(), test_pending_action_state_is_reaped_by_the_cleanup_sweep() (+5 more)

### Community 45 - "Dashboard Target Resolution"
Cohesion: 0.13
Nodes (9): resolve_targets(), FakeClient, FakeUser, test_aliases_route_through_apply_role_action(), test_hostile_names_are_html_escaped(), test_lookup_failure_degrades_to_dashes(), test_lookup_failure_never_blocks_the_admin(), test_mixed_comma_parsing_resolves_names_and_roles() (+1 more)

### Community 46 - "TMDb Backfill Enrichment Tests"
Cohesion: 0.15
Nodes (9): count_pending(), _doc(), FakeMovies, test_backfill_concurrency_maps_all_fields(), test_backfill_enriches_and_maps_fields(), fake_enrich(), test_backfill_respects_limit(), __init__() (+1 more)

### Community 48 - "Quality Ranking and Feature Tests"
Cohesion: 0.11
Nodes (9): quality_rank(), main(), test_cmd_my_history_bracket_listing(), test_cmd_watchlist_renders_bracket_lines(), test_format_enrichment_line(), test_genre_page_callback_ownership_guard(), test_genre_pick_callback_ownership_guard(), test_pick_best_quality_returns_highest_copy() (+1 more)

### Community 49 - "Genre Browse Callback Tests"
Cohesion: 0.17
Nodes (10): _FakeGenreCbq, _flat(), _genre_doc(), test_genre_back_callback_restores_page(), test_genre_page_callback_legacy_3_part_uses_stored_sort(), test_genre_page_callback_paginates(), test_genre_page_callback_rating_sort(), test_genre_page_callback_sort_toggle() (+2 more)

### Community 50 - "Codebase Architecture Notes"
Cohesion: 0.17
Nodes (15): callback_handler Inline-Button Flows (64-byte callback data), CI Gates (static-checks.yml delegating to Makefile), CognitoMM Codebase Notes, handle_command Command Router (40 command strings), Channel Auto-Indexing Flow (queue-based), features/ Module Map, Scheduled Incremental Rescan Monitor, Exact plus Fuzzy Search Flow (+7 more)

### Community 51 - "Auto-Delete Cleanup Tests"
Cohesion: 0.19
Nodes (11): cleanup_expired_file_deletions(), track_file_for_deletion(), _fresh_lock_patch(), test_cleanup_functionality(), _run(), test_edge_cases(), _run(), test_file_tracking_system() (+3 more)

### Community 52 - "Orphan Index Pruning"
Cohesion: 0.20
Nodes (9): prune_orphaned_index_entries(), main(), make_docs(), reset_prune_stats(), run_all(), run_error_path_stats(), run_flood_pause_stats(), run_no_client_no_stats() (+1 more)

### Community 53 - "Search Filtering and Season Grouping"
Cohesion: 0.20
Nodes (8): filter_copies(), group_seasons(), is_series(), normalize_resolution(), _season_number(), test_filter_copies_coerces_string_seasons(), test_group_seasons_and_filter_copies(), test_normalize_resolution()

### Community 54 - "Project README Overview"
Cohesion: 0.14
Nodes (16): Bot-session command handlers (start, help, search), main() starting both Telegram clients, Environment configuration block (API_ID, tokens, MONGO_URI, ADMINS), search_hybrid exact-plus-fuzzy search, Hybrid Telegram Movie Bot (user session + bot session), metadata command handler, movies_col collection (draft code), search_type command handler (+8 more)

### Community 55 - "Router Access Gate Callback Tests"
Cohesion: 0.14
Nodes (14): _allow_callbacks(), FakeQueryWithMessage, test_picker_button_adds_through_router(), _t(), test_picker_cancel_via_router(), _t(), test_picker_expired_token_is_refused(), _t() (+6 more)

### Community 56 - "Users Collection Watchlist Fakes"
Cohesion: 0.13
Nodes (6): _element_matches(), FakeCursor, FakeUsersCol, _positional_match(), test_failed_dm_does_not_burn_the_window(), _t()

### Community 57 - "CI and Dependabot Configuration"
Cohesion: 0.16
Nodes (15): Virtualenv and requirements.txt / pyproject.toml dependency management, Clean code and PEP 8 style principles, Dependabot v2 configuration, GitHub Dependabot configuration schema reference, Sync to Hugging Face Hub workflow, iamjoberror/bot-media Gradio Space target, huggingface/hub-sync@v0.2.1 action, sync-to-hub job (+7 more)

### Community 58 - "Genre Details and Pick Line Formatting"
Cohesion: 0.12
Nodes (9): _format_genre_details(), _genre_title_pipeline(), send_genre_page(), pick_callback(), format_latest_info(), format_pick_line(), latest_copy(), series_label() (+1 more)

### Community 60 - "Deprecated Pyroblack API Cleanup"
Cohesion: 0.14
Nodes (7): channel_forward_msg(), main(), plain_text_msg(), SpyArticle, test_index_channel_extracts_channel_from_forward_origin(), test_index_channel_rejects_non_forwarded(), test_link_preview_options_migration_fully_applied()

### Community 61 - "Python Code Guide Docs"
Cohesion: 0.15
Nodes (14): Data processing guidance, Machine learning workflow and experiment tracking, Model deployment with FastAPI/Flask and Docker, Performance optimization (vectorization, multiprocessing, async), Python Code Guide, pytest unit, fixture and integration testing, aiohttp (async HTTP client), Flask (web framework) (+6 more)

### Community 62 - "TMDb Enrichment and Backfill"
Cohesion: 0.16
Nodes (8): _genre_real_counts(), enrich_title(), _resolve_tmdb_id(), backfill(), _lookup(), _masked_host(), run(), test_masked_host_redacts_credentials()

### Community 63 - "Movie Bot System Overview"
Cohesion: 0.19
Nodes (14): Telegram movie bot system overview, Channel monitoring, Implementation roadmap, Movie metadata extraction, MongoDB Atlas integration, Movie document schema, MTProto API via Kurigram, Search engine (+6 more)

### Community 64 - "Orphan Prune Test Fakes"
Cohesion: 0.16
Nodes (5): FakeClient, FakeMessage, FakeMoviesCollection, main(), run_test()

### Community 65 - "Channel Index Command Tests"
Cohesion: 0.12
Nodes (7): FakeIndexClient, non_channel_chat_forward_msg(), run_index_channel(), test_index_channel_message_link_path_still_works(), test_index_channel_rejects_non_channel_chat_forward(), test_index_channel_rejects_user_forward(), user_forward_msg()

### Community 66 - "Title Info Block and Bulk Cleanup"
Cohesion: 0.14
Nodes (7): build_title_info_block(), _copy_type_label(), _fetch_metas(), send_search_results(), cleanup_expired_bulk_downloads(), pick_best_quality(), test_build_title_info_block_renders_meta()

### Community 67 - "Text Index Language Override"
Cohesion: 0.19
Nodes (7): RecordingCol, run(), test_text_index_uses_language_override(), check(), test_unique_indexes_still_created(), check(), _with_fakes()

### Community 68 - "Genre Aggregation Pipeline Tests"
Cohesion: 0.16
Nodes (3): FakeGenreMovies, test_cmd_genres_series_deduped_with_real_counts(), test_genre_files_split_mixed_types()

### Community 69 - "Inline Query Test Fakes"
Cohesion: 0.13
Nodes (6): FakeAnswerClient, FakeCursor, FakeInlineMoviesCol, FakeInlineQuery, from_user, test_inline_handler_uses_thumbnail_url()

### Community 70 - "Deployment and HF Spaces Docs"
Cohesion: 0.21
Nodes (11): HF Spaces Self-Keep-Alive (start_keep_alive), CognitoMM Deployment Guide, Docker Compose App plus MongoDB Stack, Hugging Face Spaces Deployment and GitHub Sync, Monitoring Endpoints (health, metrics, robots), UptimeRobot Health and Metrics Monitors, cognito_bot App Service, Container Healthchecks (GET /health) (+3 more)

### Community 71 - "Premium Purchase and Quota UI"
Cohesion: 0.15
Nodes (7): cmd_buy_premium(), get_download_quota_status(), get_retention_minutes(), is_premium_user(), build_plans_keyboard(), format_plans_text(), test_plans_keyboard_and_text()

### Community 72 - "Structured Search Query Parser"
Cohesion: 0.20
Nodes (9): _normalize_quality_token(), parse_search_query(), test_build_search_page_shows_filters(), test_parse_basic_title_only(), test_parse_paren_year_and_kv(), test_parse_series_and_4k_alias(), test_parse_title_words_preserved(), test_parse_trailing_facets() (+1 more)

### Community 73 - "Watchlist Feature Tests"
Cohesion: 0.15
Nodes (7): _array_field_matches(), _doc_matches(), _restore_module_state(), test_normalize_content_type(), test_router_covers_both_watch_callback_prefixes(), test_watchlist_escapes_html(), test_watchlist_line_format_matches_spec()

### Community 74 - "Keep-Alive HTTP Pinger"
Cohesion: 0.18
Nodes (6): keep_alive_enabled(), keep_alive_interval(), keep_alive_loop(), _ping_once(), test_keep_alive_interval_default_and_override(), test_keep_alive_loop_noop_without_url()

### Community 75 - "Request Feature Docs"
Cohesion: 0.23
Nodes (13): Eligible Broadcast Recipient Query, MongoDB Collections, Indexes and tmdb_id Identity, Title Request Flow with Rate Limits, requests and user_request_limits Collections, Request Feature Implementation Summary, Request Queue Pagination (9 per page), Request Rate Limits (3 pending / 1 per day / 20 global), Rate-Limit Constants in request_management.py (+5 more)

### Community 76 - "Watchlist Cooldown Test Fakes"
Cohesion: 0.15
Nodes (8): reset_notify_cooldowns(), reset_refresh_state(), FakeClient, _install(), test_add_without_tmdb_stores_no_null_placeholders(), _t(), test_cooldown_expires(), _t()

### Community 77 - "Auto-Delete Test Report Script"
Cohesion: 0.19
Nodes (5): generate_test_report(), main_test(), test_integration_points(), _run(), test_syntax_and_imports()

### Community 78 - "Callback Link Preview Tests"
Cohesion: 0.15
Nodes (4): FakeCallbackMsg, FakeCallbackQuery, test_search_pagination_callback_uses_link_preview_options(), test_trending_callback_uses_link_preview_options()

### Community 79 - "Search Library Facet Tests"
Cohesion: 0.22
Nodes (9): FakeMoviesCol, main(), run(), test_header_shows_library_facets(), test_parse_library_facets(), test_parse_quoted_multiword_language(), test_perform_search_bare_hdr_exists(), test_perform_search_pushes_library_facets() (+1 more)

### Community 80 - "Watchlist Series Burst Tests"
Cohesion: 0.15
Nodes (11): run(), test_add_stores_full_detail_and_stays_idempotent(), _t(), test_floodgate_is_per_title_not_global(), _t(), test_series_burst_dms_once(), _t(), test_update_skips_entries_without_tmdb_id() (+3 more)

### Community 81 - "Broadcast Documentation"
Cohesion: 0.21
Nodes (9): Broadcast Audit Logging (log_action + broadcasts_col), Broadcast System Implementation Summary, features/broadcast.py Command Module, Broadcast System Architecture Design, broadcasts_col Schema and Indexes, Broadcast Error Handling Strategy, Broadcast Progress Tracking, Admin Broadcast Flow (+1 more)

### Community 82 - "Session Generation and Smoke Test"
Cohesion: 0.20
Nodes (3): on_message(), start_command(), test_command()

### Community 83 - "Dashboard Preview and Target Parsing"
Cohesion: 0.17
Nodes (7): build_preview_text(), run_user_search(), format_role_target_lines(), parse_target_tokens(), role_target_label(), test_parse_target_tokens_accepts_ids_and_handles(), test_role_summary_and_target_lines()

### Community 84 - "Background Task Documentation"
Cohesion: 0.23
Nodes (10): Background tasks started in features/bot.py, Scheduled incremental DB rescan, .env configuration table, Tier-based file retention auto-delete, Keep-alive self-ping, TMDB_API integration, /update_db reconcile command, /watch command (+2 more)

### Community 86 - "Watchlist Command Tests"
Cohesion: 0.17
Nodes (9): FakeMessage, test_unwatch_removes(), _t(), test_watch_no_tmdb_match_still_tracks_title(), _t(), test_watch_without_title_shows_usage(), _t(), test_watchlist_command_renders_with_buttons() (+1 more)

### Community 87 - "Watchlist Update Tests"
Cohesion: 0.17
Nodes (9): FakeQuery, test_update_all_refreshes_statuses(), _t(), test_update_cooldown_blocks_rapid_taps(), _t(), test_update_one_entry_only(), _t(), test_update_rejects_other_users_message() (+1 more)

### Community 88 - "Terms Acceptance System Docs"
Cohesion: 0.23
Nodes (11): Access gate for commands, inline queries and callbacks, @CognitoMMBot (bot id 8336034036), Database verification queries, Terms acceptance manual QA protocol, Missing TERMS_AND_PRIVACY.md error handling, Success criteria checklist, terms_accepted / terms_accepted_at / last_seen user state, Terms of Use and Privacy Policy acceptance system (+3 more)

### Community 89 - "Title Extraction Test Script"
Cohesion: 0.27
Nodes (4): main(), print_test_result(), run_test(), TestCase

### Community 90 - "Enrich Status and Logs Command Tests"
Cohesion: 0.18
Nodes (3): test_cmd_enrich_status_renders_counts(), test_cmd_logs_renders_recent_entries(), _is_admin()

### Community 91 - "User Statistics Dashboard Design"
Cohesion: 0.22
Nodes (9): Activity percentage progress visualization, Comprehensive statistics design (streaks, storage, sessions), Dashboard design principles (clean, scannable, responsive, accessible), User statistics and profile dashboard feature, user-stats-dashboard agent definition, /my_history command, /my_stat command, /stat admin dashboard (+1 more)

### Community 92 - "Auto-Delete Report Findings"
Cohesion: 0.27
Nodes (7): Auto-Delete Functionality Test Report, In-Memory file_deletions Data Loss on Restart, Unsynchronized Global file_deletions Access, Mixed Naive/Aware Datetime Handling, Terms Acceptance Gate, Naive vs Aware Datetime TypeError, Terms of Use and Privacy Policy

### Community 93 - "Bot Identity Cache for Stats"
Cohesion: 0.24
Nodes (6): cache_bot_info(), collect_bot_info(), format_uptime(), test_collect_bot_info_no_cache_no_client_uses_unknown(), test_collect_bot_info_partial_cache_coalesces_to_unknown(), test_collect_bot_info_uses_cached_identity()

### Community 94 - "Recent Results HTML Formatting"
Cohesion: 0.20
Nodes (4): format_recent_output(), test_format_recent_output_escapes_titles(), test_format_recent_output_missing_year_falls_back_to_title(), test_format_recent_output_renders_sections()

### Community 95 - "HTTP Client Error Handling Tests"
Cohesion: 0.20
Nodes (3): FakeGet, FakeResp, test_request_surfaces_api_error_body()

### Community 96 - "Premium Gating and Fuzzy Dedup Docs"
Cohesion: 0.28
Nodes (7): Telegram Stars Premium Flow, Fuzzy Duplicate Detection (85% threshold), Default Premium Features (recent, request, get_all), premium_features Collection, Premium System Documentation, 85% Fuzzy Similarity Threshold Configuration, /request Interactive Request Flow

### Community 97 - "File Deletion Persistence"
Cohesion: 0.25
Nodes (3): load_file_deletions_from_disk(), periodic_save_file_deletions(), save_file_deletions_to_disk()

### Community 99 - "Scan Flood Retry Tests"
Cohesion: 0.22
Nodes (3): FakeMoviesCol, ScanClient, test_scan_uses_flood_retries()

### Community 100 - "Server-Side Filter Tests"
Cohesion: 0.28
Nodes (6): FakeMoviesCol, main(), run(), test_perform_search_applies_facets_server_side(), test_perform_search_escapes_regex_chars(), test_perform_search_fuzzy_uses_parsed_title()

### Community 101 - "Auto-Delete Background Task Tests"
Cohesion: 0.32
Nodes (5): check_files_for_deletion(), test_background_task_system(), _run(), test_error_handling(), _run()

### Community 102 - "Mongo Search Filter Builder"
Cohesion: 0.29
Nodes (5): _build_base_filter(), is_exact_title(), perform_search(), _text_candidates(), _with_title()

### Community 103 - "Watch Title Ambiguity Picker"
Cohesion: 0.25
Nodes (7): is_ambiguous_title(), _cand(), test_ambiguity_rules(), test_watch_ambiguous_shows_picker_instead_of_adding(), _t(), test_watch_unique_match_stores_with_details(), _t()

### Community 104 - "Telegram Logger LPO Value Tests"
Cohesion: 0.25
Nodes (3): _assert_lpo_value(), FakeLogClient, test_telegram_logger_uses_link_preview_options()

### Community 110 - "Antigravity Workflow Rules"
Cohesion: 0.67
Nodes (5): Antigravity Workflow Rules, Workflow authoring best practices, Workflow as step-by-step recipe, Workflow file conventions (.agent/workflows/, .md, YAML frontmatter), Workflow triggering (smart detection and slash commands)

### Community 112 - "Enrichment Cache"
Cohesion: 0.40
Nodes (4): _enrich_key(), get_cached_enrichment(), set_cached_enrichment(), test_enrichment_cache_roundtrip_and_miss()

### Community 113 - "Channel Auto-Indexing Docs"
Cohesion: 0.40
Nodes (5): Auto-indexing of new uploads, Channel management, channels_col collection, /index_channel command, /mc unified channel manager

### Community 114 - "Statistics Command Docs"
Cohesion: 0.40
Nodes (6): Statistics Commands Admin Guide, Enhanced /stat Plan (Export and QuickStat), Stats Export (JSON/CSV with stat_export callbacks), /quickstat Quick Summary Command, Stats Cache (5-Minute TTL), Stats Export Callback Handlers

### Community 119 - "Watchlist Capacity Gate Tests"
Cohesion: 0.33
Nodes (5): _restore_premium(), test_capacity_free_vs_premium(), _t(), test_capacity_gate_blocks_add_past_free_limit(), _t()

### Community 120 - "User Dashboard Keyboard Builder"
Cohesion: 0.40
Nodes (3): _back_keyboard(), build_user_keyboard(), test_keyboard_marks_the_active_filter_and_gates_promote()

### Community 124 - "Active Filter Header Formatting"
Cohesion: 0.50
Nodes (3): format_active_filters(), test_format_active_filters(), test_format_library_filters()

## Ambiguous Edges - Review These
- `Flask Webapp with Health Endpoint` → `Docker Compose App plus MongoDB Stack`  [AMBIGUOUS]
  WEBHOOK_INTEGRATION.md · relation: conceptually_related_to
- `aiohttp (async HTTP client)` → `Health-check webapp`  [AMBIGUOUS]
  requirements.txt · relation: conceptually_related_to
- `ruff==0.16.9 (lint gate)` → `Grouped pip minor/patch updates, majors separate`  [AMBIGUOUS]
  .github/dependabot.yml · relation: conceptually_related_to
- `Full pytest suite job` → `Terms acceptance manual QA protocol`  [AMBIGUOUS]
  .github/workflows/static-checks.yml · relation: conceptually_related_to
- `Removed/renamed command discipline` → `Fourteen test scenarios`  [AMBIGUOUS]
  tests/TESTING_GUIDE.md · relation: references

## Knowledge Gaps
- **33 isolated node(s):** `context-engine`, `from_user`, `Stats Cache (5-Minute TTL)`, `Stats Timeout Protection (30s /stat, 10s quickstat)`, `format_uptime Humanizer` (+28 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1113 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **43 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Flask Webapp with Health Endpoint` and `Docker Compose App plus MongoDB Stack`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `aiohttp (async HTTP client)` and `Health-check webapp`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `ruff==0.16.9 (lint gate)` and `Grouped pip minor/patch updates, majors separate`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `Full pytest suite job` and `Terms acceptance manual QA protocol`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `Removed/renamed command discipline` and `Fourteen test scenarios`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **Why does `callback_handler()` connect `Bulk File Delivery and Stars Invoice` to `Command Handlers Router`, `Request Feature Commands`, `Callbacks and User Access Control`, `Bot Startup and Configuration`, `User Dashboard Commands`, `Features Package Core and Stats Store`, `Premium Plans and Download Quota`, `Statistics Formatting and CSV Export`, `Title Pick Filter View`, `Search Results Pagination UI`, `User Dashboard Page Rendering`, `Download Retention Policy Tests`, `Genre Browse Command Tests`, `User Action Preview Flow`, `Quality Ranking and Feature Tests`, `Genre Browse Callback Tests`, `Auto-Delete Cleanup Tests`, `Search Filtering and Season Grouping`, `Genre Details and Pick Line Formatting`, `Title Info Block and Bulk Cleanup`, `Premium Purchase and Quota UI`, `Auto-Delete Test Report Script`, `Callback Link Preview Tests`, `Mongo Search Filter Builder`?**
  _High betweenness centrality (0.022) - this node is a cross-community bridge._
- **Why does `FakeCursor` connect `Async Cursor Double` to `Search Library Facet Tests`?**
  _High betweenness centrality (0.020) - this node is a cross-community bridge._