"""
Tests for the UptimeRobot monitor-creation script
(scripts/create_uptimerobot_monitors.py, v3 API).

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
    assert by_url["https://iamjoberror-bot-media.hf.space/health"]["keywordValue"] == "healthy"
    # /metrics keyword matches Flask's COMPACT jsonify output (no spaces),
    # guarding against a regression back to 200 + ok:null
    assert by_url["https://iamjoberror-bot-media.hf.space/metrics"]["keywordValue"] == '"status":"ok"'


def test_create_monitors_creates_both(monkeypatch):
    calls = []

    def fake_existing(key):
        return set()

    def fake_request(api_key, method, payload=None):
        calls.append((method, payload))
        return {"id": len(calls), "friendlyName": "x"}

    monkeypatch.setattr(script, "existing_monitor_urls", fake_existing)
    monkeypatch.setattr(script, "_request", fake_request)

    created = script.create_monitors("key", "https://example.com", interval=300)

    assert created == 2
    assert [m for m, _ in calls] == ["POST", "POST"]
    urls = [p["url"] for _, p in calls]
    assert urls == ["https://example.com/health", "https://example.com/metrics"]
    kw = {p["url"]: p["keywordValue"] for _, p in calls}
    assert kw["https://example.com/health"] == "healthy"
    assert kw["https://example.com/metrics"] == '"status":"ok"'
    # Every payload must be an HTTP monitor with the requested interval and
    # the keyword-exists check (ALERT_EXISTS)
    assert all(
        p["type"] == "HTTP" and p["interval"] == 300
        and p["keywordType"] == "ALERT_EXISTS" and p["keywordCaseType"] == 1
        for _, p in calls
    )


def test_create_monitors_skips_existing(monkeypatch):
    monkeypatch.setattr(script, "existing_monitor_urls", lambda key: {
        "https://example.com/health",
        "https://example.com/metrics",
    })
    post_calls = []
    monkeypatch.setattr(
        script, "_request",
        lambda k, m, p=None: post_calls.append(m) or {"id": 1},
    )

    created = script.create_monitors("key", "https://example.com")

    assert created == 0
    assert post_calls == []


def test_existing_monitor_urls_extracts_urls(monkeypatch):
    monkeypatch.setattr(script, "_request", lambda k, m, p=None: {
        "data": [
            {"url": "https://a.example/health"},
            {"url": "https://a.example/metrics"},
            {},  # malformed entry without a url
        ]
    })

    assert script.existing_monitor_urls("key") == {
        "https://a.example/health",
        "https://a.example/metrics",
    }


def test_request_uses_bearer_auth(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"data": []}

    def fake_request(method, url, headers, json, timeout):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr(script.requests, "request", fake_request)

    out = script._request("key123", "GET")

    assert out == {"data": []}
    assert captured["method"] == "GET"
    assert captured["url"] == "https://api.uptimerobot.com/v3/monitors"
    assert captured["headers"]["Authorization"] == "Bearer key123"


def test_request_surfaces_api_error_body(monkeypatch):
    """A 4xx/5xx must raise with the API's own message, not a bare HTTP
    status (this is what made the v2 403 so hard to diagnose)."""

    class FakeResp:
        status_code = 403
        text = "{\"stat\":\"fail\",...}"

        def json(self):
            return {"message": "You are not allowed to use some settings with your current plan."}

    monkeypatch.setattr(script.requests, "request", lambda *a, **k: FakeResp())

    with pytest.raises(RuntimeError, match="403.*not allowed to use some settings"):
        script._request("k", "POST", {})


def test_create_monitors_api_error_raises(monkeypatch):
    monkeypatch.setattr(script, "existing_monitor_urls", lambda key: set())
    monkeypatch.setattr(
        script, "_request",
        lambda k, m, p=None: (_ for _ in ()).throw(
            RuntimeError("POST https://api.uptimerobot.com/v3/monitors failed (HTTP 500): Internal Server Error")
        ),
    )
    with pytest.raises(RuntimeError, match="500"):
        script.create_monitors("key", "https://example.com")
