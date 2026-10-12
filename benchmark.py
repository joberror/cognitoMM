import asyncio
import time
import json
import os
import aiofiles

# Setup some dummy data
data = {f"test_{i}": {"some": "data"} for i in range(100000)}
with open('test_file_deletions.json', 'w') as f:
    json.dump(data, f)

def sync_read():
    with open('test_file_deletions.json', 'r') as f:
        data = json.load(f)
    return data

async def async_read():
    async with aiofiles.open('test_file_deletions.json', 'r') as f:
        content = await f.read()
        data = json.loads(content)
    return data

def sync_write(data):
    with open('test_file_deletions.json', 'w') as f:
        json.dump(data, f)

async def async_write(data):
    async with aiofiles.open('test_file_deletions.json', 'w') as f:
        await f.write(json.dumps(data))

async def main():
    print("Benchmarking read...")

    start = time.perf_counter()
    sync_read()
    sync_read_time = time.perf_counter() - start
    print(f"Sync read time: {sync_read_time:.4f}s")

    start = time.perf_counter()
    await async_read()
    async_read_time = time.perf_counter() - start
    print(f"Async read time: {async_read_time:.4f}s")

    print("\nBenchmarking write...")
    start = time.perf_counter()
    sync_write(data)
    sync_write_time = time.perf_counter() - start
    print(f"Sync write time: {sync_write_time:.4f}s")

    start = time.perf_counter()
    await async_write(data)
    async_write_time = time.perf_counter() - start
    print(f"Async write time: {async_write_time:.4f}s")

    os.remove('test_file_deletions.json')

asyncio.run(main())
