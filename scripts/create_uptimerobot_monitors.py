#!/usr/bin/env python3
"""
Create UptimeRobot monitors for the CognitoMM bot's web endpoints.

Wires /health and /metrics to an UptimeRobot dashboard:

    UPTIMEROBOT_API_KEY=... python scripts/create_uptimerobot_monitors.py \
        [--base-url https://iamjoberror-bot-media.hf.space] [--interval 300]

Creates two HTTP monitors (5-minute interval by default - free tier):
  - "CognitoMM /health"   -> <base>/health   (keyword must exist: "healthy")
  - "CognitoMM /metrics"  -> <base>/metrics  (keyword must exist: "status":"ok")

Why the keyword checks:
  - /health: catches a 200-with-garbage response (e.g. app up but the webapp
    route broken) instead of only raw HTTP status.
  - /metrics: the endpoint returns HTTP 500 on any stats-collection failure
    (see features/webapp.py), and the keyword "status":"ok" additionally
    guards against a future regression back to 200 + {"status":"ok","data":null}.
    The keyword is written WITHOUT spaces to match Flask's compact jsonify
    output: {"status":"ok",...}.

Idempotent: monitors whose URL already exists are skipped, so re-running is
safe. Uses the UptimeRobot REST API v2.0 (https://uptimerobot.com/api/).

Requires `requests` (already in requirements.txt).
"""

import argparse
import os
import sys

import requests

API_ENDPOINT = "https://api.uptimerobot.com/v2"


def api_call(api_key: str, method: str, params: dict) -> dict:
    """POST to an UptimeRobot v2 API method and return the JSON body.

    Raises RuntimeError with the API's own error message on failure (the
    JSON body is far more useful than a bare HTTP status code).
    """
    data = {"api_key": api_key, "format": "json", **params}
    resp = requests.post(f"{API_ENDPOINT}/{method}", data=data, timeout=30)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error", resp.text)
        except ValueError:
            detail = resp.text
        raise RuntimeError(f"{method} failed (HTTP {resp.status_code}): {detail}")
    return resp.json()


def existing_monitor_urls(api_key: str) -> set:
    """Return the set of currently monitored URLs."""
    data = api_call(api_key, "getMonitors", {})
    if data.get("stat") != "ok":
        raise RuntimeError(f"getMonitors failed: {data.get('error', data)}")
    return {m.get("url") for m in data.get("monitors", []) if m.get("url")}


def build_monitors(base_url: str) -> list:
    """The two monitors to create, keyed by their public URL."""
    base = base_url.rstrip("/")
    return [
        {
            "friendly_name": "CognitoMM /health",
            "url": f"{base}/health",
            "keyword_value": "healthy",
        },
        {
            "friendly_name": "CognitoMM /metrics",
            "url": f"{base}/metrics",
            "keyword_value": '"status":"ok"',
        },
    ]


def create_monitors(api_key: str, base_url: str, interval: int = 300) -> int:
    """Create the /health + /metrics monitors; returns the number created."""
    created = 0
    existing = existing_monitor_urls(api_key)
    for m in build_monitors(base_url):
        if m["url"] in existing:
            print(f"⏭️  Already monitored, skipping: {m['url']}")
            continue
        result = api_call(api_key, "newMonitor", {
            "type": 1,  # HTTP(s)
            "interval": interval,
            "friendly_name": m["friendly_name"],
            "url": m["url"],
            "keyword_type": 1,  # keyword should exist
            "keyword_value": m["keyword_value"],
            "keyword_case_type": 1,  # case-insensitive
        })
        if result.get("stat") != "ok":
            raise RuntimeError(
                f"newMonitor failed for {m['url']}: {result.get('error', result)}"
            )
        monitor_id = result.get("monitor", {}).get("id")
        print(f"✅ Created '{m['friendly_name']}' (id {monitor_id}) -> {m['url']}")
        created += 1
    return created


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base-url",
        default="https://iamjoberror-bot-media.hf.space",
        help="Public base URL of the bot webapp (default: HF Space)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Check interval in seconds (free tier: >= 300, multiple of 60)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("UPTIMEROBOT_API_KEY")
    if not api_key:
        parser.error("UPTIMEROBOT_API_KEY environment variable is required")

    created = create_monitors(api_key, args.base_url, args.interval)
    print(
        f"\nDone. Created {created} monitor(s). "
        "View them at https://uptimerobot.com/dashboard"
    )


if __name__ == "__main__":
    main()
