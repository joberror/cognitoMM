---
type: "query"
date: "2026-10-01T14:04:21.930911+00:00"
question: "how does the premium feature works?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["is_premium_user() is_feature_premium_only() check_download_quota() activate_payment() PREMIUM_SYSTEM.md"]
---

# Q: how does the premium feature works?

## Answer

Expanded from original query via vocab: [premium, feature, features, gated, gate, paid, subscription, plan, tier, monetization, payment, upgrade]. Traversed BFS from is_premium_user (degree 20), is_feature_premium_only (degree 9) and the PREMIUM_SYSTEM.md doc nodes across communities: Premium Purchase and Quota UI, Premium Admin Command Handlers, Premium Plans and Download Quota, Bot Startup and Configuration, Request Feature Commands. Premium in cognitoMM has three layers: (1) IDENTITY - is_premium_user() in features/premium_management.py:L58 treats admin == premium: config ADMINS short-circuits with zero DB reads, else a premium_users_col record is checked against expiry_date (UTC, tz-naive dates repaired), and only a user with no active record pays the extra is_admin() lookup. (2) FEATURE FLAGS - is_feature_premium_only(name) L321 reads premium_features_col.enabled; toggle_feature() L343 flips it and logs premium_feature_toggled; add_premium_feature() L381 creates new flags enabled. Defaults recent/request/get_all are premium-only. Gates live in cmd_recent (features/commands.py:L547), cmd_request (features/request_commands.py:L44) and build_search_keyboard (features/search.py:L820, hides the Get All button rather than erroring). (3) TIER QUOTA - check_download_quota() L483 gives 10 free downloads/day (FREE_DOWNLOAD_DAILY_LIMIT) and premium lifts it to unlimited (PREMIUM_DOWNLOAD_DAILY_LIMIT=0); it only queries premium after the free cap, fails open, and record_download() L535 bumps counters stored on the user doc. Retention also tiers: 5->30 min single file, 15->60 min bulk via get_retention_minutes() L586; watchlist capacity 5->20 via watchlist_capacity() in features/user_management.py:L511. Purchase path is Telegram Stars (XTR), no external provider: /buy_premium (commands.py:L2613) -> build_plans_keyboard buyplan:<key> -> send_premium_invoice -> pre_checkout_query handle_pre_checkout -> successful_payment handle_successful_payment -> activate_payment(), idempotent per telegram charge_id against premium_payments_col, which then calls add_premium_user(added_by=0). Payload is premium:<plan>:<uid> so a payment can only apply to the payer. warn_expiring_premium() L635 DMs 3d/1d before expiry from a background task started in bot.py:191. Admin-only /premium command UI (features/premium_commands.py) does add/edit/remove users and feature management.

## Outcome

- Signal: useful

## Source Nodes

- is_premium_user() is_feature_premium_only() check_download_quota() activate_payment() PREMIUM_SYSTEM.md