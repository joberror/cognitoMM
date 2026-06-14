"""
Web App Module for Health Checks

This module provides a simple Flask web server to keep the bot alive
on platforms that require an active web port (like Hugging Face Spaces,
Render, or for BetterStack monitoring).
"""

import os
from flask import Flask, jsonify
from datetime import datetime
import threading

# Import start time from config if needed, otherwise use local
try:
    from .config import BOT_START_TIME
except ImportError:
    BOT_START_TIME = datetime.now()

app = Flask(__name__)

@app.route('/')
def index():
    """Main landing page"""
    return jsonify({
        "status": "running",
        "bot": "CognitoMM",
        "uptime": str(datetime.now() - BOT_START_TIME),
        "message": "Bot is alive and healthy!"
    })

@app.route('/health')
def health_check():
    """Dedicated health check endpoint for BetterStack"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    })

def run_flask():
    """Run the Flask app"""
    # Use port from environment variable (standard for most hosting platforms)
    port = int(os.environ.get("PORT", 8080))
    # Run Flask with host 0.0.0.0 to be accessible externally
    app.run(host='0.0.0.0', port=port)

def start_webapp():
    """Start the web application in a background thread"""
    webapp_thread = threading.Thread(target=run_flask, daemon=True)
    webapp_thread.start()
    print(f"🌐 Webapp started in background thread (Port: {os.environ.get('PORT', 8080)})")
    return webapp_thread
