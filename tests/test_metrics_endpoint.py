"""
Tests for the /metrics endpoint and bot-identity caching.

Regression: /metrics used to return {"status": "ok", "data": null} whenever
stats collection failed, because collect_comprehensive_stats() swallows
exceptions and returns None, and the handler ran the async provider on a
fresh per-request event loop (cross-loop calls to the Motor/Hydrogram
clients bound to the bot's main loop).

Fixed behavior pinned here:
- provider returns a dict   -> 200 with that data
- provider returns None     -> 500 with an error (NOT ok:null)
- provider raises           -> 500 with the error message
- provider not registered   -> 200 stub (no data key)
- collect_bot_info()        -> uses the cached identity, no Telegram call
"""

import asyncio
import os
import sys
import threading

import pytest

# Ensure project root is on the path so the features package is importable
# when this file is run standalone (python tests/test_metrics_endpoint.py).
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from features.webapp import app, set_stats_provider
from features import statistics


@pytest.fixture()
def running_loop():
    """A running event loop in a background thread (like the bot's main loop)."""
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=5)


def test_metrics_provider_dict_returns_200_with_data(running_loop):
    async def provider():
        return {"total_users": 42}

    set_stats_provider(provider, loop=running_loop)
    with app.test_client() as c:
        r = c.get("/metrics")
        body = r.get_json()

    assert r.status_code == 200
    assert body["status"] == "ok"
    assert body["data"] == {"total_users": 42}


def test_metrics_provider_none_returns_500_error(running_loop):
    """The original bug: provider returning None must NOT be ok:null."""
    async def provider():
        return None

    set_stats_provider(provider, loop=running_loop)
    with app.test_client() as c:
        r = c.get("/metrics")
        body = r.get_json()

    assert r.status_code == 500
    assert body["status"] == "error"
    assert "None" in body.get("error", "")


def test_metrics_provider_raises_returns_500(running_loop):
    async def provider():
        raise RuntimeError("boom")

    set_stats_provider(provider, loop=running_loop)
    with app.test_client() as c:
        r = c.get("/metrics")
        body = r.get_json()

    assert r.status_code == 500
    assert body["status"] == "error"
    assert "boom" in body.get("error", "")


def test_metrics_unregistered_returns_stub():
    set_stats_provider(None)
    with app.test_client() as c:
        r = c.get("/metrics")
        body = r.get_json()

    assert r.status_code == 200
    assert body["status"] == "ok"
    assert "not registered" in body.get("message", "")
    assert "data" not in body


async def test_collect_bot_info_uses_cached_identity():
    statistics.cache_bot_info({
        "username": "testbot",
        "id": 123,
        "first_name": "Test Bot",
        "dc_id": 2,
    })
    info = await statistics.collect_bot_info()

    assert info["bot_username"] == "testbot"
    assert info["bot_id"] == 123
    assert info["bot_name"] == "Test Bot"
    assert info["bot_dc_id"] == 2


async def test_collect_bot_info_partial_cache_coalesces_to_unknown():
    """A partial cache must render as 'Unknown', never as None."""
    statistics.cache_bot_info({"username": "testbot"})
    info = await statistics.collect_bot_info()

    assert info["bot_username"] == "testbot"
    assert info["bot_name"] == "Unknown"
    assert info["bot_id"] == "Unknown"


async def test_collect_bot_info_no_cache_no_client_uses_unknown():
    statistics.cache_bot_info({})
    info = await statistics.collect_bot_info()

    assert "Unknown" in info["bot_username"]
