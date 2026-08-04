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


def set_stats_provider(fn: callable):
    """Register a callable (async or sync) that returns stats dict.

    Called by the bot's main() after the database is ready.
    """
    global _stats_provider
    _stats_provider = fn


# ------------------------------------------------------------------ #
#  Flask app                                                          #
# ------------------------------------------------------------------ #

app = Flask(__name__)


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
            loop = asyncio.new_event_loop()
            try:
                data = loop.run_until_complete(_stats_provider())
            finally:
                loop.close()
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