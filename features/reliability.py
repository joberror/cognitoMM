"""
Reliability Helpers

Central home for the retry/backoff and structured-logging primitives that were
previously re-implemented ad hoc at each call site (a bare
``except FloodWait: await asyncio.sleep(e.value)`` in indexing, a one-shot
retry in broadcast, etc.).

Two concerns:

1. ``retry_on_flood`` - retries a Telegram call with exponential backoff plus
   jitter, honouring the flood-wait duration the API reports. ``sleep`` and
   ``rng`` are injectable so tests never actually wait.
2. ``struct_log`` - a single formatting/postting helper for
   ``[EVENT] action key=value`` log lines carrying user/chat/action context,
   so operational events are greppable instead of free-form prose.
"""

import asyncio
import random

try:
    from pyrogram.errors import FloodWait
except Exception:  # pragma: no cover - pyrogram always present in the app
    class FloodWait(Exception):
        def __init__(self, value=0):
            self.value = value
            super().__init__(value)


def flood_wait_seconds(exc, default=None):
    """Seconds requested by a FloodWait-ish exception (or ``default``)."""
    for attr in ("value", "x", "seconds"):
        val = getattr(exc, attr, None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None if default is None else float(default)


def is_flood_wait(exc) -> bool:
    """True for FloodWait and subclasses/same-named errors from any lib."""
    if isinstance(exc, FloodWait):
        return True
    for cls in type(exc).__mro__:
        if cls.__name__.startswith("FloodWait"):
            return True
    return False


def compute_delay(attempt: int, base_delay: float, max_delay: float) -> float:
    """Exponential backoff delay for a 1-based ``attempt`` (capped)."""
    attempt = max(1, int(attempt))
    delay = float(base_delay) * (2 ** (attempt - 1))
    return min(delay, float(max_delay))


def add_jitter(seconds: float, jitter: float, rng=random) -> float:
    """Return ``seconds`` + up to ``jitter`` fraction of it (random)."""
    seconds = max(0.0, float(seconds))
    if jitter and jitter > 0:
        spread = seconds * float(jitter)
        if spread:
            return seconds + rng.uniform(0, spread)
    return seconds


async def jittered_sleep(seconds, jitter=0.25, rng=random):
    """Sleep with jitter; returns the actual delay slept."""
    delay = add_jitter(seconds, jitter, rng)
    await asyncio.sleep(delay)
    return delay


async def retry_on_flood(coro_factory, *, max_retries=3, base_delay=1.0,
                         max_delay=60.0, jitter=0.25, rng=random,
                         retry_on=None, on_retry=None, sleep=asyncio.sleep):
    """Await ``coro_factory()``, retrying on FloodWait (and optionally
    ``retry_on`` exception types) with backoff + jitter.

    - FloodWait: waits the API-reported duration (clamped to
      ``[base_delay, max_delay]``), up to ``max_retries`` times.
    - ``retry_on``: a tuple of exception types retried with exponential
      backoff (transient network errors).
    - ``on_retry(exc, attempt, delay)`` is called before each sleep.
    - ``sleep``/``rng`` are injectable for deterministic tests.
    """
    attempt = 0
    while True:
        try:
            return await coro_factory()
        except FloodWait as exc:
            if attempt >= max_retries:
                raise
            wait = flood_wait_seconds(exc, default=base_delay) or base_delay
            wait = min(max(wait, float(base_delay)), float(max_delay))
            attempt += 1
            if on_retry:
                on_retry(exc, attempt, wait)
            await sleep(add_jitter(wait, jitter, rng))
        except Exception as exc:
            if (retry_on and isinstance(exc, retry_on)
                    and attempt < max_retries):
                attempt += 1
                wait = compute_delay(attempt, base_delay, max_delay)
                if on_retry:
                    on_retry(exc, attempt, wait)
                await sleep(add_jitter(wait, jitter, rng))
                continue
            raise


def struct_log(event: str, level: str = "info", **fields) -> str:
    """Print + return a structured ``[EVENT] event key=value`` line.

    ``None`` fields are skipped; keys are sorted so lines are stable and
    greppable. The TelegramLogger captures stdout, so these lines reach the log
    channel like any other printed output.
    """
    parts = [f"[EVENT] {event}"]
    for key in sorted(fields):
        value = fields[key]
        if value is None:
            continue
        parts.append(f"{key}={value}")
    line = " ".join(parts)
    print(line)
    return line
