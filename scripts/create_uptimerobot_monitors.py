#!/usr/bin/env python3
"""
Create UptimeRobot monitors for the CognitoMM bot's web endpoints (v3 API).

Wires /health and /metrics to an UptimeRobot dashboard:

    UPTIMEROBOT_API_KEY=... python scripts/create_uptimerobot_monitors.py \
        [--base-url https://iamjoberror-bot-media.hf.space] [--interval 300]

Creates two HTTP monitors (5-minute interval by default - free tier):
  - "CognitoMM /health"   -> <base>/health   (keyword exists: "healthy")
  - "CognitoMM /metrics"  -> <base>/metrics  (keyword exists: "status":"ok")

Uses the CURRENT v3 REST API (https://uptimerobot.com/api/v3/) with Bearer
auth. IMPORTANT: the legacy v2 API (api.uptimerobot.com/v2/newMonitor)
rejects monitor creation on the FREE plan with "You are not allowed to use
some settings with your current plan" - use v3.

The keyword checks guard against 200-with-garbage responses (e.g. app up but
the webapp route broken) and, for /metrics, against any regression back to
200 + {"status":"ok","data":null} (the endpoint returns HTTP 500 on stats
collection failure - see features/webapp.py). Keywords are written WITHOUT
spaces to match Flask's compact jsonify output: {"status":"ok",...}.

Idempotent: monitors whose URL already exists are skipped, so re-running is
safe. Requires `requests` (already in requirements.txt).
"""

import argparse
import os

import requests

API_ENDPOINT = "https://api.uptimerobot.com/v3/monitors"


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _request(api_key: str, method: str, payload=None) -> dict:
    """Send a v3 API request and return the JSON body.

    Raises RuntimeError with the API's own message on failure (the JSON body
    is far more useful than a bare HTTP status code).
    """
    resp = requests.request(
        method, API_ENDPOINT, headers=_headers(api_key), json=payload, timeout=30
    )
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("message", resp.text)
        except ValueError:
            detail = resp.text
        raise RuntimeError(f"{method} {API_ENDPOINT} failed (HTTP {resp.status_code}): {detail}")
    return resp.json()


def existing_monitor_urls(api_key: str) -> set:
    """Return the set of currently monitored URLs."""
    data = _request(api_key, "GET")
    return {m.get("url") for m in data.get("data", []) if m.get("url")}


def build_monitors(base_url: str) -> list:
    """The two monitors to create, keyed by their public URL."""
    base = base_url.rstrip("/")
    return [
        {
            "friendlyName": "CognitoMM /health",
            "url": f"{base}/health",
            "keywordValue": "healthy",
        },
        {
            "friendlyName": "CognitoMM /metrics",
            "url": f"{base}/metrics",
            "keywordValue": '"status":"ok"',
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
        payload = {
            "friendlyName": m["friendlyName"],
            "url": m["url"],
            "type": "HTTP",
            "interval": interval,
            "timeout": 30,
            # Alert when the keyword is NOT found in the response body
            "keywordType": "ALERT_EXISTS",
            "keywordValue": m["keywordValue"],
            "keywordCaseType": 1,  # case-insensitive
        }
        result = _request(api_key, "POST", payload)
        monitor_id = result.get("id")
        print(f"✅ Created '{m['friendlyName']}' (id {monitor_id}) -> {m['url']}")
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
