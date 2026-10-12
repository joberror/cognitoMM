#!/bin/bash
# ========================================================================
#  MovieBot Launcher
#  Usage: ./run.sh [--help] [--docker]
# ========================================================================
set -euo pipefail

show_help() {
    cat <<EOF
MovieBot Launcher — CognitoMM

Usage:
  ./run.sh                  Start the bot directly (requires Python + .env)
  ./run.sh --docker         Build and run via Docker Compose instead
  ./run.sh --help           Show this message

Environment:
  cp .env.example .env   then edit with your values

Developer tools:
  make check             run the static import check
  make test              install deps, then run the full pytest suite
  make verify            run everything CI runs (check + test)
  make install-hooks     install the pre-commit hook (runs the static check)

See DEPLOYMENT.md for full Docker, VPS, and Hugging Face Spaces guides.

EOF
    exit 0
}

# --- Parse flags ---
DOCKER_MODE=false
for arg in "$@"; do
    case "$arg" in
        --help|-h) show_help ;;
        --docker) DOCKER_MODE=true ;;
        *) echo "❌ Unknown flag: $arg"; show_help ;;
    esac
done

# --- Resolve the Python interpreter ---
# Prefer the project virtualenv (.venv) — it holds pyroblack (the Telegram
# framework this bot runs on). Fall back to the plain `python` on PATH for
# environments without a .venv (e.g. the Docker image, where the image's own
# python is already set up).
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python"
fi

# --- Docker mode ---
if $DOCKER_MODE; then
    echo "🐳 Building and starting via Docker Compose..."
    if [ ! -f ".env" ]; then
        echo "❌ .env file not found. Create one before running."
        exit 1
    fi
    docker compose build --pull
    docker compose up -d
    echo "✅ Bot started. Logs: docker compose logs -f"
    exit 0
fi

# --- Direct mode ---
echo "🚀 MovieBot Launcher"
echo "===================="

# Check we're in the project root
if [ ! -f "main.py" ]; then
    echo "❌ main.py not found — run this script from the project directory."
    exit 1
fi

# Check .env
if [ ! -f ".env" ]; then
    echo "❌ .env file not found. Create it with your configuration."
    exit 1
fi

# Check Python version (informational only)
echo "🐍 $("$PYTHON" --version 2>&1)"

# Check for the Telegram library (pyroblack — installs as the `pyrogram` package)
if "$PYTHON" -c "import pyrogram" 2>/dev/null; then
    echo "📦 Pyroblack (pyrogram): $("$PYTHON" -c 'import pyrogram; print(pyrogram.__version__)')"
else
    echo "⚠️  Pyroblack not found in $PYTHON — install it with 'pip install pyroblack' (see requirements.txt)"
fi

# Session files
# The .session file stores the bot's auth AND the Telegram peer cache (access
# hashes). Deleting it on every start makes log sends fail with
# PEER_ID_INVALID until each peer re-resolves (e.g. the admin messages the
# bot again). Keep sessions by default; only wipe when explicitly asked
# (corrupt session) via CLEAN_SESSIONS=1.
if [ "${CLEAN_SESSIONS:-0}" = "1" ]; then
    echo "🧹 CLEAN_SESSIONS=1 - wiping session files..."
    rm -f *.session *.session-journal *.session-shm *.session-wal
else
    echo "ℹ️  Keeping session files (set CLEAN_SESSIONS=1 to wipe stale ones)"
fi

echo ""
echo "🎬 Starting MovieBot (using $PYTHON)..."
echo "========================"
exec "$PYTHON" main.py