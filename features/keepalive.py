"""
Keep-Alive Module

Prevents platform-managed containers (Hugging Face Spaces, Render, etc.)
from being put to sleep by periodically pinging the app's own PUBLIC URL.

Why this exists (see DEPLOYMENT.md "HF Spaces sleep"):
- Hugging Face Spaces (free tier) sleep after a configurable period of
  inactivity. Only traffic to the Space's *public* URL counts as activity -
  localhost traffic does not.
- External monitors (UptimeRobot) ping every 5 minutes on the free plan,
  which leaves a race window and depends on the monitor actually running.
- A self-ping every few minutes (well below HF's minimum sleep timer) keeps
  the Space awake indefinitely with no external dependency. UptimeRobot
  remains as a belt-and-braces external watchdog for cold starts.

Behavior:
- The keep-alive URL is derived from (in order): KEEP_ALIVE_URL (explicit,
  used as-is), SPACE_HOST (HF sets this, e.g. 'owner-space.hf.space'),
  SPACE_ID (HF sets this, e.g. 'owner/space' -> https://owner-space.hf.space).
- On non-HF hosts (local dev, VPS, Docker) none of these are set, so the
  keep-alive is a silent no-op.
- KEEP_ALIVE_ENABLED=false forces it off; KEEP_ALIVE_INTERVAL (seconds,
  default 240) controls the cadence. The default must stay below Hugging
  Face's minimum sleep timer (15 minutes) to guarantee the Space never sleeps.
"""

import asyncio
import os
from typing import Optional

import aiohttp

# Default ping interval in seconds. Must be < HF's minimum sleep timer (15
# minutes) so the Space never reaches the sleep threshold.
KEEP_ALIVE_INTERVAL_DEFAULT = 240

# How long a single ping may take. When the Space is cold-starting this can
# exceed the normal timeout, so be generous (HF cold starts can take ~60s).
_PING_TIMEOUT_SECONDS = 90


def derive_keep_alive_url() -> Optional[str]:
    """Return the public URL the keep-alive should ping, or None if none.

    Resolution order:
      1. ``KEEP_ALIVE_URL`` - explicit override, used as-is (full URL).
      2. ``SPACE_HOST`` - set by Hugging Face (e.g. 'owner-space.hf.space'),
         /health is appended.
      3. ``SPACE_ID`` - set by Hugging Face (e.g. 'owner/space'),
         https://<owner>-<space>.hf.space/health is derived.
    """
    explicit = os.getenv("KEEP_ALIVE_URL", "").strip()
    if explicit:
        return explicit

    host = os.getenv("SPACE_HOST", "").strip().rstrip("/")
    if host:
        base = host if host.startswith("http") else "https://" + host
        return base + "/health"

    space_id = os.getenv("SPACE_ID", "").strip().rstrip("/")
    if space_id:
        subdomain = space_id.replace("/", "-").replace("_", "-").lower()
        return f"https://{subdomain}.hf.space/health"

    return None


def keep_alive_enabled() -> bool:
    """Whether the keep-alive is allowed to run (KEEP_ALIVE_ENABLED=false off)."""
    value = os.getenv("KEEP_ALIVE_ENABLED", "").strip().lower()
    return value not in ("0", "false", "no", "off")


def keep_alive_interval() -> int:
    """Ping interval in seconds (KEEP_ALIVE_INTERVAL, default 240)."""
    raw = os.getenv("KEEP_ALIVE_INTERVAL", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return KEEP_ALIVE_INTERVAL_DEFAULT


async def _ping_once(url: str) -> int:
    """GET the URL and return the HTTP status. Raises on network failure."""
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=_PING_TIMEOUT_SECONDS)
    ) as session:
        async with session.get(url) as resp:
            await resp.text()
            return resp.status


async def keep_alive_loop(url: Optional[str] = None, interval: Optional[int] = None):
    """Ping the public URL every `interval` seconds until the task is cancelled.

    Failures are logged and swallowed - a sleeping Space simply means the ping
    (which is what wakes it) takes longer, and the next iteration retries.
    """
    if url is None:
        url = derive_keep_alive_url()
    if url is None:
        print("⏸️ [KEEPALIVE] No public URL configured - keep-alive disabled "
              "(set KEEP_ALIVE_URL or run on a host that sets SPACE_ID/SPACE_HOST)")
        return

    if interval is None:
        interval = keep_alive_interval()

    print(f"🔁 [KEEPALIVE] Self-keep-alive enabled -> {url} every {interval}s")

    while True:
        try:
            status = await _ping_once(url)
            print(f"✅ [KEEPALIVE] ping {url} -> {status}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"⚠️ [KEEPALIVE] ping {url} failed: {type(e).__name__}: {e}")
        await asyncio.sleep(interval)


def start_keep_alive() -> Optional[asyncio.Task]:
    """Schedule the keep-alive task on the running loop.

    Returns the created task, or None when the keep-alive is disabled via
    KEEP_ALIVE_ENABLED=false or when no public URL can be derived.
    """
    if not keep_alive_enabled():
        print("⏸️ [KEEPALIVE] Disabled via KEEP_ALIVE_ENABLED=false")
        return None
    url = derive_keep_alive_url()
    if url is None:
        print("⏸️ [KEEPALIVE] No public URL configured - keep-alive disabled")
        return None
    loop = asyncio.get_running_loop()
    return loop.create_task(keep_alive_loop(url=url))
