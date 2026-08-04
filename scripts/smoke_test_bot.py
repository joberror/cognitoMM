#!/usr/bin/env python3
"""
MANUAL live smoke test - NOT part of the pytest suite (kept out of tests/ so
pytest never collects it).

WARNING: This script connects to the REAL Telegram API using the credentials
in .env and prints API_ID to stdout. It is for ad-hoc verification only - do
not run it in CI or on shared machines.

Note: it uses the pyrogram library (legacy); the production bot runs on
hydrogram (see features/bot.py).
"""

import os
import asyncio
from dotenv import load_dotenv
from hydrogram import Client, filters
from hydrogram.types import Message

load_dotenv()

# Get credentials from .env
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

print(f"API_ID: {API_ID}")
print(f"API_HASH: {'*' * len(API_HASH) if API_HASH else 'Not set'}")
print(f"BOT_TOKEN: {'*' * len(BOT_TOKEN) if BOT_TOKEN else 'Not set'}")

# Create bot client
bot = Client(
    "test_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir="."
)

@bot.on_message(filters.command("start"))
async def start_command(client, message: Message):
    await message.reply_text("🎬 Hello! Test bot is working!")

@bot.on_message(filters.command("test"))
async def test_command(client, message: Message):
    await message.reply_text("✅ Test command received!")

async def main():
    print("🔄 Starting test bot...")
    try:
        await bot.start()
        print("✅ Test bot started successfully!")
        print("📱 Bot is ready to receive commands!")
        print("🛑 Press Ctrl+C to stop")
        
        # Keep the bot running
        await asyncio.Event().wait()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            await bot.stop()
            print("✅ Bot stopped")
        except Exception as e:
            print(f"⚠️ Error stopping bot: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
