"""
Regression tests for the CI test-collection crash:

    pymongo.errors.ConfigurationError: Empty host (or extra comma in host list)

CI runs ``make test`` (pytest) with no MONGO_URI env var and no .env file, so
features/config.py leaves MONGO_URI as "". features/database.py used to pass
that empty string straight into AsyncIOMotorClient(...), which raises
ConfigurationError at module IMPORT time -> every test module importing
features.* failed during collection (16 collection errors).

The fix: database.py resolves an empty MONGO_URI to a localhost stand-in so the
module always imports, and records MONGO_URI_WAS_EMPTY so ensure_indexes()
fails fast with a clear message at bot startup instead of silently probing
localhost.
"""

import os
import sys

import pytest

# Ensure project root is on the path so the features package is importable
# when this file is run standalone (python tests/test_database_import_guard.py).
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from motor.motor_asyncio import AsyncIOMotorClient

import features.database as database
from features.database import MONGO_URI_WAS_EMPTY, resolve_mongo_uri


def test_resolve_mongo_uri_empty_falls_back_to_localhost():
    assert resolve_mongo_uri("") == "mongodb://localhost:27017"


def test_resolve_mongo_uri_none_falls_back_to_localhost():
    assert resolve_mongo_uri(None) == "mongodb://localhost:27017"


def test_resolve_mongo_uri_blank_falls_back_to_localhost():
    assert resolve_mongo_uri("   ") == "mongodb://localhost:27017"


def test_resolve_mongo_uri_strips_surrounding_whitespace():
    uri = "mongodb+srv://user:pass@cluster.example.net/db"
    assert resolve_mongo_uri(f"  {uri}  ") == uri


def test_resolve_mongo_uri_passes_through_real_uri():
    uri = "mongodb+srv://user:pass@cluster.example.net/db"
    assert resolve_mongo_uri(uri) == uri


def test_empty_uri_no_longer_crashes_client_construction():
    """Pin the CI regression: AsyncIOMotorClient('') raises ConfigurationError,
    while the resolved stand-in constructs fine."""
    client = AsyncIOMotorClient(resolve_mongo_uri(""))
    assert client is not None
    client.close()


def test_was_empty_flag_tracks_config_uri():
    """The flag mirrors config's MONGO_URI, so the fast-fail below only fires
    when the bot genuinely has no database configured."""
    from features import config

    assert isinstance(MONGO_URI_WAS_EMPTY, bool)
    assert MONGO_URI_WAS_EMPTY == (not bool(config.MONGO_URI))


async def test_ensure_indexes_fails_fast_when_uri_missing(monkeypatch):
    """Bot startup must fail loudly (never probe localhost) without MONGO_URI."""
    monkeypatch.setattr(database, "MONGO_URI_WAS_EMPTY", True)

    with pytest.raises(RuntimeError, match="MONGO_URI is not set"):
        await database.ensure_indexes()
