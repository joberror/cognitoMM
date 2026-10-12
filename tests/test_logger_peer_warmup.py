"""
Tests for the TelegramLogger peer warm-up (features/logger.py).

Pins the fix for the recurring startup error:
    Failed to send log to Telegram: Telegram says: [403 PEER_ID_INVALID] ...

Root cause: on a fresh session (HF rebuild, wiped .session file) the peer for
the log target is not cached, so send_message() fails until an update from
that chat caches it. Covered here:
- set_client() casts the env string LOG_CHANNEL to int (and None for empty).
- warm_up_peer() resolves the peer via get_chat() and never raises.
- flush() self-heals: a PEER_ID_INVALID send triggers a best-effort re-resolve
  so the NEXT flush succeeds the moment the peer is reachable.
"""

import asyncio
import os
import sys

# Ensure project root is on the path so the features package is importable
# when this file is run standalone (python tests/test_logger_peer_warmup.py).
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from pyrogram.errors import PeerIdInvalid

from features.logger import TelegramLogger

CHANNEL = -1001234567890


class FakeClient:
    """get_chat() records calls; send_message() can be scripted to fail."""

    def __init__(self):
        self.chat_calls = []
        self.sent = []
        self.send_error = None

    async def get_chat(self, chat_id):
        self.chat_calls.append(chat_id)
        return type("Chat", (), {"title": "Log Channel"})()

    async def send_message(self, chat_id, text, **kwargs):
        if self.send_error is not None:
            err = self.send_error
            raise err
        self.sent.append((chat_id, text))


# ------------------------------------------------------------------ #
#  set_client() int cast                                             #
# ------------------------------------------------------------------ #


def test_set_client_casts_string_channel_to_int():
    logger = TelegramLogger()
    logger.set_client(FakeClient(), "-1001234567890")

    assert logger.channel_id == -1001234567890
    assert isinstance(logger.channel_id, int)


def test_set_client_accepts_int_channel():
    logger = TelegramLogger()
    logger.set_client(FakeClient(), -1001234567890)

    assert logger.channel_id == CHANNEL


def test_set_client_empty_channel_becomes_none():
    for value in (None, ""):
        logger = TelegramLogger()
        logger.set_client(FakeClient(), value)
        assert logger.channel_id is None


def test_set_client_malformed_channel_keeps_raw_value():
    """A non-numeric LOG_CHANNEL must not crash startup (fail-fast regression)."""
    logger = TelegramLogger()
    logger.set_client(FakeClient(), "-100abc")
    assert logger.channel_id == "-100abc"


# ------------------------------------------------------------------ #
#  warm_up_peer()                                                    #
# ------------------------------------------------------------------ #


async def test_warm_up_peer_resolves_and_caches():
    client = FakeClient()
    logger = TelegramLogger()
    logger.set_client(client, str(CHANNEL))

    ok = await logger.warm_up_peer()

    assert ok is True
    assert client.chat_calls == [CHANNEL]


async def test_warm_up_peer_without_channel_is_noop():
    logger = TelegramLogger()
    logger.set_client(FakeClient(), None)

    assert await logger.warm_up_peer() is False


async def test_warm_up_peer_never_raises_on_failure():
    client = FakeClient()

    async def boom(chat_id):
        raise PeerIdInvalid("peer not cached yet")

    client.get_chat = boom
    logger = TelegramLogger()
    logger.set_client(client, str(CHANNEL))

    assert await logger.warm_up_peer() is False


# ------------------------------------------------------------------ #
#  flush() PEER_ID_INVALID self-heal                                 #
# ------------------------------------------------------------------ #


async def test_flush_self_heals_on_peer_id_invalid():
    """First send fails with PEER_ID_INVALID -> re-resolve; next flush sends."""
    client = FakeClient()
    client.send_error = PeerIdInvalid("The provided peer id is invalid")

    logger = TelegramLogger()
    logger.set_client(client, str(CHANNEL))
    logger._add_to_buffer("line one")

    # First flush: send fails, peer re-resolved, no crash, buffer drained.
    await logger.flush()
    assert client.sent == []                       # send failed
    assert client.chat_calls == [CHANNEL]          # get_chat was re-attempted

    # The peer is now resolvable -> next flush succeeds.
    client.send_error = None
    logger._add_to_buffer("line two")
    await logger.flush()
    assert client.sent == [(CHANNEL, "line two")]


async def test_flush_other_errors_do_not_re_resolve():
    """Non-PEER_ID_INVALID errors keep the current behavior (no re-resolve)."""

    class SomeError(Exception):
        pass

    client = FakeClient()
    client.send_error = SomeError("flood or whatever")

    logger = TelegramLogger()
    logger.set_client(client, str(CHANNEL))
    logger._add_to_buffer("line one")

    await logger.flush()

    assert client.sent == []
    assert client.chat_calls == []  # no get_chat re-attempt for other errors


# ------------------------------------------------------------------ #
#  Standalone runner                                                 #
# ------------------------------------------------------------------ #


def main():
    async def run_async():
        await test_warm_up_peer_resolves_and_caches()
        await test_warm_up_peer_without_channel_is_noop()
        await test_warm_up_peer_never_raises_on_failure()
        await test_flush_self_heals_on_peer_id_invalid()
        await test_flush_other_errors_do_not_re_resolve()

    print("🧪 LOGGER PEER WARM-UP TEST SUITE")
    test_set_client_casts_string_channel_to_int()
    test_set_client_accepts_int_channel()
    test_set_client_empty_channel_becomes_none()
    test_set_client_malformed_channel_keeps_raw_value()
    asyncio.run(run_async())
    print("✅ Logger peer warm-up tests passed")


if __name__ == "__main__":
    main()
