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
PYTHON_VERSION=$(python --version 2>&1)
echo "🐍 $PYTHON_VERSION"

# Check for Pyrogram/Hydrogram
if python -c "import pyrogram" 2>/dev/null; then
    echo "📦 Pyrogram: $(python -c 'import pyrogram; print(pyrogram.__version__)')"
elif python -c "import hydrogram" 2>/dev/null; then
    echo "📦 Hydrogram: $(python -c 'import hydrogram; print(hydrogram.__version__)')"
else
    echo "⚠️  Neither Pyrogram nor Hydrogram found — check requirements.txt"
fi

# Clean up stale session files
echo "🧹 Cleaning stale session files..."
rm -f *.session *.session-journal *.session-shm *.session-wal

echo ""
echo "🎬 Starting MovieBot..."
echo "========================"
exec python main.py