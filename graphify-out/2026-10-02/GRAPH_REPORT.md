# Graph Report - cognitoMM  (2026-10-02)

## Corpus Check
- 122 files · ~159,669 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 12 file(s) not represented in the graph (top: (none) 6, .example 2, .nix 1)

## Summary
- 2631 nodes · 5474 edges · 149 communities (108 shown, 41 thin omitted)
- Extraction: 93% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 351 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e738c462`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- commands.py
- tmdb_integration.py
- test_tmdb_identity_requests.py
- watchlist.py
- TelegramLogger
- bot.py
- test_scan_message_range.py
- user_commands.py
- test_update_db_guards.py
- __init__.py
- test_premium_monetization.py
- test_critical_fixes.py
- asyncio
- test_reliability.py
- test_consolidation.py
- check_reexports.py
- test_queue_command.py
- test_user_dashboard.py
- request_management.py
- test_reexport_check.py
- test_stats_dashboard.py
- os
- callback_handler
- run_all
- handle_command router in features/commands.py
- MovieFilenameParser
- _match
- webapp.py
- incremental_rescan
- test_pick_filter.py
- test_uptimerobot_monitors.py
- test_keepalive.py
- build_search_page
- render_user_page
- test_version_bump.py
- FakeCallbackQuery
- premium_commands.py
- test_download_retention.py
- broadcast.py
- test_database_import_guard.py
- FakeMessage
- test_metrics_endpoint.py
- test_premium_list.py
- features/statistics.py Statistics Module
- start_user_action
- FakeClient
- FakeMovies
- .parse
- test_new_features.py
- _FakeGenreCbq
- features/ Module Map
- track_file_for_deletion
- test_prune_stats.py
- request_commands.py
- Hybrid Telegram Movie Bot (user session + bot session)
- FakeQueryWithMessage
- FakeUsersCol
- ruff lint gate
- enrich_title
- premium_management.py
- test_pyroblack_api_cleanup.py
- Python Code Guide
- types
- Telegram movie bot system overview
- test_orphan_prune.py
- run_index_channel
- send_search_results
- test_index_language_override.py
- FakeGenreMovies
- test_inline_handler_uses_thumbnail_url
- CognitoMM Deployment Guide
- build_plans_keyboard
- search.py
- test_watchlist.py
- keep_alive_loop
- Movie/Series Request Feature Documentation
- _install
- test_auto_delete.py
- FakeCallbackQuery
- add_to_watchlist
- run
- Broadcast System Architecture Design
- smoke_test_bot.py
- resolve_targets
- TMDB_API integration
- FakeRequestCollection
- FakeMessage
- FakeQuery
- Terms acceptance manual QA protocol
- TestCase
- test_cmd_logs_renders_recent_entries
- users_col collection
- Auto-Delete Functionality Test Report
- statistics.py
- format_recent_output
- FakeSession
- Telegram Stars Premium Flow
- FakePremiumUsersCol
- conftest.py
- FakeUsersCol
- FakeRequestsCol
- FakeUsersCollection
- test_tmdb_integration.py
- FakeResp
- test_telegram_logger_uses_link_preview_options
- FakeCursor
- TestResults
- FakeCursor
- test_cmd_recent_uses_link_preview_options
- FakeCursor
- Antigravity Workflow Rules
- CognitoBot
- start_keep_alive
- Auto-indexing of new uploads
- Enhanced /stat Plan (Export and QuickStat)
- _clean_list_query
- export_stats_csv
- Q: how does the premium feature works?
- FakeSentMsg
- _t
- build_user_keyboard
- test_incremental_rescan_window_and_cursor
- FakeCallbackMsg
- test_cmd_genres_series_deduped_with_real_counts
- _rank_watch_candidates
- test_cmd_watchlist_renders_bracket_lines
- test_incremental_rescan_empty_history_returns_none
- GRAPH_REPORT.md (Broad Architecture Review Only)
- run.sh
- test_old_filename_parser_module_gone
- test_role_helpers_not_defined_in_database
- .mcp.json
- test_engine_raw_scan_owns_underscore_metadata
- test_engine_m4a_is_audio_codec
- test_parse_metadata_has_no_year_fallbacks
- test_engine_owns_multi_year_2012
- test_engine_owns_multi_year_2001
- test_group_recent_content_consolidates_qualities
- test_role_helpers_single_canonical_home
- test_grouping_helpers_single_canonical_home
- test_grouping_helpers_not_defined_in_search
- test_multi_year_edge_case_still_works
- test_format_file_size_is_canonical
- Pillow (image handling)

## God Nodes (most connected - your core abstractions)
1. `callback_handler()` - 68 edges
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
- `Fourteen test scenarios` --references--> `Removed/renamed command discipline`  [AMBIGUOUS]
  tests/TESTING_GUIDE.md → info/commands.md
- `Full pytest suite job` --conceptually_related_to--> `Terms acceptance manual QA protocol`  [AMBIGUOUS]
  .github/workflows/static-checks.yml → tests/TESTING_GUIDE.md
- `User statistics and profile dashboard feature` --semantically_similar_to--> `/stat admin dashboard`  [INFERRED] [semantically similar]
  .claude/agents/user-stats-dashboard.md → info/commands.md
- `_run()` --calls--> `callback_handler()`  [EXTRACTED]
  tests/test_auto_delete.py → features/callbacks.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Bot indexing ingest pipeline** — info_architecture_channel_monitoring, info_architecture_metadata_extraction, info_architecture_telegram_file_details, info_architecture_auto_indexing, info_architecture_mongodb_atlas_integration [EXTRACTED 1.00]
- **CognitoMM MongoDB collection set** — info_commands_movies_col, info_commands_users_col, info_commands_logs_col, info_commands_settings_col, info_commands_channels_col, info_commands_requests_col, info_commands_premium_users_col [EXTRACTED 1.00]
- **Static Checks CI quality gates** — _github_workflows_static_checks_reexport_check, _github_workflows_static_checks_lint, _github_workflows_static_checks_tests, _github_workflows_static_checks_python_312 [EXTRACTED 1.00]
- **Stat Output Formatting Evolution (Markdown -> HTML -> Box-Drawing)** — formatting_updates_complete_formatting_rollup, formatting_updates_complete_html_parse_mode, my_stat_formatting_update_my_stat_formatting, stat_command_formatting_update_stat_html_formatting, refined_formatting_update_box_drawing_design, stat_feature_update_bot_information_section [EXTRACTED 1.00]
- **Request Feature End-to-End Lifecycle** — request_feature_request_flow, request_feature_admin_actions, request_feature_requests_collection, implementation_summary_request_rate_limiting, implementation_summary_duplicate_detection, implementation_summary_request_pagination, quick_start_requests_rate_limit_constants, tmdb_integration_summary_search_tmdb [INFERRED 0.85]
- **Statistics Dashboard Collect-Format-Export Pipeline** — stat_feature_plan_collect_comprehensive_stats, stat_feature_implementation_statistics_module, stat_feature_implementation_parallel_data_collection, stat_feature_implementation_timeout_protection, stat_feature_enhanced_plan_stats_caching, stat_feature_enhanced_plan_export_functionality [INFERRED 0.85]

## Communities (149 total, 41 thin omitted)

### Community 0 - "commands.py"
Cohesion: 0.06
Nodes (46): cmd_add_channel(), cmd_ban_user(), cmd_buy_premium(), cmd_demote(), cmd_enrich(), cmd_enrich_status(), cmd_genres(), cmd_help() (+38 more)

### Community 1 - "tmdb_integration.py"
Cohesion: 0.07
Nodes (21): derive_movie_status(), derive_series_status(), extract_year(), fetch_title_status(), format_enrichment_line(), format_tmdb_result(), get_cached_trending(), get_imdb_id() (+13 more)

### Community 2 - "test_tmdb_identity_requests.py"
Cohesion: 0.15
Nodes (13): fulfill_matching_requests(), _request_matches(), FakeClient, _install(), main(), _restore(), run(), test_fulfill_by_tmdb_notifies_requester_and_voters() (+5 more)

### Community 3 - "watchlist.py"
Cohesion: 0.08
Nodes (21): get_watchlist(), remove_from_watchlist(), update_watchlist_status(), watchlist_capacity(), cmd_unwatch(), cmd_watch(), cmd_watchlist(), handle_watch_update() (+13 more)

### Community 4 - "TelegramLogger"
Cohesion: 0.06
Nodes (15): _StreamWrapper, TelegramLogger, FakeClient, main(), run_async(), test_flush_other_errors_do_not_re_resolve(), test_flush_self_heals_on_peer_id_invalid(), test_set_client_accepts_int_channel() (+7 more)

### Community 5 - "bot.py"
Cohesion: 0.05
Nodes (21): main(), run_bot(), TempData, ensure_indexes(), __getattr__(), scan_message_range(), start_db_rescan_monitor(), load_file_deletions_from_disk() (+13 more)

### Community 6 - "test_scan_message_range.py"
Cohesion: 0.08
Nodes (19): existing_docs(), FakeClient, FakeCursor, FakeMedia, FakeMoviesCol, FakeMsg, main(), run_scan() (+11 more)

### Community 7 - "user_commands.py"
Cohesion: 0.05
Nodes (27): _active_premium_ids(), _ago(), build_preview_text(), build_prompt(), can_use_dashboard(), cancel_user_action(), confirm_user_action(), _deliver() (+19 more)

### Community 8 - "test_update_db_guards.py"
Cohesion: 0.06
Nodes (17): existing_docs(), FakeChannelsCol, FakeClient, FakeCursor, FakeMessage, FakeMoviesCol, FakeMsg, FakeSent (+9 more)

### Community 9 - "__init__.py"
Cohesion: 0.05
Nodes (27): _deliver_bulk_files(), cleanup_expired_premium(), get_all_premium_features(), record_download(), toggle_feature(), check_terms_acceptance(), get_user_doc(), has_accepted_terms() (+19 more)

### Community 10 - "test_premium_monetization.py"
Cohesion: 0.08
Nodes (20): _parse_premium_plans(), check_download_quota(), FakeClient, FakeCursor, FakePaymentMessage, FakePaymentsCol, FakePremiumUsersCol, FakeUsersCol (+12 more)

### Community 11 - "test_critical_fixes.py"
Cohesion: 0.08
Nodes (19): FakeChannelsCol, main(), make_message(), run_should_process(), _is_admin(), test_access_control_not_duplicated_in_utils(), test_add_channel_end_to_end(), test_admin_allowed_in_random_group() (+11 more)

### Community 12 - "asyncio"
Cohesion: 0.13
Nodes (10): _extract_channel_id(), _extract_message_ids(), handle_raw_update(), FakeChannelsCollection, FakeMoviesCollection, stub_log_action(), test_handle_raw_update_deletes_indexed_entries(), test_handle_raw_update_handles_exceptions_gracefully() (+2 more)

### Community 13 - "test_reliability.py"
Cohesion: 0.08
Nodes (23): add_jitter(), compute_delay(), flood_wait_seconds(), FloodWait, is_flood_wait(), jittered_sleep(), retry_on_flood(), struct_log() (+15 more)

### Community 14 - "test_consolidation.py"
Cohesion: 0.06
Nodes (16): test_construct_final_caption_uses_canonical_formatter(), test_engine_bracket_dts_hd_ma_full_form(), test_engine_hdr_no_dv_false_positive(), test_engine_owns_all_parsing(), test_engine_owns_multi_year_1917(), test_engine_owns_same_year_title_year(), test_engine_publisher_coexists_with_rip(), test_engine_publisher_via_bracket_and_underscore() (+8 more)

### Community 15 - "check_reexports.py"
Cohesion: 0.09
Nodes (17): _collect_symbols(), _collect_targets(), _lazy_reexport_names(), main(), _module_level_defs(), _module_package(), _module_path(), _resolve_source() (+9 more)

### Community 16 - "test_queue_command.py"
Cohesion: 0.11
Nodes (15): cmd_queue(), FakeChannelsCol, FakeCursor, FakeMessage, FakeSettingsCol, _install(), _restore(), run() (+7 more)

### Community 17 - "test_user_dashboard.py"
Cohesion: 0.10
Nodes (20): apply_role_action(), _boom(), days_ago(), Env, in_days(), role_of(), test_alias_demote_requires_a_super_admin(), test_alias_skips_guarded_targets_in_the_summary() (+12 more)

### Community 18 - "request_management.py"
Cohesion: 0.14
Nodes (12): check_duplicate_request(), check_rate_limits(), update_user_limits(), validate_imdb_link(), _install_fakes(), main(), test_duplicate_detection(), _test_duplicate_detection() (+4 more)

### Community 19 - "test_reexport_check.py"
Cohesion: 0.09
Nodes (14): test_current_repo_is_clean(), test_duplicate_check_flags_same_helper_in_two_modules(), test_duplicate_check_ignores_class_methods(), test_duplicate_check_ignores_module_dunders(), test_duplicate_check_ignores_unique_names(), test_duplicate_check_skips_allowlisted(), test_scanner_allows_absolute_and_submodule_imports(), test_scanner_allows_aliased_imports() (+6 more)

### Community 20 - "test_stats_dashboard.py"
Cohesion: 0.19
Nodes (12): format_number(), format_quick_stats_output(), format_stats_output(), test_statistics_uses_canonical_formatter(), _errors_lines(), main(), test_block_appears_on_first_run_error(), test_block_with_data() (+4 more)

### Community 21 - "os"
Cohesion: 0.07
Nodes (14): save_file_to_db(), parse_metadata(), compare_field(), main(), print_test_result(), test_case_1_star_wars_visions(), test_case_2_the_witcher(), test_case_3_hazbin_hotel() (+6 more)

### Community 22 - "callback_handler"
Cohesion: 0.11
Nodes (8): callback_handler(), start_indexing_process(), build_premium_menu(), get_retention_minutes(), send_premium_invoice(), render_pick_view(), export_stats_json(), format_trending_list()

### Community 23 - "run_all"
Cohesion: 0.12
Nodes (14): _assert_link_preview_only(), FakeUserMsg, run_all(), _sent_msgs(), test_cmd_indexing_stats_uses_link_preview_options(), test_cmd_my_history_plain_html_tap_to_copy(), test_cmd_my_history_uses_link_preview_options(), test_cmd_quickstat_uses_link_preview_options() (+6 more)

### Community 24 - "handle_command router in features/commands.py"
Cohesion: 0.10
Nodes (26): /broadcast command, /buy_premium command, CognitoMM command reference, /enrich TMDb backfill, /genres command, handle_command router in features/commands.py, Inline query mode, /logs audit view (+18 more)

### Community 25 - "MovieFilenameParser"
Cohesion: 0.08
Nodes (12): demo(), MovieFilenameParser, test_engine_and_api_agree(), test_engine_extracts_bit_depth_separately(), test_engine_full_text_scan_sees_brackets_and_underscores(), test_engine_handles_ch_suffixed_channels(), test_engine_imdb_id_field(), test_engine_publisher_field_and_alone() (+4 more)

### Community 26 - "_match"
Cohesion: 0.10
Nodes (8): _as_utc(), FakeCursor, FakeLogsCol, FakePremiumCol, FakeUsersCol, _geq(), _match(), _sort_key()

### Community 27 - "webapp.py"
Cohesion: 0.10
Nodes (9): add_cors_headers(), _get_port(), health_check(), index(), metrics(), _MongoJSONProvider, robots_txt(), run_flask() (+1 more)

### Community 28 - "incremental_rescan"
Cohesion: 0.25
Nodes (4): get_channel_scan_cursor(), incremental_rescan(), set_channel_scan_cursor(), test_scan_cursor_roundtrip()

### Community 29 - "test_pick_filter.py"
Cohesion: 0.10
Nodes (27): build_pick_view(), filter_copies(), group_seasons(), is_series(), normalize_resolution(), pick_callback(), _season_number(), episode() (+19 more)

### Community 30 - "test_uptimerobot_monitors.py"
Cohesion: 0.13
Nodes (13): build_monitors(), create_monitors(), existing_monitor_urls(), _headers(), main(), _request(), test_build_monitors_urls_and_keywords(), test_create_monitors_api_error_raises() (+5 more)

### Community 31 - "test_keepalive.py"
Cohesion: 0.14
Nodes (14): derive_keep_alive_url(), key(), main(), undo(), test_explicit_url_used_as_is(), test_explicit_url_wins_over_hf_vars(), test_keep_alive_interval_default_and_override(), test_keep_alive_loop_noop_without_url() (+6 more)

### Community 32 - "build_search_page"
Cohesion: 0.12
Nodes (17): build_search_keyboard(), build_search_page(), group_by_title(), render_search_page(), latest_copy(), test_build_search_keyboard_clamps_stale_season_page(), run(), test_build_search_keyboard_few_seasons_no_paging() (+9 more)

### Community 33 - "render_user_page"
Cohesion: 0.11
Nodes (15): cmd_user(), render_user_page(), FakeMessage, list_block(), listed_ids(), test_active_filter_uses_a_seven_day_window(), test_alias_is_private_only_and_admin_only(), test_dashboard_is_private_and_admin_only() (+7 more)

### Community 34 - "test_version_bump.py"
Cohesion: 0.06
Nodes (27): bump(), main(), read_version(), set_version(), added_files(), check(), _git(), main() (+19 more)

### Community 35 - "FakeCallbackQuery"
Cohesion: 0.12
Nodes (13): FakeCallbackQuery, movie(), _run_callback(), test_back_callback_ownership_guard(), test_back_callback_restores_search_page(), test_build_search_page_exact_fuzzy_header_counts(), test_build_search_page_latest_copy_wins_by_indexed_at(), test_choose_callback_filters_in_place() (+5 more)

### Community 36 - "premium_commands.py"
Cohesion: 0.11
Nodes (13): handle_add_premium_feature(), handle_add_premium_user(), handle_edit_premium_user(), handle_premium_list_search(), handle_premium_user_input(), handle_remove_premium_user(), add_premium_feature(), add_premium_user() (+5 more)

### Community 37 - "test_download_retention.py"
Cohesion: 0.12
Nodes (11): retention_warn_minutes(), FakeCallbackMsg, FakeCallbackQuery, FakeClient, run(), test_get_retention_minutes_by_tier(), test_getpack_delivers_copies(), test_monitor_uses_stored_warn_minutes() (+3 more)

### Community 38 - "broadcast.py"
Cohesion: 0.15
Nodes (8): cmd_broadcast(), execute_broadcast(), format_progress_message(), format_summary_message(), get_broadcast_recipients(), log_broadcast(), send_broadcast_message(), get_readable_time()

### Community 39 - "test_database_import_guard.py"
Cohesion: 0.17
Nodes (9): resolve_mongo_uri(), test_empty_uri_no_longer_crashes_client_construction(), test_ensure_indexes_fails_fast_when_uri_missing(), test_resolve_mongo_uri_blank_falls_back_to_localhost(), test_resolve_mongo_uri_empty_falls_back_to_localhost(), test_resolve_mongo_uri_none_falls_back_to_localhost(), test_resolve_mongo_uri_passes_through_real_uri(), test_resolve_mongo_uri_strips_surrounding_whitespace() (+1 more)

### Community 40 - "FakeMessage"
Cohesion: 0.11
Nodes (8): FakeMessage, test_cmd_genres_browse_empty_genre(), test_cmd_genres_browse_paginates(), test_cmd_random_caption_uses_bracket_style(), test_genre_results_season_paging(), test_new_commands_are_routed(), _no(), recorder()

### Community 41 - "test_metrics_endpoint.py"
Cohesion: 0.13
Nodes (9): set_stats_provider(), running_loop(), test_metrics_provider_dict_returns_200_with_data(), provider(), test_metrics_provider_none_returns_500_error(), test_metrics_provider_raises_returns_500(), test_metrics_provider_with_objectid_serializes(), test_metrics_unregistered_returns_stub() (+1 more)

### Community 42 - "test_premium_list.py"
Cohesion: 0.28
Nodes (16): build_premium_user_list(), ExplodingCol, make_doc(), patch_cols(), restore_cols(), run(), test_callback_data_under_limit(), test_enrichment_failure_does_not_break_list() (+8 more)

### Community 43 - "features/statistics.py Statistics Module"
Cohesion: 0.15
Nodes (16): Datetime Timezone Fix Summary, Complete Formatting Updates Summary, /my_stat HTML Formatting Update, premium_users Collection, Refined Box-Drawing Formatting Update, /stat HTML Formatting Update, asyncio.gather Parallel Data Collection, features/statistics.py Statistics Module (+8 more)

### Community 44 - "start_user_action"
Cohesion: 0.17
Nodes (13): start_user_action(), _store_pending_action(), FakeCallbackQuery, _queue_input(), _fake_wait(), test_cancel_writes_nothing(), test_confirm_writes_roles_and_shows_the_result_banner(), test_pending_action_state_is_reaped_by_the_cleanup_sweep() (+5 more)

### Community 45 - "FakeClient"
Cohesion: 0.15
Nodes (7): FakeClient, FakeUser, test_aliases_route_through_apply_role_action(), test_hostile_names_are_html_escaped(), test_lookup_failure_degrades_to_dashes(), test_mixed_comma_parsing_resolves_names_and_roles(), test_preview_verdicts_cover_every_guard()

### Community 46 - "FakeMovies"
Cohesion: 0.06
Nodes (15): backfill(), _lookup(), count_pending(), run(), _doc(), FakeMovies, test_backfill_concurrency_maps_all_fields(), test_backfill_enriches_and_maps_fields() (+7 more)

### Community 48 - "test_new_features.py"
Cohesion: 0.10
Nodes (12): _enrich_key(), get_cached_enrichment(), set_cached_enrichment(), quality_rank(), main(), test_cmd_my_history_bracket_listing(), test_enrichment_cache_roundtrip_and_miss(), test_format_enrichment_line() (+4 more)

### Community 49 - "_FakeGenreCbq"
Cohesion: 0.17
Nodes (10): _FakeGenreCbq, _flat(), _genre_doc(), test_genre_back_callback_restores_page(), test_genre_page_callback_legacy_3_part_uses_stored_sort(), test_genre_page_callback_paginates(), test_genre_page_callback_rating_sort(), test_genre_page_callback_sort_toggle() (+2 more)

### Community 50 - "features/ Module Map"
Cohesion: 0.17
Nodes (15): callback_handler Inline-Button Flows (64-byte callback data), CI Gates (static-checks.yml delegating to Makefile), CognitoMM Codebase Notes, handle_command Command Router (40 command strings), Channel Auto-Indexing Flow (queue-based), features/ Module Map, Scheduled Incremental Rescan Monitor, Exact plus Fuzzy Search Flow (+7 more)

### Community 51 - "track_file_for_deletion"
Cohesion: 0.15
Nodes (16): check_files_for_deletion(), cleanup_expired_file_deletions(), track_file_for_deletion(), _fresh_lock_patch(), test_background_task_system(), _run(), test_cleanup_functionality(), _run() (+8 more)

### Community 52 - "test_prune_stats.py"
Cohesion: 0.08
Nodes (14): prune_orphaned_index_entries(), FailingCollection, FakeClient, FakeCursor, FakeMessage, FakeMoviesCollection, main(), make_docs() (+6 more)

### Community 53 - "request_commands.py"
Cohesion: 0.12
Nodes (9): is_feature_premium_only(), is_premium_user(), cmd_request(), cmd_request_list(), send_request_list_page(), find_global_match(), get_queue_position(), request_priority_key() (+1 more)

### Community 54 - "Hybrid Telegram Movie Bot (user session + bot session)"
Cohesion: 0.14
Nodes (16): Bot-session command handlers (start, help, search), main() starting both Telegram clients, Environment configuration block (API_ID, tokens, MONGO_URI, ADMINS), search_hybrid exact-plus-fuzzy search, Hybrid Telegram Movie Bot (user session + bot session), metadata command handler, movies_col collection (draft code), search_type command handler (+8 more)

### Community 55 - "FakeQueryWithMessage"
Cohesion: 0.14
Nodes (14): _allow_callbacks(), FakeQueryWithMessage, test_picker_button_adds_through_router(), _t(), test_picker_cancel_via_router(), _t(), test_picker_expired_token_is_refused(), _t() (+6 more)

### Community 56 - "FakeUsersCol"
Cohesion: 0.13
Nodes (6): _element_matches(), FakeCursor, FakeUsersCol, _positional_match(), test_failed_dm_does_not_burn_the_window(), _t()

### Community 57 - "ruff lint gate"
Cohesion: 0.16
Nodes (15): Virtualenv and requirements.txt / pyproject.toml dependency management, Clean code and PEP 8 style principles, Dependabot v2 configuration, GitHub Dependabot configuration schema reference, Sync to Hugging Face Hub workflow, iamjoberror/bot-media Gradio Space target, huggingface/hub-sync@v0.2.1 action, sync-to-hub job (+7 more)

### Community 58 - "enrich_title"
Cohesion: 0.14
Nodes (7): _format_genre_details(), _genre_real_counts(), _genre_title_count(), _genre_title_pipeline(), send_genre_page(), enrich_title(), _resolve_tmdb_id()

### Community 59 - "premium_management.py"
Cohesion: 0.15
Nodes (8): _day_key(), get_all_premium_users(), get_download_quota_status(), _premium_expiry(), _premium_list_status(), _send_expiry_warning(), start_premium_expiry_monitor(), warn_expiring_premium()

### Community 60 - "test_pyroblack_api_cleanup.py"
Cohesion: 0.14
Nodes (7): channel_forward_msg(), main(), plain_text_msg(), SpyArticle, test_index_channel_extracts_channel_from_forward_origin(), test_index_channel_rejects_non_forwarded(), test_link_preview_options_migration_fully_applied()

### Community 61 - "Python Code Guide"
Cohesion: 0.15
Nodes (14): Data processing guidance, Machine learning workflow and experiment tracking, Model deployment with FastAPI/Flask and Docker, Performance optimization (vectorization, multiprocessing, async), Python Code Guide, pytest unit, fixture and integration testing, aiohttp (async HTTP client), Flask (web framework) (+6 more)

### Community 62 - "types"
Cohesion: 0.20
Nodes (3): _masked_host(), test_masked_host_redacts_credentials(), test_script_refuses_without_credentials()

### Community 63 - "Telegram movie bot system overview"
Cohesion: 0.19
Nodes (14): Telegram movie bot system overview, Channel monitoring, Implementation roadmap, Movie metadata extraction, MongoDB Atlas integration, Movie document schema, MTProto API via Kurigram, Search engine (+6 more)

### Community 64 - "test_orphan_prune.py"
Cohesion: 0.24
Nodes (4): FakeClient, FakeMessage, main(), run_test()

### Community 65 - "run_index_channel"
Cohesion: 0.12
Nodes (7): FakeIndexClient, non_channel_chat_forward_msg(), run_index_channel(), test_index_channel_message_link_path_still_works(), test_index_channel_rejects_non_channel_chat_forward(), test_index_channel_rejects_user_forward(), user_forward_msg()

### Community 66 - "send_search_results"
Cohesion: 0.17
Nodes (6): build_title_info_block(), _copy_type_label(), _fetch_metas(), send_search_results(), pick_best_quality(), test_build_title_info_block_renders_meta()

### Community 67 - "test_index_language_override.py"
Cohesion: 0.21
Nodes (7): RecordingCol, run(), test_text_index_uses_language_override(), check(), test_unique_indexes_still_created(), check(), _with_fakes()

### Community 69 - "test_inline_handler_uses_thumbnail_url"
Cohesion: 0.13
Nodes (6): FakeAnswerClient, FakeCursor, FakeInlineMoviesCol, FakeInlineQuery, from_user, test_inline_handler_uses_thumbnail_url()

### Community 70 - "CognitoMM Deployment Guide"
Cohesion: 0.21
Nodes (11): HF Spaces Self-Keep-Alive (start_keep_alive), CognitoMM Deployment Guide, Docker Compose App plus MongoDB Stack, Hugging Face Spaces Deployment and GitHub Sync, Monitoring Endpoints (health, metrics, robots), UptimeRobot Health and Metrics Monitors, cognito_bot App Service, Container Healthchecks (GET /health) (+3 more)

### Community 71 - "build_plans_keyboard"
Cohesion: 0.33
Nodes (3): build_plans_keyboard(), format_plans_text(), test_plans_keyboard_and_text()

### Community 72 - "search.py"
Cohesion: 0.07
Nodes (30): _build_base_filter(), format_active_filters(), is_exact_title(), _normalize_quality_token(), parse_search_query(), perform_search(), _text_candidates(), _with_title() (+22 more)

### Community 73 - "test_watchlist.py"
Cohesion: 0.12
Nodes (14): _array_field_matches(), _cand(), _doc_matches(), _restore_module_state(), test_ambiguity_rules(), test_normalize_content_type(), test_picker_keyboard_and_state(), test_router_covers_both_watch_callback_prefixes() (+6 more)

### Community 74 - "keep_alive_loop"
Cohesion: 0.22
Nodes (5): keep_alive_interval(), keep_alive_loop(), _ping_once(), test_keep_alive_loop_pings_repeatedly(), test_keep_alive_loop_tolerates_failures()

### Community 75 - "Movie/Series Request Feature Documentation"
Cohesion: 0.23
Nodes (13): Eligible Broadcast Recipient Query, MongoDB Collections, Indexes and tmdb_id Identity, Title Request Flow with Rate Limits, requests and user_request_limits Collections, Request Feature Implementation Summary, Request Queue Pagination (9 per page), Request Rate Limits (3 pending / 1 per day / 20 global), Rate-Limit Constants in request_management.py (+5 more)

### Community 76 - "_install"
Cohesion: 0.14
Nodes (8): reset_notify_cooldowns(), reset_refresh_state(), FakeClient, _install(), test_floodgate_is_per_title_not_global(), _t(), test_series_burst_dms_once(), _t()

### Community 77 - "test_auto_delete.py"
Cohesion: 0.19
Nodes (5): generate_test_report(), main_test(), test_integration_points(), _run(), test_syntax_and_imports()

### Community 78 - "FakeCallbackQuery"
Cohesion: 0.15
Nodes (4): FakeCallbackMsg, FakeCallbackQuery, test_search_pagination_callback_uses_link_preview_options(), test_trending_callback_uses_link_preview_options()

### Community 79 - "add_to_watchlist"
Cohesion: 0.17
Nodes (8): add_to_watchlist(), _cooldown_active(), _notify_identity(), notify_watchlist(), _watch_key(), test_notify_watchlist_dms_matching_users(), test_watch_notify_matches_tmdb_across_spellings(), test_watch_notify_title_fallback_without_tmdb()

### Community 80 - "run"
Cohesion: 0.17
Nodes (11): run(), test_add_stores_full_detail_and_stays_idempotent(), _t(), test_add_without_tmdb_stores_no_null_placeholders(), _t(), test_cooldown_expires(), _t(), test_update_skips_entries_without_tmdb_id() (+3 more)

### Community 81 - "Broadcast System Architecture Design"
Cohesion: 0.21
Nodes (9): Broadcast Audit Logging (log_action + broadcasts_col), Broadcast System Implementation Summary, features/broadcast.py Command Module, Broadcast System Architecture Design, broadcasts_col Schema and Indexes, Broadcast Error Handling Strategy, Broadcast Progress Tracking, Admin Broadcast Flow (+1 more)

### Community 82 - "smoke_test_bot.py"
Cohesion: 0.18
Nodes (3): on_message(), start_command(), test_command()

### Community 83 - "resolve_targets"
Cohesion: 0.12
Nodes (9): _resolve_names(), run_user_search(), _load_user_roles(), lookup_users_batched(), parse_target_tokens(), resolve_targets(), role_guard_verdict(), test_lookup_failure_never_blocks_the_admin() (+1 more)

### Community 84 - "TMDB_API integration"
Cohesion: 0.23
Nodes (10): Background tasks started in features/bot.py, Scheduled incremental DB rescan, .env configuration table, Tier-based file retention auto-delete, Keep-alive self-ping, TMDB_API integration, /update_db reconcile command, /watch command (+2 more)

### Community 86 - "FakeMessage"
Cohesion: 0.17
Nodes (9): FakeMessage, test_unwatch_removes(), _t(), test_watch_no_tmdb_match_still_tracks_title(), _t(), test_watch_without_title_shows_usage(), _t(), test_watchlist_command_renders_with_buttons() (+1 more)

### Community 87 - "FakeQuery"
Cohesion: 0.17
Nodes (9): FakeQuery, test_update_all_refreshes_statuses(), _t(), test_update_cooldown_blocks_rapid_taps(), _t(), test_update_one_entry_only(), _t(), test_update_rejects_other_users_message() (+1 more)

### Community 88 - "Terms acceptance manual QA protocol"
Cohesion: 0.23
Nodes (11): Access gate for commands, inline queries and callbacks, @CognitoMMBot (bot id 8336034036), Database verification queries, Terms acceptance manual QA protocol, Missing TERMS_AND_PRIVACY.md error handling, Success criteria checklist, terms_accepted / terms_accepted_at / last_seen user state, Terms of Use and Privacy Policy acceptance system (+3 more)

### Community 89 - "TestCase"
Cohesion: 0.28
Nodes (4): main(), print_test_result(), run_test(), TestCase

### Community 90 - "test_cmd_logs_renders_recent_entries"
Cohesion: 0.18
Nodes (3): test_cmd_enrich_status_renders_counts(), test_cmd_logs_renders_recent_entries(), _is_admin()

### Community 91 - "users_col collection"
Cohesion: 0.22
Nodes (9): Activity percentage progress visualization, Comprehensive statistics design (streaks, storage, sessions), Dashboard design principles (clean, scannable, responsive, accessible), User statistics and profile dashboard feature, user-stats-dashboard agent definition, /my_history command, /my_stat command, /stat admin dashboard (+1 more)

### Community 92 - "Auto-Delete Functionality Test Report"
Cohesion: 0.27
Nodes (7): Auto-Delete Functionality Test Report, In-Memory file_deletions Data Loss on Restart, Unsynchronized Global file_deletions Access, Mixed Naive/Aware Datetime Handling, Terms Acceptance Gate, Naive vs Aware Datetime TypeError, Terms of Use and Privacy Policy

### Community 93 - "statistics.py"
Cohesion: 0.13
Nodes (8): cache_bot_info(), collect_bot_info(), create_progress_bar(), format_percentage(), format_uptime(), test_collect_bot_info_no_cache_no_client_uses_unknown(), test_collect_bot_info_partial_cache_coalesces_to_unknown(), test_collect_bot_info_uses_cached_identity()

### Community 94 - "format_recent_output"
Cohesion: 0.20
Nodes (4): format_recent_output(), test_format_recent_output_escapes_titles(), test_format_recent_output_missing_year_falls_back_to_title(), test_format_recent_output_renders_sections()

### Community 95 - "FakeSession"
Cohesion: 0.15
Nodes (3): FailingSession, FakeGet, FakeSession

### Community 96 - "Telegram Stars Premium Flow"
Cohesion: 0.28
Nodes (7): Telegram Stars Premium Flow, Fuzzy Duplicate Detection (85% threshold), Default Premium Features (recent, request, get_all), premium_features Collection, Premium System Documentation, 85% Fuzzy Similarity Threshold Configuration, /request Interactive Request Flow

### Community 97 - "FakePremiumUsersCol"
Cohesion: 0.18
Nodes (4): FakeCursor, FakePremiumUsersCol, FakeUsersCol, _matches()

### Community 98 - "conftest.py"
Cohesion: 0.20
Nodes (3): _install_pyrogram_deprecation_guard(), _no_uvloop_policy(), _PyrogramDeprecationGuard

### Community 99 - "FakeUsersCol"
Cohesion: 0.24
Nodes (3): FakeCursor, FakeUsersCol, _watch_doc_matches()

### Community 102 - "test_tmdb_integration.py"
Cohesion: 0.33
Nodes (3): main(), test_format_trending_list_search_style(), test_tmdb_search()

### Community 103 - "FakeResp"
Cohesion: 0.33
Nodes (3): FakeResp, test_request_surfaces_api_error_body(), fake_request()

### Community 104 - "test_telegram_logger_uses_link_preview_options"
Cohesion: 0.25
Nodes (3): _assert_lpo_value(), FakeLogClient, test_telegram_logger_uses_link_preview_options()

### Community 110 - "Antigravity Workflow Rules"
Cohesion: 0.67
Nodes (5): Antigravity Workflow Rules, Workflow authoring best practices, Workflow as step-by-step recipe, Workflow file conventions (.agent/workflows/, .md, YAML frontmatter), Workflow triggering (smart detection and slash commands)

### Community 113 - "Auto-indexing of new uploads"
Cohesion: 0.40
Nodes (5): Auto-indexing of new uploads, Channel management, channels_col collection, /index_channel command, /mc unified channel manager

### Community 114 - "Enhanced /stat Plan (Export and QuickStat)"
Cohesion: 0.40
Nodes (6): Statistics Commands Admin Guide, Enhanced /stat Plan (Export and QuickStat), Stats Export (JSON/CSV with stat_export callbacks), /quickstat Quick Summary Command, Stats Cache (5-Minute TTL), Stats Export Callback Handlers

### Community 115 - "_clean_list_query"
Cohesion: 0.40
Nodes (3): _clean_list_query(), _list_query_token(), test_premium_list_page_and_query_helpers()

### Community 116 - "export_stats_csv"
Cohesion: 0.50
Nodes (4): export_stats_csv(), test_csv_export_includes_bot_version(), test_csv_export_with_and_without_prune_data(), collect()

### Community 117 - "Q: how does the premium feature works?"
Cohesion: 0.40
Nodes (4): Answer, Outcome, Q: how does the premium feature works?, Source Nodes

### Community 119 - "_t"
Cohesion: 0.33
Nodes (5): _restore_premium(), test_capacity_free_vs_premium(), _t(), test_capacity_gate_blocks_add_past_free_limit(), _t()

### Community 120 - "build_user_keyboard"
Cohesion: 0.40
Nodes (3): _back_keyboard(), build_user_keyboard(), test_keyboard_marks_the_active_filter_and_gates_promote()

## Ambiguous Edges - Review These
- `Removed/renamed command discipline` → `Fourteen test scenarios`  [AMBIGUOUS]
  tests/TESTING_GUIDE.md · relation: references
- `Full pytest suite job` → `Terms acceptance manual QA protocol`  [AMBIGUOUS]
  .github/workflows/static-checks.yml · relation: conceptually_related_to
- `aiohttp (async HTTP client)` → `Health-check webapp`  [AMBIGUOUS]
  requirements.txt · relation: conceptually_related_to
- `ruff==0.16.9 (lint gate)` → `Grouped pip minor/patch updates, majors separate`  [AMBIGUOUS]
  .github/dependabot.yml · relation: conceptually_related_to
- `Docker Compose App plus MongoDB Stack` → `Flask Webapp with Health Endpoint`  [AMBIGUOUS]
  WEBHOOK_INTEGRATION.md · relation: conceptually_related_to

## Knowledge Gaps
- **36 isolated node(s):** `context-engine`, `from_user`, `Answer`, `Outcome`, `Source Nodes` (+31 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1138 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **41 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Removed/renamed command discipline` and `Fourteen test scenarios`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **What is the exact relationship between `Full pytest suite job` and `Terms acceptance manual QA protocol`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `aiohttp (async HTTP client)` and `Health-check webapp`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `ruff==0.16.9 (lint gate)` and `Grouped pip minor/patch updates, majors separate`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `Docker Compose App plus MongoDB Stack` and `Flask Webapp with Health Endpoint`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `TelegramLogger` connect `TelegramLogger` to `test_telegram_logger_uses_link_preview_options`, `smoke_test_bot.py`, `test_pyroblack_api_cleanup.py`, `bot.py`?**
  _High betweenness centrality (0.019) - this node is a cross-community bridge._
- **What connects `context-engine`, `from_user`, `Answer` to the rest of the system?**
  _36 weakly-connected nodes found - possible documentation gaps or missing edges._