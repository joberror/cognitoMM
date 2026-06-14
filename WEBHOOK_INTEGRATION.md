# Webhook & Health Check Integration Summary

I have integrated a Flask-based web server into the CognitoMM bot to support BetterStack monitoring and ensure the bot remains active on hosting platforms like Hugging Face Spaces or Render.

## Key Changes

1.  **New Module: `features/webapp.py`**
    *   Implements a lightweight Flask server.
    *   **Endpoints:**
        *   `/`: Returns bot status, name, and uptime.
        *   `/health`: A dedicated endpoint for BetterStack or other monitoring services.
    *   **Configurable Port:** Uses the `PORT` environment variable (defaults to `8080`).

2.  **Bot Startup Logic (`features/bot.py`)**
    *   The web server is automatically started in a background thread when the bot runs.
    *   This ensures the web server doesn't block the main Hydrogram event loop.

3.  **Dependency Update (`requirements.txt`)**
    *   Added `Flask` to the project dependencies.

4.  **Deployment Configurations**
    *   **Dockerfile:** Added `EXPOSE 8080` to document the health check port.
    *   **docker-compose.yml:** Added port mapping (`8080:8080`) so the health check endpoint is accessible from the host.

## How to use with BetterStack

1.  Deploy the bot to your server or hosting platform.
2.  In BetterStack, create a new "HTTP Monitor".
3.  Set the URL to: `http://your-server-ip-or-domain:8080/health`
4.  BetterStack will now ping this endpoint regularly, keeping your bot "alive" and notifying you if it goes down.

## Environment Variables (Optional)

*   `PORT`: The port on which the web server will run (Default: `8080`).