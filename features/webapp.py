"""
Web App Module for Health Checks & Metrics

Provides a Flask web server to keep the bot alive on platforms that
require an active web port (Hugging Face Spaces, Render, etc.) and
exposes /health (BetterStack monitoring) and /metrics endpoints.

Uses waitress as the production WSGI server when available, falling
back to Flask's built-in server (threaded=True).
"""

import os
import json
import signal
import threading
from datetime import datetime, timezone
from typing import Optional

from flask import Flask, jsonify, request

try:
    from .config import BOT_START_TIME
except ImportError:
    BOT_START_TIME = datetime.now(timezone.utc)

# ------------------------------------------------------------------ #
#  Store / stats callbacks (set by the bot at startup)                #
# ------------------------------------------------------------------ #

_stats_provider: Optional[callable] = None
"""Optional async callable returning a dict for the /metrics endpoint."""

_bot_loop = None
"""Event loop the stats provider must run on (the bot's main loop).

The Motor and Pyroblack clients are bound to this loop, so /metrics must
schedule the provider there instead of on a fresh per-request loop.
"""

# Hard cap on how long a /metrics request waits for stats collection. The
# timeout is wall-clock and includes queue time on the bot's main loop, so
# it can be raised via METRICS_TIMEOUT (seconds) for slow/sharded DBs.
_METRICS_TIMEOUT = float(os.environ.get("METRICS_TIMEOUT", "30"))


def set_stats_provider(fn: callable, loop=None):
    """Register a callable (async or sync) that returns stats dict.

    Called by the bot's main() after the database is ready. Pass `loop` =
    the bot's running event loop so /metrics can schedule the provider on
    it (thread-safe) rather than on a fresh per-request loop, which breaks
    the Motor/Pyroblack clients bound to the main loop.
    """
    global _stats_provider, _bot_loop
    _stats_provider = fn
    _bot_loop = loop


# ------------------------------------------------------------------ #
#  Flask app                                                          #
# ------------------------------------------------------------------ #

app = Flask(__name__)

# ------------------------------------------------------------------ #
#  JSON serialization: handle MongoDB/bson types                      #
# ------------------------------------------------------------------ #

try:
    from flask.json.provider import DefaultJSONProvider
except ImportError:  # very old Flask - rely on the projection fix instead
    DefaultJSONProvider = None
    print("⚠️ [Webapp] flask.json.provider unavailable - bson types will not auto-serialize")

if DefaultJSONProvider is not None:
    class _MongoJSONProvider(DefaultJSONProvider):
        """Flask JSON provider that also serializes MongoDB/bson types.

        Stats documents can carry bson types (ObjectId from aggregation `_id`,
        Timestamp, Decimal128, Binary), which would otherwise make jsonify
        raise "Object of type ... is not JSON serializable" and turn /metrics
        into a 500.
        """

        @staticmethod
        def default(o):
            try:
                from bson import Binary, Decimal128, ObjectId, Timestamp
                if isinstance(o, (ObjectId, Decimal128, Binary, Timestamp)):
                    return str(o)
            except ImportError:
                pass
            return DefaultJSONProvider.default(o)

    app.json = _MongoJSONProvider(app)


@app.after_request
def add_cors_headers(response):
    """Allow cross-origin requests from monitoring dashboards."""
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET, OPTIONS")
    response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type")
    return response


@app.route("/")
def index():
    """Main landing page."""
    return jsonify({
        "status": "running",
        "bot": "CognitoMM",
        "version": os.environ.get("BOT_VERSION", "unknown"),
        "uptime": str(datetime.now(timezone.utc) - BOT_START_TIME),
        "message": "Bot is alive and healthy!",
    })


@app.route("/health")
def health_check():
    """Dedicated health check endpoint (BetterStack / K8s / Docker)."""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/metrics")
def metrics():
    """Optional metrics endpoint for monitoring dashboards.

    Returns a JSON blob with DB stats, index counts, etc. when the
    bot has registered a `_stats_provider`; otherwise returns a stub.
    """
    if _stats_provider is not None:
        try:
            import asyncio
            if _bot_loop is not None:
                # Run the provider on the bot's OWN event loop (thread-safe).
                # A fresh per-request loop makes cross-loop calls to the
                # Motor/Pyroblack clients fail, and those errors used to be
                # swallowed and returned as `data: null`.
                future = asyncio.run_coroutine_threadsafe(_stats_provider(), _bot_loop)
                try:
                    data = future.result(timeout=_METRICS_TIMEOUT)
                except TimeoutError:
                    # Don't leave the provider running forever on the bot's
                    # loop - cancel it (best-effort) and report a failure.
                    future.cancel()
                    raise
            else:
                # No loop captured (e.g. direct import in tests/scripts).
                print("⚠️ [Webapp] /metrics called without a bot loop - running "
                      "provider on a fresh loop (cross-loop risk)")
                data = asyncio.run(_stats_provider())
            if data is None:
                # Provider swallowed an error (see bot logs: "Error collecting
                # stats: ..."). Surface it as 500 so monitors see a failure.
                return jsonify({
                    "status": "error",
                    "error": "Stats provider returned None (check bot logs for 'Error collecting stats')",
                }), 500
            return jsonify({
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": data,
            })
        except Exception as e:
            return jsonify({
                "status": "error",
                "error": str(e),
            }), 500
    return jsonify({
        "status": "ok",
        "message": "Stats provider not registered (bot may not be fully initialized).",
    })


@app.route("/robots.txt")
def robots_txt():
    """Discourage crawlers from indexing the bot's web endpoints."""
    return "User-agent: *\nDisallow: /\n", 200, {"Content-Type": "text/plain"}


# ------------------------------------------------------------------ #
#  Server runner (production-grade via waitress if available)         #
# ------------------------------------------------------------------ #

_server = None
"""Holds the running server instance for graceful shutdown."""


def _get_port() -> int:
    return int(os.environ.get("PORT", 7860))


def run_flask():
    """Run the Flask app with a production WSGI server (waitress) or fallback."""
    port = _get_port()
    use_waitress = False
    try:
        from waitress import serve
        use_waitress = True
    except ImportError:
        pass

    if use_waitress:
        print(f"🚀 [Webapp] Starting waitress server on 0.0.0.0:{port}")
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=4)
    else:
        print(f"🚀 [Webapp] Starting Flask dev server on 0.0.0.0:{port}")
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


def start_webapp() -> threading.Thread:
    """Start the web application in a background daemon thread.

    Returns:
        The thread object so the caller can keep a reference.
    """
    t = threading.Thread(target=run_flask, daemon=True, name="webapp")
    t.start()
    print(f"✅ [Webapp] Listening on port {_get_port()}")
    return t