#!/usr/bin/env python3
"""
Test: the movies title text index sets language_override.

MongoDB text indexes read a per-document stemming language from a field named
"language" unless ``language_override`` points elsewhere. The movies
collection stores ``language`` as the release's AUDIO language (sometimes a
non-string in legacy docs), which aborted the build with:

    found language override field in document with non-string type (code 17261)

This pins that ensure_indexes() creates the text index with
``language_override`` = TEXT_LANGUAGE_OVERRIDE and ``default_language="none"``,
and that the other (unique) indexes are still created. No real MongoDB needed.
"""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import features.database as database

COLLECTION_NAMES = [
    "movies_col", "users_col", "channels_col", "settings_col", "logs_col",
    "requests_col", "user_request_limits_col", "premium_users_col",
    "premium_features_col", "premium_payments_col", "broadcasts_col",
]


class RecordingCol:
    """Records create_index(spec, **kwargs) calls."""

    def __init__(self):
        self.calls = []

    async def create_index(self, spec, **kwargs):
        self.calls.append((spec, dict(kwargs)))
        return "ok"


def run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        loop = asyncio.new_event_loop()
    return loop.run_until_complete(coro)


def _with_fakes(fn):
    saved_empty = database.MONGO_URI_WAS_EMPTY
    saved_mongo = database.mongo
    saved_cols = {n: getattr(database, n) for n in COLLECTION_NAMES}
    rec = RecordingCol()
    database.MONGO_URI_WAS_EMPTY = False
    database.mongo = SimpleNamespace(
        admin=SimpleNamespace(command=AsyncMock(return_value={"ok": 1})))
    for n in COLLECTION_NAMES:
        setattr(database, n, rec)
    try:
        fn(rec)
    finally:
        database.MONGO_URI_WAS_EMPTY = saved_empty
        database.mongo = saved_mongo
        for n, v in saved_cols.items():
            setattr(database, n, v)


def test_text_index_uses_language_override():
    def check(rec):
        run(database.ensure_indexes())
        text_calls = [c for c in rec.calls if c[0] == [("title", "text")]]
        assert len(text_calls) == 1, rec.calls
        kwargs = text_calls[0][1]
        assert kwargs.get("language_override") == database.TEXT_LANGUAGE_OVERRIDE, kwargs
        assert kwargs.get("language_override") != "language", kwargs
        assert kwargs.get("default_language") == "none", kwargs

    _with_fakes(check)


def test_unique_indexes_still_created():
    def check(rec):
        run(database.ensure_indexes())
        by_spec = {tuple(map(tuple, spec)): kwargs for spec, kwargs in rec.calls}
        # user_id index is unique; the text index is not.
        user_index = [k for k in by_spec if k == (("user_id", 1),)]
        assert user_index, by_spec
        assert by_spec[user_index[0]].get("unique") is True, by_spec
        text = [k for k in by_spec if k == (("title", "text"),)]
        assert "unique" not in by_spec[text[0]], by_spec

    _with_fakes(check)


_TESTS = [
    test_text_index_uses_language_override,
    test_unique_indexes_still_created,
]


def main() -> int:
    failures = 0
    for fn in _TESTS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
            import traceback
            traceback.print_exc()
    print(f"\n{len(_TESTS) - failures}/{len(_TESTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
