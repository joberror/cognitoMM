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

> **📦 Telegram library (pyroblack).** The bot's MTProto framework is
> **pyroblack**, the actively maintained successor to hydrogram. Pyroblack
> installs as the **`pyrogram`** package: `pip install pyroblack` provides
> `import pyrogram`, so every import in the codebase reads
> `from pyrogram import ...` (`Client`, `filters`, `types`, `handlers`,
> `errors`) — there is no separate `pyroblack` import namespace. This matters
> when setting up a local environment: after `pip install -r requirements.txt`
> you will import from `pyrogram`, and `./run.sh` / `make` select the project
> venv (`.venv`, which holds pyroblack) automatically when present.

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
| `KEEP_ALIVE_URL` | — | Public URL the bot pings to keep managed hosts (HF Spaces) awake. Auto-derived from `SPACE_HOST`/`SPACE_ID` on HF — only needed for custom domains / other hosts |
| `KEEP_ALIVE_INTERVAL` | `240` | Self-ping interval in seconds (must stay below the host's sleep timer, e.g. HF's 15 min) |
| `KEEP_ALIVE_ENABLED` | `true` | Set `false` to disable the self-keep-alive |
| `CLEAN_SESSIONS` | `0` | Set `1` to wipe `.session` files at startup (`run.sh` only) — see *Session file issues* below |
| `TMDB_ENRICH_INDEX` | `true` | Enrich newly indexed entries with TMDb metadata (poster, genres, rating, IMDb) — powers `/genres` and posters on `/random`/inline |
| `DB_RESCAN_ENABLED` | `true` | Scheduled incremental rescan (background `/update_db`) for all registered channels |
| `DB_RESCAN_INTERVAL_MINUTES` | `360` | Rescan cadence (every 6 hours) |

> **Keep-alive on VPS/Docker:** the self-ping exists for managed hosts (HF Spaces) —
> VPS/Docker containers don't sleep, so `.env.example` ships with
> `KEEP_ALIVE_ENABLED=false`. On HF Spaces leave it unset (or `true`); the URL is
> auto-derived from `SPACE_HOST`/`SPACE_ID`.

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

### Smoke-test the commands

Once the stack is up, message the bot in Telegram (admin commands only work for
the user IDs listed in `ADMINS`):

| Command | What to expect |
|---------|----------------|
| `/search <title>` | Results with deduplicated copies + `Pick [n]` quality chooser; TMDb rating/genres/IMDb when `TMDB_API` is set |
| `/random` | A random indexed title (poster photo once metadata is enriched) |
| `/genres` | Genre list with counts (needs enriched metadata — run `/enrich` once to backfill); `/genres <name>` browses paginated with one deduped line per title (series show DB + real TMDb season/episode totals) |
| `/watch <title>` / `/watchlist` | Adds to your watchlist; you get a DM the moment a new copy is indexed |
| `/logs` | Recent audit-log entries from `logs_col` |
| `/enrich [n]` / `/enrich_status` | Backfill TMDb metadata / show enriched–pending–no-match progress |

See `info/commands.md` for the full command reference.

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

### Monitoring (UptimeRobot)

The bot exposes two endpoints for monitoring:

| Endpoint | Purpose | Expected response |
|----------|---------|-------------------|
| `GET /health` | Liveness for Docker/K8s/UptimeRobot | `{"status":"healthy",...}` |
| `GET /metrics` | Live DB/indexing stats — returns **HTTP 500** if stats collection fails | `{"status":"ok","timestamp":...,"data":{...}}` |

**Quick start** — creates both monitors on your UptimeRobot account:

```bash
# Prefer the project venv (has all deps); plain `python` also works if you
# installed requirements into your default interpreter.
UPTIMEROBOT_API_KEY=your-key .venv/bin/python scripts/create_uptimerobot_monitors.py
```

This creates (idempotently — monitors whose URL already exists are skipped):

| Monitor | URL | Keyword check |
|---------|-----|---------------|
| `CognitoMM /health` | `https://iamjoberror-bot-media.hf.space/health` | contains `healthy` |
| `CognitoMM /metrics` | `https://iamjoberror-bot-media.hf.space/metrics` | contains `"status":"ok"` |

Point it at a different host with `--base-url http://localhost:7860` (local/dev)
or your own domain (production). Uses the current [UptimeRobot v3 API](https://uptimerobot.com/api/v3/)
(Bearer auth). **Note:** the legacy v2 API rejects monitor creation on the free plan
("You are not allowed to use some settings with your current plan") — v3 is required.

**Manual alternative** (dashboard, ~2 min):
1. Sign up at [uptimerobot.com](https://uptimerobot.com) → *Add New Monitor*.
2. Monitor 1: type **HTTP(s)**, URL `https://iamjoberror-bot-media.hf.space/health`,
   interval **5 minutes**, keyword type *Exists*, keyword `healthy`.
3. Monitor 2: same settings, URL `https://iamjoberror-bot-media.hf.space/metrics`,
   keyword `"status":"ok"`.
4. Set **alert contacts** (email/Slack) under *My Settings → Alert Contacts*.

**Notes:**
- Free tier: 50 monitors @ 5-minute checks, email alerts.
- **HF Spaces sleep:** free Spaces pause after a period of inactivity, which shows
  as downtime on the dashboard. The bot now runs a **built-in self-keep-alive**:
  it pings its own public URL (`/health`) every 240s, so the Space never reaches
  HF's minimum sleep timer. UptimeRobot is the belt-and-braces external watchdog
  for cold starts (the self-ping can't fire while the container is asleep, so an
  external ping is what wakes it). Expect occasional "down" alerts only if the
  Space is cold-starting.
- `/metrics` intentionally returns 500 when stats collection fails or exceeds
  `METRICS_TIMEOUT` (default 30s) — monitors see a real failure, never `ok:null`.

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
4. The bot self-pings its public URL every 240s (**keep-alive**) so the Space
   never goes to sleep — verify with
   `https://iamjoberror-bot-media.hf.space/health`

> **Note:** to *wake* an already-sleeping Space, an external request is needed
> (visiting the URL, or an UptimeRobot monitor — see *Monitoring* above). The
> self-ping only runs while the container is awake, which is why it's paired
> with the UptimeRobot monitors.

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

The bot creates a `.session` file in the working directory. This file stores the
bot's auth **and the Telegram peer cache (access hashes)**. **Keep it across
restarts** — deleting it makes log sends fail with `[403 PEER_ID_INVALID]` until
each peer re-resolves (e.g. the admin messages the bot again). `run.sh` keeps
sessions by default. If you see "session revoked" or "logged out" errors and need
to wipe them:

```bash
# Remove stale session files and restart (run.sh) - or set CLEAN_SESSIONS=1
docker compose down
rm -f *.session *.session-journal
docker compose up -d
```

### "Failed to send log to Telegram: [403 PEER_ID_INVALID]"

This happens on a **fresh session** (HF rebuild, or after manually deleting the
`.session` file): the bot hasn't cached the peer (access hash) for `LOG_CHANNEL`
yet, so `send_message` fails until an update from that chat caches it. The bot
now handles this automatically:

- At startup it resolves the log peer via `get_chat()` (fixes channels/groups
  immediately).
- On a `PEER_ID_INVALID` send it re-resolves once per flush, so it recovers the
  moment the peer is reachable — normally as soon as the admin sends the bot
  any message/command.

If the error persists even after messaging the bot, double-check `LOG_CHANNEL`:
- For a **private chat**, use your numeric user ID and make sure you have
  started the bot (sent it at least one message).
- For a **channel/group**, use the `-100...` ID and confirm the bot is a member.

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