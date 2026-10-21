import asyncio
import os
import time
import aiofiles

_terms_text = None

# Compute absolute path to TERMS_AND_PRIVACY.md relative to this script's directory
_TERMS_FILE_PATH = os.path.join(os.path.dirname(__file__), 'TERMS_AND_PRIVACY.md')

async def load_terms_and_privacy_cached():
    global _terms_text
    if _terms_text is None:
        try:
            async with aiofiles.open(_TERMS_FILE_PATH, 'r', encoding='utf-8') as f:
                _terms_text = await f.read()
        except Exception as e:
            print(f"❌ Failed to load terms and privacy: {e}")
            return None
    return _terms_text

async def run_benchmark():
    # Warmup / Load
    await load_terms_and_privacy_cached()

    start = time.time()
    for _ in range(10000):
        await load_terms_and_privacy_cached()
    end = time.time()
    print(f"Time taken (cached): {end - start:.4f} seconds")

asyncio.run(run_benchmark())
