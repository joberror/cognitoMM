"""
Backfill TMDb enrichment for existing indexed entries.

Standalone counterpart of the bot's /enrich command: iterates movies missing
`tmdb_genres`, looks each title up on TMDb (cached per title via
features/tmdb_integration.enrich_title), and stores poster/rating/genres/
overview/imdb_id. Idempotent - re-running skips documents that already have
genres. Writes to the MONGO_URI / MONGO_DB configured in .env (this is the
same database the deployed bot uses).

Usage:
  .venv/bin/python scripts/backfill_enrichment.py             # next 100 entries
  .venv/bin/python scripts/backfill_enrichment.py --limit 500
  .venv/bin/python scripts/backfill_enrichment.py --all       # everything pending
  .venv/bin/python scripts/backfill_enrichment.py --dry-run   # count only, no writes
  .venv/bin/python scripts/backfill_enrichment.py --delay 0.5 # gentler toward TMDb

Notes:
- Transient TMDb/network errors are NOT cached as misses (see enrich_title),
  so a re-run after an outage picks those titles up.
- Run it as many times as needed - each run advances the enriched count.
"""

import argparse
import asyncio
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from features.config import MONGO_URI, MONGO_DB, TMDB_API

# Entries awaiting enrichment: tmdb_genres absent. Genuine no-matches are
# marked with an EMPTY array (so they leave the pending set and are not
# re-hit on every run); enriched entries get a real array.
_PENDING_FILTER = {"tmdb_genres": {"$exists": False}}
_NO_MATCH_MARK = {"tmdb_genres": []}
_SLICE_SIZE = 500


def _masked_host(uri: str) -> str:
    """Redact credentials from a Mongo URI for display (mongodb://u:p@host)."""
    if "://" in uri:
        scheme, rest = uri.split("://", 1)
        if "@" in rest:
            host = rest.rsplit("@", 1)[1]
        else:
            host = rest
        return f"{scheme}://***@{host}"
    return uri


async def count_pending(movies_col_ref) -> int:
    """Number of entries still missing TMDb metadata."""
    return await movies_col_ref.count_documents(_PENDING_FILTER)


async def backfill(movies_col_ref, limit: int = 100, delay: float = 0.2,
                   concurrency: int = 1, progress_cb=None):
    """
    Enrich up to `limit` entries missing tmdb_genres.

    ``movies_col_ref`` allows injecting a fake for tests; ``concurrency`` runs
    that many TMDb lookups in parallel (DB writes still applied in order, one
    ``delay`` apart, so Mongo load stays gentle); ``progress_cb`` is an optional
    async callable receiving (processed, total, enriched, not_found).

    Returns:
        dict: {scanned, enriched, not_found}
    """
    from features.tmdb_integration import enrich_title

    cursor = movies_col_ref.find(
        _PENDING_FILTER,
        {"title": 1, "year": 1, "type": 1, "_id": 1, "imdb": 1},
    ).limit(limit)
    docs = await cursor.to_list(length=limit)

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _lookup(doc):
        async with sem:
            meta = await enrich_title(doc.get("title"), doc.get("year"), doc.get("type", "Movie"))
            return doc, meta

    # Look up all titles (bounded by the semaphore), then write back in order.
    results = await asyncio.gather(*[_lookup(doc) for doc in docs])

    enriched = 0
    not_found = 0
    for i, (doc, meta) in enumerate(results, 1):
        if meta:
            set_fields = {
                "tmdb_poster": meta.get("poster_url"),
                "tmdb_rating": meta.get("rating"),
                "tmdb_genres": meta.get("genres"),
                "tmdb_overview": meta.get("overview"),
                "imdb_id": meta.get("imdb_id") or doc.get("imdb"),
            }
            await movies_col_ref.update_one({"_id": doc["_id"]}, {"$set": set_fields})
            enriched += 1
        else:
            # Genuine no-match on TMDb (or transient error). Mark it attempted
            # with an empty array so it leaves the pending set - otherwise the
            # head of the pending list would re-select it forever. A transient
            # error can be retried by clearing the field (or a later /enrich
            # run after a cold start of the cache).
            await movies_col_ref.update_one({"_id": doc["_id"]}, {"$set": _NO_MATCH_MARK})
            not_found += 1
        if progress_cb is not None:
            await progress_cb(i, len(docs), enriched, not_found)
        if delay:
            await asyncio.sleep(delay)

    return {"scanned": len(docs), "enriched": enriched, "not_found": not_found}


async def run(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Backfill TMDb metadata for indexed entries")
    parser.add_argument("--limit", type=int, default=100, help="entries to process (default 100)")
    parser.add_argument("--all", action="store_true", help="process everything pending")
    parser.add_argument("--delay", type=float, default=0.2, help="seconds between DB writes (default 0.2)")
    parser.add_argument("--concurrency", type=int, default=4, help="parallel TMDb lookups (default 4)")
    parser.add_argument("--dry-run", action="store_true", help="count pending entries only, write nothing")
    args = parser.parse_args(argv)

    if not MONGO_URI or not TMDB_API or TMDB_API == "your_api_key_here":
        print("❌ MONGO_URI and TMDB_API must be configured in .env")
        return 1

    from features.database import movies_col

    print(f"🎯 Target: {MONGO_DB} @ {_masked_host(MONGO_URI)}")
    pending = await count_pending(movies_col)
    print(f"📊 Entries missing TMDb metadata: {pending}")

    if args.dry_run:
        print("👀 Dry run - nothing was written.")
        return 0

    if args.all:
        # Process in bounded slices: --all must never materialize the whole
        # pending set at once (22k+ docs stalls on slow connections), and
        # no-match entries are marked [] so each slice advances to fresh docs.
        print(f"🚀 Enriching all {pending} entries in slices of {_SLICE_SIZE} "
              f"(concurrency {args.concurrency}, delay {args.delay}s)...")
        total_enriched = 0
        total_not_found = 0
        total_scanned = 0
        while True:
            result = await backfill(movies_col, limit=_SLICE_SIZE, delay=args.delay,
                                    concurrency=args.concurrency)
            total_scanned += result["scanned"]
            total_enriched += result["enriched"]
            total_not_found += result["not_found"]
            print(f"   [slice] scanned {result['scanned']}, enriched {result['enriched']}, "
                  f"no match {result['not_found']} | cumulative enriched {total_enriched}")
            remaining = await count_pending(movies_col)
            if result["scanned"] == 0 or remaining == 0:
                break
        print(f"✅ Done: enriched {total_enriched} of {total_scanned} scanned "
              f"({total_not_found} with no TMDb match).")
        print(f"📊 Remaining pending: {await count_pending(movies_col)}")
        return 0

    limit = min(args.limit, pending)
    if limit <= 0:
        print("✅ Nothing to do - all indexed entries already have TMDb metadata.")
        return 0

    print(f"🚀 Enriching up to {limit} entries (concurrency {args.concurrency}, delay {args.delay}s)...")

    async def _progress(processed, total, enriched, not_found):
        if processed % 50 == 0 or processed == total:
            print(f"   [{processed}/{total}] enriched: {enriched}, no match: {not_found}")

    result = await backfill(movies_col, limit=limit, delay=args.delay,
                            concurrency=args.concurrency, progress_cb=_progress)

    remaining = await count_pending(movies_col)
    print(f"✅ Done: enriched {result['enriched']} of {result['scanned']} scanned "
          f"({result['not_found']} with no TMDb match).")
    print(f"📊 Remaining pending: {remaining}"
          + (" - re-run to continue." if remaining else " - all enriched!"))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
