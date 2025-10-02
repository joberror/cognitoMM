#!/bin/bash

# MovieBot Launcher Script
# This ensures we use the correct Python version and environment

echo "🚀 MovieBot Launcher"
echo "===================="

# Check if we're in the right directory
if [ ! -f "main.py" ]; then
    echo "❌ Error: main.py not found. Please run this script from the project directory."
    exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found. Please create it with your configuration."
    exit 1
fi

# Set Python version using pyenv
echo "🔧 Setting Python version to 3.12.8..."
pyenv local 3.12.8

# Check Python version
PYTHON_VERSION=$(python --version 2>&1)
echo "🐍 Using: $PYTHON_VERSION"

# Check if it's the right version
if [[ "$PYTHON_VERSION" == *"3.12.8"* ]]; then
    echo "✅ Correct Python version detected"
else
    echo "⚠️  Warning: Expected Python 3.12.8, got: $PYTHON_VERSION"
    echo "⚠️  This may cause compatibility issues with Pyrogram"
fi

# Check Pyrogram version
PYROGRAM_VERSION=$(python -c "import pyrogram; print(pyrogram.__version__)" 2>/dev/null)
if [ $? -eq 0 ]; then
    echo "📦 Pyrogram version: $PYROGRAM_VERSION"
    if [[ "$PYROGRAM_VERSION" == "2.0.106" ]]; then
        echo "✅ Correct Pyrogram version"
    else
        echo "⚠️  Warning: Expected Pyrogram 2.0.106, got: $PYROGRAM_VERSION"
    fi
else
    echo "❌ Error: Pyrogram not found or not importable"
    exit 1
fi

# Clean up any locked session files
echo "🧹 Cleaning up session files..."
rm -f *.session *.session-journal

echo ""
echo "🎬 Starting MovieBot..."
echo "======================"

# Run the application
python main.py
