#!/usr/bin/env python3
"""
Test: structured /search filters (year / quality / type).

Pins cluster-1 search upgrade (features/search.py):

1. parse_search_query splits trailing "<year> <quality> <type>" tokens plus
   explicit ``year:/quality:/type:`` and "(year)" forms, without eating
   title words (only trailing tokens are stripped; "/search 2012" stays a
   title).
2. perform_search pushes facets server-side (year $in [int, str], quality
   case-insensitive exact, type movie/series regex), escapes the title
   regex (old code passed raw user input as $regex), tries a $text fast
   path with graceful fallback, and fuzzy-matches against the parsed title
   over a facet-narrowed candidate set with O(1) dedup.
3. build_search_page renders an applied-filters header line and pagination
   preserves it via the stored search state.

All DB access runs against injected fakes - no real MongoDB needed.
"""

import asyncio
import os
import re
import sys

# Ensure project root on path so `features` is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import features.search as search_mod
from features.search import (
    build_search_page,
    format_active_filters,
    parse_search_query,
    perform_search,
)


# ------------------------------------------------------------------ #
# Fakes                                                               #
# ------------------------------------------------------------------ #

class FakeCursor:
    """Minimal motor-cursor stand-in: sort/limit/to_list + async iteration."""

    def __init__(self, docs, col=None, filt=None):
        self._docs = list(docs)
        self.col = col
        self.filt = filt

    def sort(self, *args, **kwargs):
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length=None):
        if length is not None:
            return self._docs[:length]
        return list(self._docs)

    def __aiter__(self):
        async def _gen():
            for d in self._docs:
                yield d
        return _gen()


class FakeMoviesCol:
    """Records find() filters; serves pre-set docs per call (FIFO)."""

    def __init__(self, doc_queues=None):
        # doc_queues: list of doc-lists, one per find() call in order.
        self.doc_queues = list(doc_queues or [])
        self.find_calls = []
        self.raise_on_text = True  # simulate DBs without the text index

    def find(self, filt=None, projection=None):
        self.find_calls.append(dict(filt or {}))
        if filt and "$text" in filt and self.raise_on_text:
            raise RuntimeError("no text index")
        docs = self.doc_queues.pop(0) if self.doc_queues else []
        return FakeCursor(docs, col=self, filt=filt)


def run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        loop = asyncio.new_event_loop()
    return loop.run_until_complete(coro)


# ------------------------------------------------------------------ #
# 1. Query parsing                                                    #
# ------------------------------------------------------------------ #

def test_parse_basic_title_only():
    p = parse_search_query("Dune")
    assert p == {"title": "Dune", "year": None, "quality": None, "type": None,
                 "language": None, "subtitles": None, "audio": None,
                 "hdr": None, "raw": "Dune"}, p


def test_parse_trailing_facets():
    p = parse_search_query("Dune 2021 1080p movie")
    assert p["title"] == "Dune", p
    assert p["year"] == 2021, p
    assert p["quality"] == "1080p", p
    assert p["type"] == "Movie", p


def test_parse_series_and_4k_alias():
    p = parse_search_query("Breaking Bad 4k series")
    assert p["title"] == "Breaking Bad", p
    assert p["quality"] == "2160p", p
    assert p["type"] == "Series", p


def test_parse_paren_year_and_kv():
    p = parse_search_query("Dune (2021)")
    assert p["title"] == "Dune" and p["year"] == 2021, p
    p = parse_search_query("year:2019 quality:720p type:show Dune")
    assert p["title"] == "Dune", p
    assert (p["year"], p["quality"], p["type"]) == (2019, "720p", "Series"), p


def test_parse_title_words_preserved():
    # "Show" inside the title must survive; only trailing filters strip.
    p = parse_search_query("The Show")
    assert p["title"] == "The Show" and p["type"] is None, p
    # ...while a real single-word title + filter still strips.
    p = parse_search_query("Dune series")
    assert p["title"] == "Dune" and p["type"] == "Series", p
    # Lone year-like token stays a title (film literally called "2012").
    p = parse_search_query("2012")
    assert p["title"] == "2012" and p["year"] is None, p


def test_format_active_filters():
    assert format_active_filters(year=2021, quality="1080p", type_="Movie") == \
        "year=2021 · 1080p · Movie"
    assert format_active_filters() == ""


# ------------------------------------------------------------------ #
# 2. perform_search pushes facets + escapes regex                     #
# ------------------------------------------------------------------ #

def test_perform_search_applies_facets_server_side():
    docs = [{"_id": 1, "title": "Dune", "year": 2021, "quality": "1080p", "type": "Movie"}]
    # find() calls in order: $text attempt (raises: no text index on old DBs,
    # queue untouched), exact stage (serves the doc), fuzzy scan (empty -
    # exact already hit... actually 1 hit < 50 so fuzzy still runs).
    fake = FakeMoviesCol(doc_queues=[list(docs), []])
    search_mod.movies_col = fake
    out = run(perform_search("Dune 2021 1080p movie"))
    assert out["title"] == "Dune", out
    assert out["filters"] == {"year": 2021, "quality": "1080p", "type": "Movie",
                              "language": None, "subtitles": None,
                              "audio": None, "hdr": None}, out
    assert [d["title"] for d in out["results"]] == ["Dune"]
    # The exact-stage filter must carry all three facets server-side.
    exact_call = fake.find_calls[1]
    assert exact_call.get("year") == {"$in": [2021, "2021"]}, exact_call
    assert exact_call.get("quality") == {"$regex": "^1080p$", "$options": "i"}, exact_call
    assert exact_call.get("type") == {"$regex": "^movie$", "$options": "i"}, exact_call
    # Fuzzy candidate scan is facet-narrowed too.
    fuzzy_call = fake.find_calls[2]
    assert fuzzy_call.get("year") == {"$in": [2021, "2021"]}, fuzzy_call
    assert "$text" not in fuzzy_call


def test_perform_search_escapes_regex_chars():
    fake = FakeMoviesCol(doc_queues=[[], []])
    search_mod.movies_col = fake
    out = run(perform_search("C++"))
    assert out["title"] == "C++", out
    exact_call = fake.find_calls[1]
    assert exact_call["title"] == {"$regex": re.escape("C++"), "$options": "i"}, exact_call


def test_perform_search_fuzzy_uses_parsed_title():
    docs = [{"_id": 7, "title": "Dune", "year": 2021, "quality": "1080p", "type": "Movie"}]
    # No exact hit (empty exact stage), fuzzy scan returns the doc; the raw
    # query "Dune 2021" must fuzzy-match on parsed title "Dune", not the raw
    # string. Queues: exact stage -> [], fuzzy scan -> [doc] ($text attempt
    # raises before consuming any queue entry).
    fake = FakeMoviesCol(doc_queues=[[], list(docs)])
    search_mod.movies_col = fake
    out = run(perform_search("Dune 2021"))
    assert out["title"] == "Dune" and out["filters"]["year"] == 2021, out
    assert [d["_id"] for d in out["results"]] == [7]
    assert out["exact_ids"] == {7}  # "Dune" is_exact_title("Dune", "Dune")


# ------------------------------------------------------------------ #
# 3. Header rendering                                                 #
# ------------------------------------------------------------------ #

def test_build_search_page_shows_filters():
    results = [{"_id": 1, "title": "Dune", "year": 2021, "quality": "1080p",
                "type": "Movie", "channel_id": -100, "message_id": 5}]
    text, _, _, _ = build_search_page(
        results, "Dune 2021 1080p movie", 1, exact_ids={1},
        filters={"year": 2021, "quality": "1080p", "type": "Movie"})
    assert "Filters: year=2021 · 1080p · Movie" in text, text
    text_plain, _, _, _ = build_search_page(results, "Dune", 1, exact_ids={1})
    assert "Filters:" not in text_plain, text_plain


# ------------------------------------------------------------------ #
# Standalone runner (python tests/test_search_filters.py)             #
# ------------------------------------------------------------------ #

_TESTS = [
    test_parse_basic_title_only,
    test_parse_trailing_facets,
    test_parse_series_and_4k_alias,
    test_parse_paren_year_and_kv,
    test_parse_title_words_preserved,
    test_format_active_filters,
    test_perform_search_applies_facets_server_side,
    test_perform_search_escapes_regex_chars,
    test_perform_search_fuzzy_uses_parsed_title,
    test_build_search_page_shows_filters,
]


def main() -> int:
    failures = 0
    for fn in _TESTS:
        # Restore the real collection between tests (fakes swap module attr).
        from features import database as _db
        search_mod.movies_col = _db.movies_col
        try:
            out = fn()
            if asyncio.iscoroutine(out):
                run(out)
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
