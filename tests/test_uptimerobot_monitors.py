"""
Tests for the UptimeRobot monitor-creation script
(scripts/create_uptimerobot_monitors.py).

Pins the two monitors (/health keyword "healthy", /metrics keyword
"status":"ok" matching Flask's compact jsonify output), idempotency
(existing monitors are skipped), and API error handling.
"""

import os
import sys

import pytest

# Ensure project root is on the path so the scripts package is importable
# when this file is run standalone (python tests/test_uptimerobot_monitors.py).
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import scripts.create_uptimerobot_monitors as script
from scripts.create_uptimerobot_monitors import build_monitors


def test_build_monitors_urls_and_keywords():
    monitors = build_monitors("https://iamjoberror-bot-media.hf.space/")
    by_url = {m["url"]: m for m in monitors}

    assert set(by_url) == {
        "https://iamjoberror-bot-media.hf.space/health",
        "https://iamjoberror-bot-media.hf.space/metrics",
    }
    # /health alerts when the word "healthy" is missing from the response
    assert by_url["https://iamjoberror-bot-media.hf.space/health"]["keyword_value"] == "healthy"
    # /metrics keyword matches Flask's COMPACT jsonify output (no spaces),
    # guarding against a regression back to 200 + ok:null
    assert by_url["https://iamjoberror-bot-media.hf.space/metrics"]["keyword_value"] == '"status":"ok"'


def test_create_monitors_creates_both(monkeypatch):
    calls = []

    def fake_existing(key):
        return set()

    def fake_new(api_key, method, params):
        calls.append((method, params))
        return {"stat": "ok", "monitor": {"id": len(calls)}}

    monkeypatch.setattr(script, "existing_monitor_urls", fake_existing)
    monkeypatch.setattr(script, "api_call", fake_new)

    created = script.create_monitors("key", "https://example.com", interval=300)

    assert created == 2
    assert [m for m, _ in calls] == ["newMonitor", "newMonitor"]
    urls = [p["url"] for _, p in calls]
    assert urls == ["https://example.com/health", "https://example.com/metrics"]
    kw = {p["url"]: p["keyword_value"] for _, p in calls}
    assert kw["https://example.com/health"] == "healthy"
    assert kw["https://example.com/metrics"] == '"status":"ok"'
    # Every payload must be an HTTP monitor with the requested interval
    assert all(p["type"] == 1 and p["interval"] == 300 for _, p in calls)


def test_create_monitors_skips_existing(monkeypatch):
    monkeypatch.setattr(script, "existing_monitor_urls", lambda key: {
        "https://example.com/health",
        "https://example.com/metrics",
    })
    new_calls = []
    monkeypatch.setattr(
        script,
        "api_call",
        lambda k, m, p: new_calls.append(m) or {"stat": "ok", "monitor": {"id": 1}},
    )

    created = script.create_monitors("key", "https://example.com")

    assert created == 0
    assert new_calls == []


def test_api_call_posts_to_endpoint(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"stat": "ok"}

    def fake_post(url, data, timeout):
        captured["url"] = url
        captured["data"] = data
        return FakeResp()

    monkeypatch.setattr(script.requests, "post", fake_post)

    out = script.api_call("k", "getMonitors", {"a": 1})

    assert out == {"stat": "ok"}
    assert captured["url"] == "https://api.uptimerobot.com/v2/getMonitors"
    assert captured["data"] == {"api_key": "k", "format": "json", "a": 1}


def test_api_call_surfaces_api_error_body(monkeypatch):
    """A 4xx/5xx must raise with the API's own error message, not a bare
    HTTP status (this is what made the 403 so hard to diagnose)."""
    class FakeResp:
        status_code = 403
        text = "{\"stat\":\"fail\",...}"  # requests.Response always exposes .text

        def json(self):
            return {
                "stat": "fail",
                "error": {
                    "type": "access_denied",
                    "message": "You are not allowed to use some settings with your current plan.",
                },
            }

    monkeypatch.setattr(script.requests, "post", lambda *a, **k: FakeResp())

    with pytest.raises(RuntimeError, match="newMonitor failed.*access_denied"):
        script.api_call("k", "newMonitor", {})


def test_existing_monitor_urls_error_raises(monkeypatch):
    monkeypatch.setattr(
        script, "api_call",
        lambda k, m, p: {"stat": "fail", "error": {"type": "bad_api_key"}},
    )
    with pytest.raises(RuntimeError, match="getMonitors failed"):
        script.existing_monitor_urls("key")


def test_create_monitors_api_error_raises(monkeypatch):
    monkeypatch.setattr(script, "existing_monitor_urls", lambda key: set())
    monkeypatch.setattr(
        script, "api_call",
        lambda k, m, p: {"stat": "fail", "error": {"type": "invalid_url"}},
    )
    with pytest.raises(RuntimeError, match="newMonitor failed"):
        script.create_monitors("key", "https://example.com")
