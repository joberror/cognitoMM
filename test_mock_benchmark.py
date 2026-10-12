import asyncio
import time
from datetime import datetime, timezone, timedelta

class MockCollection:
    def __init__(self):
        self.updates = []
        self.bulk_ops = []

    class FindCursor:
        def __init__(self, docs):
            self.docs = docs
        async def to_list(self, length):
            return self.docs

    def find(self, query):
        now = datetime.now(timezone.utc)
        docs = []
        for i in range(1000):
            docs.append({
                "user_id": i,
                "expiry_date": now + timedelta(days=2),
                # no warn flags set
            })
        return self.FindCursor(docs)

    async def update_one(self, query, update):
        # Simulate db network latency
        await asyncio.sleep(0.001)
        self.updates.append((query, update))

    async def bulk_write(self, ops):
        # Simulate db network latency for bulk write
        await asyncio.sleep(0.005)
        self.bulk_ops.extend(ops)

class UpdateOne:
    def __init__(self, filter, update):
        self.filter = filter
        self.update = update

async def mock_send_expiry_warning(user_id, days_left, expiry):
    # Simulate some local work
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
    col1 = MockCollection()
    baseline_time, sent1 = await run_baseline(col1)

    col2 = MockCollection()
    optimized_time, sent2 = await run_optimized(col2)

    print(f"Baseline (N+1 queries) with simulated 1ms latency: {baseline_time:.4f}s")
    print(f"Optimized (Bulk write) with simulated 5ms bulk latency: {optimized_time:.4f}s")
    print(f"Improvement: {(baseline_time - optimized_time) / baseline_time * 100:.2f}%")

if __name__ == '__main__':
    asyncio.run(main())
