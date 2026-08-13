"""
Tests for the TMDb backfill script (scripts/backfill_enrichment.py).

Pins the idempotent backfill loop: only docs missing tmdb_genres are selected,
enrichment maps to the expected $set fields, and the dry-run mode writes
nothing. Uses a fake collection - no live database.
"""

import asyncio
import os
import sys
from types import SimpleNamespace

# Ensure project root is on the path so the scripts package is importable
# when this file is run standalone (python tests/test_backfill_enrichment.py).
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import scripts.backfill_enrichment as script


class FakeMovies:
    """In-memory movies_col stand-in with the operations backfill uses."""

    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, filt, projection=None):
        matches = [d for d in self.docs if "tmdb_genres" not in d]

        class _Cursor:
            def __init__(self):
                self._limit = None

            def limit(self, n):
                self._limit = n
                return self

            async def to_list(self, length=None):
                limited = matches
                if self._limit is not None:
                    limited = limited[: self._limit]
                return limited

        return _Cursor()

    async def count_documents(self, filt):
        return sum(1 for d in self.docs if "tmdb_genres" not in d)

    async def update_one(self, filt, update):
        for d in self.docs:
            if d["_id"] == filt["_id"]:
                d.update(update["$set"])
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)


def _doc(oid, title, year=None, type_="Movie"):
    return {"_id": oid, "title": title, "year": year, "type": type_}


async def test_count_pending_counts_only_unenriched(monkeypatch):
    col = FakeMovies([
        _doc(1, "Avatar"),
        _doc(2, "Matrix", 1999),
        {**_doc(3, "Done"), "tmdb_genres": ["Action"]},
    ])
    assert await script.count_pending(col) == 2


async def test_backfill_enriches_and_maps_fields(monkeypatch):
    col = FakeMovies([_doc(1, "Avatar", 2009), _doc(2, "Matrix", 1999)])

    async def fake_enrich(title, year=None, content_type="Movie"):
        if title == "Avatar":
            return {"poster_url": "https://img/p.jpg", "rating": 8.0,
                    "genres": ["Action"], "overview": "Blue people", "imdb_id": "tt1"}
        return None  # Matrix: no TMDb match

    monkeypatch.setattr("features.tmdb_integration.enrich_title", fake_enrich)

    result = await script.backfill(col, limit=10, delay=0)

    assert result == {"scanned": 2, "enriched": 1, "not_found": 1}
    assert col.docs[0]["tmdb_genres"] == ["Action"]
    assert col.docs[0]["tmdb_rating"] == 8.0
    assert col.docs[0]["imdb_id"] == "tt1"
    # No-match entry is marked with an EMPTY array so it leaves the pending
    # set (never re-selected at the head of the queue on re-runs).
    assert col.docs[1]["tmdb_genres"] == []


async def test_backfill_respects_limit(monkeypatch):
    col = FakeMovies([_doc(i, f"Title {i}") for i in range(5)])

    async def fake_enrich(title, year=None, content_type="Movie"):
        return {"rating": 7.0, "genres": ["Drama"]}

    monkeypatch.setattr("features.tmdb_integration.enrich_title", fake_enrich)
    result = await script.backfill(col, limit=2, delay=0)

    assert result["scanned"] == 2
    assert sum("tmdb_genres" in d for d in col.docs) == 2


async def test_backfill_concurrency_maps_all_fields(monkeypatch):
    """Parallel lookups must still write every result back correctly."""
    col = FakeMovies([_doc(i, f"Title {i}", 2000 + i) for i in range(8)])

    async def fake_enrich(title, year=None, content_type="Movie"):
        await asyncio.sleep(0.005)
        return {"rating": 6.0, "genres": ["Drama"], "poster_url": "p", "overview": "o", "imdb_id": "tt1"}

    monkeypatch.setattr("features.tmdb_integration.enrich_title", fake_enrich)
    result = await script.backfill(col, limit=8, delay=0, concurrency=4)

    assert result == {"scanned": 8, "enriched": 8, "not_found": 0}
    assert all(d.get("tmdb_genres") == ["Drama"] for d in col.docs)


async def test_cli_all_processes_in_slices(monkeypatch):
    """--all must slice through the whole pending set until it empties."""
    import features.database as fdb

    class SliceCol:
        """Docs empty out as they're enriched/marked; find returns <= slice."""

        def __init__(self):
            self.docs = [_doc(i, f"Title {i}", 2000 + i) for i in range(7)]

        def find(self, filt, projection=None):
            pending = [d for d in self.docs if "tmdb_genres" not in d]

            class _Cursor:
                def __init__(self):
                    self._limit = script._SLICE_SIZE

                def limit(self, n):
                    self._limit = n
                    return self

                async def to_list(self, length=None):
                    return pending[: self._limit]

            return _Cursor()

        async def count_documents(self, filt):
            return sum(1 for d in self.docs if "tmdb_genres" not in d)

        async def update_one(self, filt, update):
            for d in self.docs:
                if d["_id"] == filt["_id"]:
                    d.update(update["$set"])

    async def fake_enrich(title, year=None, content_type="Movie"):
        return {"rating": 6.0, "genres": ["Drama"]}

    monkeypatch.setattr(script, "MONGO_URI", "mongodb://u:p@h:27017")
    monkeypatch.setattr(script, "TMDB_API", "key")
    monkeypatch.setattr(script, "MONGO_DB", "CognitoMM")
    monkeypatch.setattr(fdb, "movies_col", SliceCol())
    monkeypatch.setattr("features.tmdb_integration.enrich_title", fake_enrich)

    code = await script.run(["--all", "--concurrency", "2", "--delay", "0"])

    assert code == 0
    assert sum("tmdb_genres" in d for d in fdb.movies_col.docs) == 7  # all done


async def test_cli_dry_run_writes_nothing(monkeypatch):
    """--dry-run must count and exit 0 without calling backfill/update."""
    calls = []

    class FakeCol:
        async def count_documents(self, filt):
            return 3

        def find(self, *a, **k):
            raise AssertionError("find() must not run in dry-run mode")

    monkeypatch.setattr(script, "MONGO_URI", "mongodb://u:p@host:27017")
    monkeypatch.setattr(script, "TMDB_API", "key")
    monkeypatch.setattr(script, "MONGO_DB", "CognitoMM")
    monkeypatch.setattr("features.database.movies_col", FakeCol())

    code = await script.run(["--dry-run"])

    assert code == 0
    assert calls == []


def test_masked_host_redacts_credentials():
    masked = script._masked_host("mongodb+srv://user:secret@cognito.j3knnzh.mongodb.net/")
    assert "secret" not in masked and "user" not in masked
    assert "cognito.j3knnzh.mongodb.net" in masked


def test_script_refuses_without_credentials(monkeypatch):
    async def _run():
        monkeypatch.setattr(script, "MONGO_URI", "")
        monkeypatch.setattr(script, "TMDB_API", "")
        return await script.run([])

    assert asyncio.run(_run()) == 1


# ------------------------------------------------------------------ #
#  Standalone runner                                                 #
# ------------------------------------------------------------------ #


def main():
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


if __name__ == "__main__":
    main()
