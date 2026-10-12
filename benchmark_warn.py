import asyncio
import time
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient

async def setup_db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client["benchmark_db"]
    col = db["premium_users"]
    await col.delete_many({})

    now = datetime.now(timezone.utc)
    # Insert 1000 users expiring in 2 days (triggering 3d and 7d thresholds)
    docs = []
    for i in range(1000):
        docs.append({
            "user_id": i,
            "expiry_date": now + timedelta(days=2),
            # no warn flags set
        })
    await col.insert_many(docs)
    return col

# Mock _send_expiry_warning
async def mock_send_expiry_warning(user_id, days_left, expiry):
    return True

async def run_baseline(col):
    thresholds = sorted([1, 3, 7])
    now = datetime.now(timezone.utc)
    docs = await col.find({}).to_list(length=2000)

    start_time = time.time()

    sent = 0
    for doc in docs:
        expiry = doc.get("expiry_date")
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        delta = expiry - now
        if delta.total_seconds() <= 0:
            continue

        days_left = delta.days
        for idx, threshold in enumerate(thresholds):
            flag = f"warned_{threshold}d"
            if days_left <= threshold and not doc.get(flag):
                await mock_send_expiry_warning(doc.get("user_id"), days_left, expiry)
                sent += 1
                updates = {flag: True}
                for larger in thresholds[idx + 1:]:
                    updates[f"warned_{larger}d"] = True
                await col.update_one({"user_id": doc.get("user_id")}, {"$set": updates})
                break

    end_time = time.time()
    return end_time - start_time, sent

from pymongo import UpdateOne
async def run_optimized(col):
    thresholds = sorted([1, 3, 7])
    now = datetime.now(timezone.utc)
    docs = await col.find({}).to_list(length=2000)

    start_time = time.time()

    sent = 0
    bulk_ops = []
    for doc in docs:
        expiry = doc.get("expiry_date")
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        delta = expiry - now
        if delta.total_seconds() <= 0:
            continue

        days_left = delta.days
        for idx, threshold in enumerate(thresholds):
            flag = f"warned_{threshold}d"
            if days_left <= threshold and not doc.get(flag):
                await mock_send_expiry_warning(doc.get("user_id"), days_left, expiry)
                sent += 1
                updates = {flag: True}
                for larger in thresholds[idx + 1:]:
                    updates[f"warned_{larger}d"] = True

                bulk_ops.append(
                    UpdateOne({"user_id": doc.get("user_id")}, {"$set": updates})
                )
                break

    if bulk_ops:
        await col.bulk_write(bulk_ops)

    end_time = time.time()
    return end_time - start_time, sent

async def main():
    col = await setup_db()
    baseline_time, sent1 = await run_baseline(col)

    col = await setup_db()
    optimized_time, sent2 = await run_optimized(col)

    print(f"Baseline (N+1 queries): {baseline_time:.4f}s")
    print(f"Optimized (Bulk write): {optimized_time:.4f}s")
    print(f"Improvement: {(baseline_time - optimized_time) / baseline_time * 100:.2f}%")

if __name__ == '__main__':
    asyncio.run(main())
