#!/usr/bin/env python3
"""
Test: /search library facets (lang:/subs:/audio:/hdr:).

Pins the cluster-5 upgrade (features/search.py):

1. parse_search_query extracts lang:/subs:/audio:/hdr: anywhere (quoted
   multi-word values supported) plus bare trailing `hdr` (any HDR), without
   touching title words ("English Patient" keeps its words - language stays
   key:value-only by design).
2. perform_search pushes the facets server-side (case-insensitive exact on
   the parser's canonical values; bare hdr -> $exists).
3. build_search_page renders them in the Filters: header line.

All DB access runs against injected fakes - no real MongoDB needed.
"""

import asyncio
import os
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


class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

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
    def __init__(self, doc_queues=None):
        self.doc_queues = list(doc_queues or [])
        self.find_calls = []
        self.raise_on_text = True

    def find(self, filt=None, projection=None):
        self.find_calls.append(dict(filt or {}))
        if filt and "$text" in filt and self.raise_on_text:
            raise RuntimeError("no text index")
        docs = self.doc_queues.pop(0) if self.doc_queues else []
        return FakeCursor(docs)


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
# Parsing                                                             #
# ------------------------------------------------------------------ #

def test_parse_library_facets():
    p = parse_search_query("RRR lang:hindi subs:esub audio:atmos hdr:dv")
    assert p["title"] == "RRR", p
    assert p["language"] == "hindi", p
    assert p["subtitles"] == "esub", p
    assert p["audio"] == "atmos", p
    assert p["hdr"] == "Dolby Vision", p


def test_parse_quoted_multiword_language():
    p = parse_search_query('Dune lang:"dual audio"')
    assert p["title"] == "Dune" and p["language"] == "dual audio", p


def test_parse_bare_trailing_hdr():
    p = parse_search_query("Dune 2021 hdr")
    assert (p["title"], p["year"], p["hdr"]) == ("Dune", 2021, True), p


def test_title_words_never_eaten():
    # "English" looks like a language but stays title text without lang:.
    p = parse_search_query("The English Patient")
    assert p["title"] == "The English Patient", p
    assert p["language"] is None, p


def test_format_library_filters():
    line = format_active_filters(language="hindi", subtitles="esub",
                                 audio="atmos", hdr=True)
    assert line == "lang=hindi · subs=esub · audio=atmos · HDR", line
    line = format_active_filters(hdr="Dolby Vision")
    assert line == "HDR=Dolby Vision", line


# ------------------------------------------------------------------ #
# Server-side push-down                                               #
# ------------------------------------------------------------------ #

def test_perform_search_pushes_library_facets():
    docs = [{"_id": 1, "title": "RRR", "year": 2022, "language": "Hindi",
             "subtitles": "English Subs", "audio_codec": "Atmos",
             "hdr": "Dolby Vision"}]
    fake = FakeMoviesCol(doc_queues=[list(docs), []])
    search_mod.movies_col = fake
    out = run(perform_search("RRR lang:hindi subs:esub audio:atmos hdr:dv"))
    assert [d["_id"] for d in out["results"]] == [1], out
    exact_call = fake.find_calls[1]
    assert exact_call.get("language") == {"$regex": "^hindi$", "$options": "i"}, exact_call
    assert exact_call.get("subtitles") == {"$regex": "^esub$", "$options": "i"}, exact_call
    assert exact_call.get("audio_codec") == {"$regex": "^atmos$", "$options": "i"}, exact_call
    assert exact_call.get("hdr") == {"$regex": "^Dolby\\ Vision$", "$options": "i"}, exact_call


def test_perform_search_bare_hdr_exists():
    fake = FakeMoviesCol(doc_queues=[[], []])
    search_mod.movies_col = fake
    out = run(perform_search("Dune hdr"))
    assert out["filters"]["hdr"] is True, out
    exact_call = fake.find_calls[1]
    assert exact_call.get("hdr") == {"$exists": True, "$ne": None}, exact_call


def test_header_shows_library_facets():
    results = [{"_id": 1, "title": "RRR", "year": 2022, "quality": "2160p",
                "type": "Movie", "channel_id": -100, "message_id": 5}]
    text, _, _, _ = build_search_page(
        results, "RRR lang:hindi hdr", 1, exact_ids={1},
        filters={"year": None, "quality": None, "type": None,
                 "language": "hindi", "subtitles": None,
                 "audio": None, "hdr": True})
    assert "Filters: lang=hindi · HDR" in text, text


# ------------------------------------------------------------------ #
# Standalone runner                                                   #
# ------------------------------------------------------------------ #

_TESTS = [
    test_parse_library_facets,
    test_parse_quoted_multiword_language,
    test_parse_bare_trailing_hdr,
    test_title_words_never_eaten,
    test_format_library_filters,
    test_perform_search_pushes_library_facets,
    test_perform_search_bare_hdr_exists,
    test_header_shows_library_facets,
]


def main() -> int:
    failures = 0
    for fn in _TESTS:
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
