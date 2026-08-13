"""
Tests for the self-keep-alive module (features/keepalive.py).

Pins:
- URL derivation: KEEP_ALIVE_URL override (used as-is), HF SPACE_HOST
  (/health appended), HF SPACE_ID (public subdomain derived), and the
  no-URL -> disabled case.
- The ping loop: GETs the public URL, tolerates failures without crashing,
  and runs at the configured cadence.
- start_keep_alive(): returns a task when enabled + URL derivable, None when
  disabled or no URL.
"""

import asyncio
import os
import sys

# Ensure project root is on the path so the features package is importable
# when this file is run standalone (python tests/test_keepalive.py).
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from features import keepalive

# ------------------------------------------------------------------ #
#  URL derivation                                                    #
# ------------------------------------------------------------------ #


def test_no_url_when_nothing_configured(monkeypatch):
    for var in ("KEEP_ALIVE_URL", "SPACE_HOST", "SPACE_ID"):
        monkeypatch.delenv(var, raising=False)

    assert keepalive.derive_keep_alive_url() is None


def test_explicit_url_used_as_is(monkeypatch):
    monkeypatch.setenv("KEEP_ALIVE_URL", "https://example.com/health")
    monkeypatch.delenv("SPACE_HOST", raising=False)
    monkeypatch.delenv("SPACE_ID", raising=False)

    assert keepalive.derive_keep_alive_url() == "https://example.com/health"


def test_space_host_gets_health_appended(monkeypatch):
    monkeypatch.setenv("SPACE_HOST", "iamjoberror-bot-media.hf.space")
    monkeypatch.delenv("KEEP_ALIVE_URL", raising=False)
    monkeypatch.delenv("SPACE_ID", raising=False)

    assert keepalive.derive_keep_alive_url() == "https://iamjoberror-bot-media.hf.space/health"


def test_space_id_derives_hf_subdomain(monkeypatch):
    monkeypatch.setenv("SPACE_ID", "iamjoberror/bot-media")
    monkeypatch.delenv("KEEP_ALIVE_URL", raising=False)
    monkeypatch.delenv("SPACE_HOST", raising=False)

    assert keepalive.derive_keep_alive_url() == "https://iamjoberror-bot-media.hf.space/health"


def test_explicit_url_wins_over_hf_vars(monkeypatch):
    monkeypatch.setenv("KEEP_ALIVE_URL", "https://custom.example/health")
    monkeypatch.setenv("SPACE_HOST", "iamjoberror-bot-media.hf.space")
    monkeypatch.setenv("SPACE_ID", "iamjoberror/bot-media")

    assert keepalive.derive_keep_alive_url() == "https://custom.example/health"


def test_keep_alive_interval_default_and_override(monkeypatch):
    monkeypatch.delenv("KEEP_ALIVE_INTERVAL", raising=False)
    assert keepalive.keep_alive_interval() == 240

    monkeypatch.setenv("KEEP_ALIVE_INTERVAL", "60")
    assert keepalive.keep_alive_interval() == 60

    monkeypatch.setenv("KEEP_ALIVE_INTERVAL", "bogus")
    assert keepalive.keep_alive_interval() == 240


# ------------------------------------------------------------------ #
#  Ping loop (aiohttp mocked)                                        #
# ------------------------------------------------------------------ #


class FakeResp:
    status = 200

    async def text(self):
        return "healthy"


class FakeGet:
    """Async context manager returned by FakeSession.get()."""

    def __init__(self, url):
        self.url = url
        self.entered = False

    async def __aenter__(self):
        self.entered = True
        return FakeResp()

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Replaces aiohttp.ClientSession; records every URL it was asked to GET."""

    def __init__(self, *args, **kwargs):
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return FakeGet(url)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FailingSession(FakeSession):
    """Session whose first get() raises (simulates a sleeping/cold Space)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_first = True

    def get(self, url):
        self.calls.append(url)
        if self.fail_first:
            self.fail_first = False
            raise ConnectionError("space is asleep")
        return FakeGet(url)


async def test_keep_alive_loop_pings_repeatedly(monkeypatch):
    monkeypatch.setenv("KEEP_ALIVE_URL", "https://example.com/health")
    session = FakeSession()
    monkeypatch.setattr(keepalive.aiohttp, "ClientSession", lambda *a, **k: session)

    # Run the loop for a few short cycles, then cancel it.
    task = asyncio.create_task(keepalive.keep_alive_loop(interval=0.01))
    await asyncio.sleep(0.06)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(session.calls) >= 3, f"expected multiple pings, got {session.calls}"
    assert all(u == "https://example.com/health" for u in session.calls)


async def test_keep_alive_loop_tolerates_failures(monkeypatch):
    """A failed ping must not kill the loop - the next cycle retries."""
    monkeypatch.setenv("KEEP_ALIVE_URL", "https://example.com/health")
    session = FailingSession()
    monkeypatch.setattr(keepalive.aiohttp, "ClientSession", lambda *a, **k: session)

    task = asyncio.create_task(keepalive.keep_alive_loop(interval=0.01))
    await asyncio.sleep(0.06)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # First attempt failed, but the loop kept running and pinged again.
    assert len(session.calls) >= 2
    assert not session.fail_first  # a later call succeeded


async def test_keep_alive_loop_noop_without_url(monkeypatch):
    for var in ("KEEP_ALIVE_URL", "SPACE_HOST", "SPACE_ID"):
        monkeypatch.delenv(var, raising=False)

    import contextlib
    import io
    out = io.StringIO()
    # Loop should return immediately without pinging.
    with contextlib.redirect_stdout(out):
        await keepalive.keep_alive_loop()

    assert "disabled" in out.getvalue().lower()


# ------------------------------------------------------------------ #
#  start_keep_alive()                                                #
# ------------------------------------------------------------------ #


async def test_start_keep_alive_returns_task_when_configured(monkeypatch):
    monkeypatch.setenv("KEEP_ALIVE_URL", "https://example.com/health")

    task = keepalive.start_keep_alive()

    assert task is not None and not task.done()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_start_keep_alive_none_when_disabled(monkeypatch):
    monkeypatch.setenv("KEEP_ALIVE_URL", "https://example.com/health")
    monkeypatch.setenv("KEEP_ALIVE_ENABLED", "false")

    assert keepalive.start_keep_alive() is None


async def test_start_keep_alive_none_without_url(monkeypatch):
    for var in ("KEEP_ALIVE_URL", "SPACE_HOST", "SPACE_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("KEEP_ALIVE_ENABLED", raising=False)

    assert keepalive.start_keep_alive() is None


# ------------------------------------------------------------------ #
#  Standalone runner                                                 #
# ------------------------------------------------------------------ #


def main():
    tests = [
        test_no_url_when_nothing_configured,
        test_explicit_url_used_as_is,
        test_space_host_gets_health_appended,
        test_space_id_derives_hf_subdomain,
        test_explicit_url_wins_over_hf_vars,
        test_keep_alive_interval_default_and_override,
    ]
    async_tests = [
        test_keep_alive_loop_pings_repeatedly,
        test_keep_alive_loop_tolerates_failures,
        test_keep_alive_loop_noop_without_url,
        test_start_keep_alive_returns_task_when_configured,
        test_start_keep_alive_none_when_disabled,
        test_start_keep_alive_none_without_url,
    ]

    # Sync tests need monkeypatch - emulate with a tiny shim so the standalone
    # runner works without pytest fixtures.
    import contextlib
    import unittest.mock as mock

    class _Monkeypatch:
        def __init__(self):
            self._saved = {}

        def setenv(self, key, value):
            self._saved.setdefault(("env", key), (os.environ.get(key), key in os.environ))
            os.environ[key] = value

        def delenv(self, key, raising=False):
            if key in os.environ:
                self._saved.setdefault(("env", key), (os.environ.get(key), True))
                del os.environ[key]
            elif raising:
                raise KeyError(key)

        def setattr(self, obj, name, value):
            self._saved.setdefault(("attr", obj, name), (getattr(obj, name, None), hasattr(obj, name)))
            setattr(obj, name, value)

        def undo(self):
            for (kind, *key), value in self._saved.items():
                if kind == "env":
                    name = key[0]
                    if value[1]:
                        os.environ[name] = value[0]
                    else:
                        os.environ.pop(name, None)
                else:
                    obj, name = key
                    if value[1]:
                        setattr(obj, name, value[0])
                    else:
                        delattr(obj, name)

    async def run_async():
        for fn in async_tests:
            mp = _Monkeypatch()
            await fn(mp)  # async tests use monkeypatch only for env - shim ok
            mp.undo()
            print(f"  ✅ {fn.__name__}")

    def run_sync():
        for fn in tests:
            mp = _Monkeypatch()
            fn(mp)
            mp.undo()
            print(f"  ✅ {fn.__name__}")

    print("🧪 KEEP-ALIVE TEST SUITE")
    run_sync()
    asyncio.run(run_async())
    print("✅ Keep-alive tests passed")


if __name__ == "__main__":
    main()
