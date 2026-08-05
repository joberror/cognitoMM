# 🚀 Deployment Guide — CognitoMM

This guide covers deploying the CognitoMM Telegram bot in three environments:

1. **Local development** (Docker Compose)
2. **Production server** (Docker Compose)
3. **Hugging Face Spaces** (free tier)

---

## 📋 Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.12.x | Pinned in `Dockerfile` and `pyproject.toml` |
| Docker | 24+ | For Docker Compose deployment |
| Docker Compose | v2 | Included with Docker Desktop |
| MongoDB | 7+ | Runs in its own container via Compose |
| Telegram API credentials | — | Get from [my.telegram.org/apps](https://my.telegram.org/apps) |
| Bot Token | — | Get from [@BotFather](https://t.me/BotFather) |

---

## ⚙️ Environment Variables

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `API_ID` | Telegram API ID (from my.telegram.org) | `123456` |
| `API_HASH` | Telegram API hash | `abc123def456` |
| `BOT_TOKEN` | Bot token from @BotFather | `123:ABC` |
| `MONGO_URI` | MongoDB connection string | `mongodb://mongo:27017` |
| `MONGO_DB` | MongoDB database name | `moviebot` |
| `ADMINS` | Comma-separated Telegram user IDs | `123456789,987654321` |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `7860` | Port for the health-check web server |
| `LOG_CHANNEL` | — | Telegram channel ID for bot logs (e.g. `-1001234567890`) |
| `TMDB_API` | — | TMDb API key for the movie request feature |
| `FUZZY_THRESHOLD` | `68` | Fuzzy search threshold (0–100) |
| `AUTO_INDEXING` | `True` | Enable auto-indexing on startup |
| `BROADCAST_RATE_LIMIT` | `25` | Broadcast messages per second |
| `BROADCAST_TEST_MODE` | `False` | Enable broadcast test mode |
| `SUPPORT_LINK` | `https://t.me/` | Support group link for /start |
| `START_MESSAGE` | `Welcome to the bot!...` | Custom /start message |

---

## 🐳 Local Development (Docker Compose)

### Quick Start

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your API_ID, API_HASH, BOT_TOKEN, MONGO_URI, ADMINS

# 2. Build and start
docker compose up -d

# 3. View logs
docker compose logs -f app

# 4. Stop
docker compose down
```

The stack starts two containers:

- **`cognito_bot`** — The Telegram bot (auto-restarts on crash)
- **`cognito_mongo`** — MongoDB 7 (data persisted in a Docker volume)

### Health Checks

The bot exposes a health-check endpoint at `http://localhost:7860/health`. Docker Compose waits for both services to be healthy before connecting them.

```bash
curl http://localhost:7860/health
# {"status":"healthy","timestamp":"2026-08-04T04:00:00.000000+00:00"}
```

### Rebuilding

```bash
docker compose build --pull   # Pull latest base images
docker compose up -d          # Start with new image
```

> **Tip:** The `Dockerfile` uses BuildKit cache mounts for both **apt**
> (`/var/cache/apt` + `/var/lib/apt`) and **pip** (`/root/.cache/pip`), so system
> and Python packages download once and are reused across rebuilds. Rebuilding after
> a source change only re-runs the fast steps, and a flaky network won't force a
> full re-download. Run `docker builder prune` to clear the cache (including both
> mounts) if you ever need a completely clean dependency fetch.

### MongoDB Shell Access

```bash
docker compose exec mongodb mongosh moviebot
```

---

## 🏭 Production Deployment

### On a VPS (Linux)

```bash
# 1. Clone the repo
git clone https://github.com/joberror/cognitoMM.git
cd cognitoMM

# 2. Configure
cp .env.example .env
nano .env   # Set production values

# 3. Run with Docker Compose
docker compose up -d

# 4. (Optional) Set up a reverse proxy for the health endpoint
```

### Reverse Proxy (Nginx)

```nginx
server {
    listen 80;
    server_name bot.example.com;

    location / {
        proxy_pass http://127.0.0.1:7860;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Monitoring

The `/metrics` endpoint returns JSON with live database statistics when the bot is running:

```bash
curl http://localhost:7860/metrics
```

You can connect this to monitoring tools like BetterStack, Grafana, or Uptime Kuma.

---

## 🤗 Hugging Face Spaces Deployment

### Prerequisites

- A Hugging Face account
- A GitHub account (for the CI/CD sync)

### Step 1: Create a Space

1. Go to [huggingface.co/spaces](https://huggingface.co/spaces)
2. Click **Create new Space**
3. Set **Space name** (e.g., `bot-media`)
4. Set **License** to `MIT`
5. Set **Space SDK** to `Docker`
6. Click **Create Space**

### Step 2: Configure Secrets

In your Space settings → **Repository secrets**:

| Secret | Value |
|--------|-------|
| `API_ID` | Your Telegram API ID |
| `API_HASH` | Your Telegram API hash |
| `BOT_TOKEN` | Your bot token |
| `MONGO_URI` | MongoDB Atlas connection string |
| `MONGO_DB` | `moviebot` |
| `ADMINS` | Your Telegram user ID(s) |

Set these as **secret** (not just environment variables) to keep them encrypted.

> **Note:** Hugging Face Spaces does **not** have a persistent MongoDB service. You must use [MongoDB Atlas](https://www.mongodb.com/atlas) (free tier) or another external MongoDB provider.

### Step 3: Set up GitHub Sync (CI/CD)

The `.github/workflows/deploy.yml` workflow automatically syncs the `main` branch from GitHub to Hugging Face Spaces.

1. Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions**
2. Add a repository secret:
   - **Name:** `HF_TOKEN`
   - **Value:** Your Hugging Face access token (generate at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens))
3. Update the workflow file (`.github/workflows/deploy.yml`) with your actual HF Space repo ID.
4. Push to `main` — the workflow automatically syncs to HF Spaces.

### Step 4: (Alternative) Manual Sync via Git

```bash
# Add the HF Space as a remote
git remote add hf https://huggingface.co/spaces/iamjoberror/bot-media

# Push directly
git push hf main
```

### Step 5: Verify

Once deployed, your Space will:

1. Build the Docker image (using the `Dockerfile`)
2. Start the bot → it connects to Telegram
3. The embedded web server starts on port 7860 (HF automatically routes traffic)
4. Visit `https://iamjoberror-bot-media.hf.space/health` to verify

---

## 🔧 Troubleshooting

### Bot won't start

```bash
# Check logs
docker compose logs app

# Common issues:
# - API_ID or API_HASH wrong → verify at my.telegram.org
# - BOT_TOKEN invalid → regenerate with @BotFather
# - MONGO_URI unreachable → check MongoDB Atlas IP whitelist
# - Port 7860 already in use → change PORT in .env
```

### MongoDB connection refused

```bash
# Verify MongoDB is running
docker compose ps

# Check MongoDB logs
docker compose logs mongodb

# Test connection
docker compose exec app python -c "from pymongo import MongoClient; c=MongoClient('mongodb://mongo:27017'); print(c.server_info())"
```

### Session file issues

The bot creates a `.session` file in the working directory. If you see "session revoked" or "logged out" errors:

```bash
# Remove stale session files and restart
docker compose down
rm -f *.session *.session-journal
docker compose up -d
```

### Docker build fails

```bash
# Try with no cache
docker compose build --no-cache

# Ensure Docker is up to date
docker version
```

---

## 📁 Project Structure

```
cognitoMM/
├── Dockerfile            # Multi-stage Docker build
├── docker-compose.yml    # Local dev/prod stack
├── .env.example          # Environment variable template
├── DEPLOYMENT.md         # ← You are here
├── run.sh                # Convenience launcher
├── main.py               # Application entry point
├── features/
│   ├── bot.py            # Bot lifecycle & handler registration
│   ├── webapp.py         # Flask health-check server (/health, /metrics)
│   ├── config.py         # Environment variable loading
│   ├── database.py       # MongoDB connection & indexes
│   ├── commands.py       # Telegram command handlers
│   ├── indexing.py       # Message indexing & orphan prune
│   └── ...               # Other feature modules
└── .github/workflows/
    └── deploy.yml        # GitHub → HF Spaces sync
```

---

## 📊 Monitoring Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Bot status, uptime, version |
| `GET /health` | Health check for Docker/K8s/BetterStack |
| `GET /metrics` | Live database & indexing statistics |
| `GET /robots.txt` | Disallow search crawlers |