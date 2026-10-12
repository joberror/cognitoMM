import asyncio
import time

from features.user_management import load_terms_and_privacy

async def run_benchmark():
    start = time.time()
    for _ in range(10000):
        await load_terms_and_privacy()
    end = time.time()
    print(f"Time taken: {end - start:.4f} seconds")

asyncio.run(run_benchmark())
