#!/usr/bin/env python3
"""
Test: pyroblack deprecated-API cleanup pins

Pins the two deprecated-API migrations from the pyroblack deprecation sweep
(see the git history for the link_preview_options migration, which this
extends):

1. features/commands.py cmd_index_channel() must read forwarded-message data
   from the modern ``Message.forward_origin`` object instead of the
   deprecated ``forward_from_chat`` / ``forward_from_message_id`` properties.

   The regression pin is structural: the fake forwarded message exposes ONLY
   ``forward_origin`` and has NO ``forward_from_chat`` attribute. If the code
   ever reverts to the deprecated properties, the fake raises AttributeError
   and the confirmation reply never happens, so the test fails.

2. features/search.py inline_handler() must build inline results with the
   modern ``thumbnail_url`` kwarg instead of the deprecated ``thumb_url``.

   A spy constructor replaces InlineQueryResultArticle and records every
   kwarg call, so reverting to ``thumb_url`` fails the assertion.

3. The link_preview_options migration (14 call sites across logger.py,
   search.py, callbacks.py, commands.py): every send/edit path that once
   passed ``disable_web_page_preview=True`` must now pass
   ``link_preview_options=LinkPreviewOptions(is_disabled=True)``. The
   receiver methods (reply_text / edit_text / edit_message_text /
   send_message) are spied on via recorder fakes, and every recorded call is
   asserted to carry the modern kwarg. A source-level scan additionally pins
   the exact per-file count of all 14 sites, so a partial revert anywhere is
   caught even if a flow is not driven.

All handlers run against injected fakes - no real DB or Telegram access.
"""

import asyncio
import sys
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

# Ensure project root on path so `features` is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from features import callbacks, commands, search
from features.logger import TelegramLogger
from pyrogram.enums import ChatType
from pyrogram.types import LinkPreviewOptions


# ---------------------------
# Fakes: cmd_index_channel
# ---------------------------

class FakeSentMsg:
    """Returned by message.reply_text(); records edit_text() calls."""

    def __init__(self):
        self.edits = []

    async def delete(self):
        pass

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))
        return self


class FakeUserMsg:
    """The command Message (an admin typing /index_channel)."""

    def __init__(self, user_id=42, chat_id=1000):
        self.from_user = SimpleNamespace(id=user_id, first_name="Test")
        self.chat = SimpleNamespace(id=chat_id)
        self.replies = []
        self.sent = []  # FakeSentMsg objects returned by reply_text (edit recorder)

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))
        sent = FakeSentMsg()
        self.sent.append(sent)
        return sent


class FakeIndexClient:
    """get_chat() returns the indexed channel."""

    def __init__(self, chat=None):
        self.chat = chat or SimpleNamespace(type=ChatType.CHANNEL, title="Test Channel")

    async def get_chat(self, chat_id):
        return self.chat


def channel_forward_msg():
    """Forwarded channel post exposing ONLY forward_origin.

    Deliberately has no forward_from_chat / forward_from_message_id
    attributes - reverting the code to the deprecated properties raises
    AttributeError here and the pinning test fails.
    """
    origin = SimpleNamespace(
        chat=SimpleNamespace(type=ChatType.CHANNEL, username=None, id=-100123),
        message_id=8888,
    )
    return SimpleNamespace(text=None, forward_origin=origin)


def user_forward_msg():
    """Forwarded message from a USER (forward_origin has no .chat)."""
    origin = SimpleNamespace(sender_user=SimpleNamespace(id=7), chat=None)
    return SimpleNamespace(text=None, forward_origin=origin)


def non_channel_chat_forward_msg():
    """Forwarded from a supergroup - forward_origin.chat exists but is not a channel."""
    origin = SimpleNamespace(
        chat=SimpleNamespace(type=ChatType.SUPERGROUP, username=None, id=-99),
        message_id=1,
    )
    return SimpleNamespace(text=None, forward_origin=origin)


def plain_text_msg():
    """A plain reply that is neither a link nor a forward."""
    return SimpleNamespace(text="not a link, not a forward")


async def run_index_channel(response, skip_text="5", client=None):
    """Drive cmd_index_channel with canned user input and admin rights."""
    user_msg = FakeUserMsg()
    skip_msg = SimpleNamespace(text=skip_text)
    with patch.object(commands, "is_admin", AsyncMock(return_value=True)), \
            patch.object(commands, "wait_for_user_input",
                         AsyncMock(side_effect=[response, skip_msg])), \
            patch.object(commands, "indexing_lock", asyncio.Lock()):
        await commands.cmd_index_channel(client or FakeIndexClient(), user_msg)
    return user_msg


# ---------------------------
# cmd_index_channel tests
# ---------------------------

async def test_index_channel_extracts_channel_from_forward_origin():
    """
    THE regression pin: a forwarded channel post is read via forward_origin
    and produces the correct confirmation (chat_id, message_id, skip).
    """
    msg = await run_index_channel(channel_forward_msg())

    conf = [t for t, _ in msg.replies if t.startswith("🎬 **Index Channel Confirmation**")]
    assert conf, f"expected a confirmation reply, got: {[t[:40] for t, _ in msg.replies]}"
    text, kwargs = next(r for r in msg.replies if r[0].startswith("🎬 **Index Channel Confirmation**"))

    assert "`-100123`" in text, "chat_id must come from forward_origin.chat"
    assert "`8888`" in text, "message_id must come from forward_origin.message_id"
    assert "`5`" in text, "skip must be parsed from the follow-up input"

    markup = kwargs["reply_markup"]
    yes = [b for row in markup.inline_keyboard for b in row
           if getattr(b, "callback_data", None) == "index#yes#-100123#8888#5"]
    assert yes, "YES button must embed chat_id, message_id and skip"

    # No error paths may have been hit
    assert not any("not a forwarded message" in t for t, _ in msg.replies)
    assert not any(t.startswith("❌ Error:") for t, _ in msg.replies)


async def test_index_channel_rejects_non_forwarded():
    """A plain reply (not a link, no forward_origin) is rejected."""
    msg = await run_index_channel(plain_text_msg())

    assert any("❌ This is not a forwarded message or valid link." in t for t, _ in msg.replies)
    assert not any(t.startswith("🎬 **Index Channel Confirmation**") for t, _ in msg.replies)


async def test_index_channel_rejects_user_forward():
    """A forward from a USER (no forward_origin.chat) is rejected."""
    msg = await run_index_channel(user_forward_msg())

    assert any("❌ This is not a forwarded message or valid link." in t for t, _ in msg.replies)
    assert not any(t.startswith("🎬 **Index Channel Confirmation**") for t, _ in msg.replies)


async def test_index_channel_rejects_non_channel_chat_forward():
    """A forward from a supergroup (forward_origin.chat not a CHANNEL) is rejected."""
    msg = await run_index_channel(non_channel_chat_forward_msg())

    assert any("❌ This is not a forwarded message or valid link." in t for t, _ in msg.replies)
    assert not any(t.startswith("🎬 **Index Channel Confirmation**") for t, _ in msg.replies)


async def test_index_channel_message_link_path_still_works():
    """The t.me link branch still takes precedence over the forward branch."""
    link_msg = SimpleNamespace(text="https://t.me/c/2465144431/13617", forward_origin=None)
    msg = await run_index_channel(link_msg)

    conf = [t for t, _ in msg.replies if t.startswith("🎬 **Index Channel Confirmation**")]
    assert conf, f"expected a confirmation reply, got: {[t[:40] for t, _ in msg.replies]}"
    text = conf[0]
    assert "`-1002465144431`" in text, "chat_id must be derived from the link"
    assert "`13617`" in text, "message_id must come from the link"


# ---------------------------
# Fakes: search inline_handler
# ---------------------------

class FakeCursor:
    """find() result with limit() + async to_list()."""

    def __init__(self, docs):
        self._docs = docs

    def limit(self, n):
        return self

    async def to_list(self, length=None):
        return self._docs


class FakeInlineMoviesCol:
    """One exact match plus one fuzzy match (different _id, high partial_ratio
    against the query) so BOTH InlineQueryResultArticle construction sites in
    inline_handler (exact + fuzzy) are exercised."""

    def find(self, filter_query, projection=None):
        if filter_query:
            # exact-title query -> one match
            return FakeCursor([{
                "_id": "m1",
                "title": "The Matrix",
                "year": 1999,
                "quality": "1080p",
                "channel_title": "Movies",
            }])
        # fuzzy {} scan -> one additional match (skipped by the exact set)
        return FakeCursor([{
            "_id": "m2",
            "title": "The Matrix Reloaded",
            "year": 2003,
            "quality": "720p",
            "channel_title": "Movies",
        }])


class SpyArticle:
    """Constructor spy: records every InlineQueryResultArticle(...) kwarg call."""

    instances = []

    def __init__(self, **kwargs):
        SpyArticle.instances.append(kwargs)


class FakeInlineQuery:
    query = "matrix"
    id = "iq-1"

    class from_user:
        id = 42


class FakeAnswerClient:
    def __init__(self):
        self.inline_answers = []

    async def answer_inline_query(self, inline_query_id, results, **kwargs):
        self.inline_answers.append((inline_query_id, results, kwargs))


# ---------------------------
# search inline_handler test
# ---------------------------

async def test_inline_handler_uses_thumbnail_url():
    """
    THE regression pin: inline results must be built with the modern
    thumbnail_url kwarg (never the deprecated thumb_url).
    """
    SpyArticle.instances.clear()
    client = FakeAnswerClient()

    with patch("features.database.movies_col", FakeInlineMoviesCol()), \
            patch("features.database.users_col", AsyncMock()), \
            patch("pyrogram.types.InlineQueryResultArticle", SpyArticle):
        await search.inline_handler(client, FakeInlineQuery())

    assert len(SpyArticle.instances) == 2, \
        "both the exact-match and fuzzy-match article sites must be exercised"
    deprecated_thumb_keys = {"thumb_url", "thumb_width", "thumb_height", "thumb_mime_type"}
    for kwargs in SpyArticle.instances:
        assert "thumbnail_url" in kwargs, "must use the modern thumbnail_url kwarg"
        overlap = deprecated_thumb_keys.intersection(kwargs)
        assert not overlap, f"deprecated thumbnail kwarg(s) used: {sorted(overlap)}"

    assert client.inline_answers, "expected answer_inline_query to be called"
    inline_id, _results, kwargs = client.inline_answers[0]
    assert inline_id == "iq-1"
    assert kwargs.get("cache_time") == 300


# ---------------------------
# Fakes: link_preview_options pins
# ---------------------------

class FakeSortedCursor:
    """find() cursor with sort() + async to_list() (used by /recent)."""

    def __init__(self, docs):
        self._docs = docs

    def sort(self, *args, **kwargs):
        return self

    async def to_list(self, length=None):
        return self._docs


class FakeCallbackMsg:
    """callback_query.message - records edit_text() calls."""

    def __init__(self):
        self.edits = []

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))
        return self


class FakeCallbackQuery:
    """callback_query - records answer() and edit_message_text() calls."""

    def __init__(self, data, user_id=42):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeCallbackMsg()
        self.answers = []
        self.edits = []

    async def answer(self, text, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


class FakeLogClient:
    """client for TelegramLogger - records send_message() kwargs."""

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(kwargs)


def _assert_lpo_value(kwargs):
    """Pin the VALUE, not just the key: previews must actually be disabled."""
    lpo = kwargs["link_preview_options"]
    assert isinstance(lpo, LinkPreviewOptions), \
        f"link_preview_options is not a LinkPreviewOptions: {lpo!r}"
    assert lpo.is_disabled is True, \
        f"link_preview_options must disable link previews: {lpo!r}"


def _assert_link_preview_only(recorded):
    """Every recorded (text, kwargs) send/edit call must use the modern kwarg
    with previews actually disabled."""
    assert recorded, "expected at least one send/edit call"
    for text, kwargs in recorded:
        assert "link_preview_options" in kwargs, \
            f"missing link_preview_options kwarg on: {text[:60]!r} -> {kwargs}"
        assert "disable_web_page_preview" not in kwargs, \
            f"deprecated disable_web_page_preview used on: {text[:60]!r}"
        _assert_lpo_value(kwargs)


# ---------------------------
# link_preview_options pins: commands.py
# ---------------------------

async def test_cmd_start_short_terms_uses_link_preview_options():
    """cmd_start single-message terms path (commands.py:314)."""
    msg = FakeUserMsg()
    with patch.object(commands, "check_banned", AsyncMock(return_value=False)), \
            patch.object(commands, "has_accepted_terms", AsyncMock(return_value=False)), \
            patch.object(commands, "load_terms_and_privacy",
                         AsyncMock(return_value="Short terms.")), \
            patch.object(commands.users_col, "update_one", AsyncMock()):
        await commands.cmd_start(None, msg)

    _assert_link_preview_only(msg.replies)


async def test_cmd_start_long_terms_chunks_use_link_preview_options():
    """cmd_start chunked terms path (commands.py:323, 333, 347)."""
    msg = FakeUserMsg()
    long_terms = "Y" * 9000  # > 2 * 4000 so the chunk loop runs at least once
    with patch.object(commands, "check_banned", AsyncMock(return_value=False)), \
            patch.object(commands, "has_accepted_terms", AsyncMock(return_value=False)), \
            patch.object(commands, "load_terms_and_privacy",
                         AsyncMock(return_value=long_terms)), \
            patch.object(commands.users_col, "update_one", AsyncMock()):
        await commands.cmd_start(None, msg)

    # first chunk + loop chunk + final chunk-with-buttons = 3 terms replies
    term_replies = [r for r in msg.replies if r[0] and not r[0].startswith("❌")]
    assert len(term_replies) == 3, f"expected 3 chunked replies, got {len(term_replies)}"
    _assert_link_preview_only(term_replies)


async def test_cmd_my_history_uses_link_preview_options():
    """cmd_my_history (commands.py:481)."""
    msg = FakeUserMsg()
    history = [{"q": "matrix", "ts": datetime.now(timezone.utc)}]
    with patch.object(commands.users_col, "find_one",
                      AsyncMock(return_value={"search_history": history})):
        await commands.cmd_my_history(None, msg)

    _assert_link_preview_only(msg.replies)


async def test_cmd_recent_uses_link_preview_options():
    """cmd_recent (commands.py:607)."""
    msg = FakeUserMsg()
    now = datetime.now(timezone.utc)
    docs = [
        {"title": "Movie One", "type": "Movie", "quality": "1080p",
         "year": 2020, "indexed_at": now, "_id": "m1"},
        {"title": "Series One", "type": "Series", "season": 1, "episode": 2,
         "year": 2021, "indexed_at": now, "_id": "s1"},
    ]
    with patch.object(commands, "is_feature_premium_only",
                      AsyncMock(return_value=False)), \
            patch.object(commands.movies_col, "find_one",
                         AsyncMock(return_value={"_id": "latest", "indexed_at": now})), \
            patch.object(commands.movies_col, "find",
                         Mock(return_value=FakeSortedCursor(docs))), \
            patch.object(commands, "log_action", AsyncMock()):
        await commands.cmd_recent(None, msg)

    _assert_link_preview_only(msg.replies)


async def test_cmd_trending_uses_link_preview_options():
    """cmd_trending edit_text on the loading message (commands.py:668)."""
    msg = FakeUserMsg()
    with patch("features.tmdb_integration.get_trending_movies",
               AsyncMock(return_value=[{"id": 1, "title": "T1"}])), \
            patch("features.tmdb_integration.format_trending_list",
                  Mock(return_value="content")):
        await commands.cmd_trending(None, msg)

    _assert_link_preview_only(_sent_msgs(msg))


async def test_cmd_indexing_stats_uses_link_preview_options():
    """cmd_indexing_stats (commands.py:1275)."""
    msg = FakeUserMsg()
    with patch.object(commands, "is_admin", AsyncMock(return_value=True)), \
            patch.object(commands, "log_action", AsyncMock()):
        await commands.cmd_indexing_stats(None, msg)

    _assert_link_preview_only(msg.replies)


async def test_cmd_stat_uses_link_preview_options():
    """cmd_stat edit_text on the loading message (commands.py:2356)."""
    msg = FakeUserMsg()
    with patch.object(commands, "is_admin", AsyncMock(return_value=True)), \
            patch.object(commands, "collect_comprehensive_stats",
                         AsyncMock(return_value={"total_users": 1, "total_content": 1})), \
            patch.object(commands, "format_stats_output",
                         Mock(return_value="stats out")), \
            patch.object(commands, "bulk_downloads", {}), \
            patch.object(commands, "log_action", AsyncMock()):
        await commands.cmd_stat(None, msg)

    _assert_link_preview_only(_sent_msgs(msg))


async def test_cmd_quickstat_uses_link_preview_options():
    """cmd_quickstat edit_text on the loading message (commands.py:2409)."""
    msg = FakeUserMsg()
    with patch.object(commands, "is_admin", AsyncMock(return_value=True)), \
            patch.object(commands, "collect_quick_stats",
                         AsyncMock(return_value={"total_users": 1})), \
            patch.object(commands, "format_quick_stats_output",
                         Mock(return_value="quick out")), \
            patch.object(commands, "log_action", AsyncMock()):
        await commands.cmd_quickstat(None, msg)

    _assert_link_preview_only(_sent_msgs(msg))


def _sent_msgs(msg):
    """Flatten (text, kwargs) edits recorded on every FakeSentMsg the message
    created via reply_text (covers edit_text calls on loading messages)."""
    collected = []
    for sent in getattr(msg, "sent", []):
        collected.extend(sent.edits)
    return collected


# ---------------------------
# link_preview_options pins: search.py / logger.py / callbacks.py
# ---------------------------

async def test_send_search_results_uses_link_preview_options():
    """send_search_results reply (search.py:256)."""
    msg = FakeUserMsg()
    results = [
        {"title": "The Matrix", "year": 1999, "quality": "1080p",
         "channel_id": -1001, "message_id": 11, "file_size": 1000},
        {"title": "The Matrix Reloaded", "year": 2003, "quality": "720p",
         "channel_id": -1001, "message_id": 12, "file_size": 2000},
        {"title": "The Matrix Revolutions", "year": 2003, "quality": "1080p",
         "channel_id": -1001, "message_id": 13, "file_size": 3000},
    ]
    with patch("features.config.bulk_downloads", {}), \
            patch("features.premium_management.is_feature_premium_only",
                  AsyncMock(return_value=False)):
        await search.send_search_results(None, msg, results, "matrix")

    _assert_link_preview_only(msg.replies)


async def test_telegram_logger_uses_link_preview_options():
    """TelegramLogger send_message (logger.py:133)."""
    client = FakeLogClient()
    logger = TelegramLogger(client=None, channel_id=None)
    logger.set_client(client, -1001234567)
    logger.log("Test log message")
    await logger.flush()

    assert client.sent, "expected send_message to be called"
    for kwargs in client.sent:
        assert "link_preview_options" in kwargs, f"missing kwarg in: {kwargs}"
        assert "disable_web_page_preview" not in kwargs
        _assert_lpo_value(kwargs)


async def test_search_pagination_callback_uses_link_preview_options():
    """Search pagination callback edit_message_text (callbacks.py:363)."""
    cbq = FakeCallbackQuery(data="page:abc123:2")
    cached = {
        "abc123": {
            "user_id": 42,
            "query": "matrix",
            "results": [
                {"title": "The Matrix", "year": 1999, "quality": "1080p",
                 "channel_id": -1001, "message_id": 11, "file_size": 1000},
                {"title": "The Matrix Reloaded", "year": 2003,
                 "channel_id": -1001, "message_id": 12, "file_size": 2000},
            ],
        }
    }
    # NOTE: page: rendering now lives in search.py (render_search_page ->
    # build_search_keyboard), which imports is_feature_premium_only fresh
    # from premium_management - so patch the real source, not callbacks.
    with patch.object(callbacks, "bulk_downloads", cached), \
            patch("features.premium_management.is_feature_premium_only",
                  AsyncMock(return_value=False)), \
            patch.object(callbacks, "has_accepted_terms",
                         AsyncMock(return_value=True)):
        await callbacks.callback_handler(None, cbq)

    _assert_link_preview_only(cbq.edits)


async def test_trending_callback_uses_link_preview_options():
    """Trending callback edit_text on callback_query.message (callbacks.py:1368)."""
    cbq = FakeCallbackQuery(data="trending:movies")
    with patch("features.tmdb_integration.get_trending_movies",
               AsyncMock(return_value=[{"id": 1}])), \
            patch("features.tmdb_integration.format_trending_list",
                  Mock(return_value="content")), \
            patch.object(callbacks, "has_accepted_terms",
                         AsyncMock(return_value=True)):
        await callbacks.callback_handler(None, cbq)

    _assert_link_preview_only(cbq.message.edits)


def test_link_preview_options_migration_fully_applied():
    """Source-level scan: pins ALL link_preview_options call sites (18).

    The exact per-file counts are the pin: adding a site or refactoring the
    kwarg construction (e.g. into a helper) fails until the counts here are
    deliberately updated - do NOT loosen the matcher to "fix" it. (Counts
    grew from 14 to 18 when the /random, /genres, /logs commands were added;
    the pick-filter refactor then moved the page:/choose: renders from
    callbacks.py into search.py, shifting 2 sites: search 1->3, callbacks 3->1.)
    """
    expected = {
        "features/logger.py": 1,
        "features/search.py": 3,
        "features/callbacks.py": 1,
        "features/commands.py": 13,
    }
    total = 0
    for rel, count in expected.items():
        with open(os.path.join(ROOT_DIR, rel), encoding="utf-8") as f:
            src = f.read()
        assert "disable_web_page_preview" not in src, \
            f"{rel} still uses the deprecated disable_web_page_preview kwarg"
        found = src.count("link_preview_options=LinkPreviewOptions(is_disabled=True)")
        assert found == count, \
            f"{rel}: expected {count} link_preview_options sites, found {found}"
        total += found
    assert total == 18, f"expected 18 total sites, found {total}"


# ---------------------------
# Standalone runner
# ---------------------------

def main():
    async def run_all():
        await test_index_channel_extracts_channel_from_forward_origin()
        await test_index_channel_rejects_non_forwarded()
        await test_index_channel_rejects_user_forward()
        await test_index_channel_rejects_non_channel_chat_forward()
        await test_index_channel_message_link_path_still_works()
        await test_inline_handler_uses_thumbnail_url()
        # link_preview_options pins
        await test_cmd_start_short_terms_uses_link_preview_options()
        await test_cmd_start_long_terms_chunks_use_link_preview_options()
        await test_cmd_my_history_uses_link_preview_options()
        await test_cmd_recent_uses_link_preview_options()
        await test_cmd_trending_uses_link_preview_options()
        await test_cmd_indexing_stats_uses_link_preview_options()
        await test_cmd_stat_uses_link_preview_options()
        await test_cmd_quickstat_uses_link_preview_options()
        await test_send_search_results_uses_link_preview_options()
        await test_telegram_logger_uses_link_preview_options()
        await test_search_pagination_callback_uses_link_preview_options()
        await test_trending_callback_uses_link_preview_options()

    asyncio.run(run_all())
    test_link_preview_options_migration_fully_applied()
    print("✅ pyroblack API cleanup tests passed")
    print("   - cmd_index_channel reads forward_origin (not forward_from_chat)")
    print("   - inline results use thumbnail_url (not thumb_url)")
    print("   - all 14 link_preview_options call sites use the modern kwarg")


if __name__ == "__main__":
    main()
