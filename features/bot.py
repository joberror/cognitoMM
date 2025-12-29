"""
Bot Initialization and Main Loop Module

This module contains the bot initialization, main function, and event loop handling.
It sets up the Hydrogram client, registers handlers, and manages the bot lifecycle.
"""

import sys
import asyncio
import threading
from datetime import datetime, timezone
from hydrogram import Client, filters
from hydrogram.types import Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from hydrogram.handlers import MessageHandler, InlineQueryHandler, CallbackQueryHandler
from hydrogram.enums import ChatType

# Import from our modules
from .config import API_ID, API_HASH, BOT_TOKEN, LOG_CHANNEL, client
from .logger import logger
from .database import ensure_indexes
from .commands import handle_command
from .callbacks import callback_handler
from .indexing import on_message
from .file_deletion import start_deletion_monitor
from .search import inline_handler
from .deletion_events import handle_raw_update  # Real-time deletion heuristic handler

# -------------------------
# CUSTOM BOT CLASS WITH iter_messages
# -------------------------

class CognitoBot(Client):
    """Extended Hydrogram Client with iter_messages method from Auto-Filter-Bot"""

    def __init__(self):
        super().__init__(
            name="movie_bot_session",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workdir=".",
        )

    async def iter_messages(self, chat_id, limit: int, offset: int = 0):
        """
        Iterate through a chat sequentially.
        This convenience method does the same as repeatedly calling get_messages in a loop.

        Parameters:
            chat_id (int | str): Unique identifier of the target chat
            limit (int): Identifier of the last message to be returned
            offset (int, optional): Identifier of the first message to be returned. Defaults to 0.

        Returns:
            Generator: A generator yielding Message objects.
        """
        current = offset
        while True:
            new_diff = min(200, limit - current)
            if new_diff <= 0:
                return
            messages = await self.get_messages(chat_id, list(range(current, current+new_diff+1)))
            for message in messages:
                yield message
                current += 1

# -------------------------
# Main Function with Event Loop Handling
# -------------------------
def run_bot():
    """Run bot with Kurigram - simplified approach"""
    try:
        print("🔄 Starting bot with Kurigram...")
        # Use asyncio.run for cleaner event loop management
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()

async def main():
    print("🔧 Setting up database indexes...")
    await ensure_indexes()
    print("✅ Database indexes ready")

    # Initialize premium features
    print("🔧 Initializing premium features...")
    from .premium_management import initialize_premium_features
    await initialize_premium_features()
    print("✅ Premium features initialized")

    # Create client configuration
    try:
        # Validate required environment variables
        if not API_ID or not API_HASH:
            print("❌ API_ID and API_HASH are required")
            sys.exit(1)

        if not BOT_TOKEN:
            print("❌ BOT_TOKEN is required for bot session")
            sys.exit(1)

        print("🔄 Starting bot session...")

        # Use our custom CognitoBot class with iter_messages support
        async with CognitoBot() as app:
            # Get bot info for verification
            bot_info = await app.get_me()
            print(f"✅ Bot authenticated: @{bot_info.username} ({bot_info.first_name})")
            print(f"🆔 Bot ID: {bot_info.id}")

            # Set client reference in config for handlers
            from . import config
            config.client = app

            # Initialize Logger
            logger.set_client(app, LOG_CHANNEL)
            logger.start_capturing()
            logger.log("🤖 Bot Session Started")
            if LOG_CHANNEL:
                print(f"📝 Logging to channel: {LOG_CHANNEL}")
            else:
                print("⚠️ No LOG_CHANNEL defined in .env")

            # Register handlers
            app.add_handler(MessageHandler(handle_command, filters.regex(r"^/")))
            app.add_handler(MessageHandler(on_message))
            app.add_handler(InlineQueryHandler(inline_handler))
            app.add_handler(CallbackQueryHandler(callback_handler))

            # Register RawUpdateHandler for real-time deletions (if available)
            try:
                from hydrogram.handlers import RawUpdateHandler
                app.add_handler(RawUpdateHandler(handle_raw_update))
            except Exception:
                pass  # Handler not available in this version

            # Start deletion monitor background task
            asyncio.create_task(start_deletion_monitor())

            print("✅ MovieBot is running!")
            print("🛑 Press Ctrl+C to stop")

            # Keep the program running
            stop_event = asyncio.Event()

            # Handle shutdown gracefully
            async def signal_handler():
                print("\n🛑 Received shutdown signal...")
                await logger.flush()
                logger.stop_capturing()
                stop_event.set()

            # Wait for stop signal
            try:
                await stop_event.wait()
            except KeyboardInterrupt:
                await signal_handler()

    except Exception as e:
        print(f"❌ Error during startup: {e}")
        import traceback
        traceback.print_exc()

# Client reference will be managed in config.py

if __name__ == "__main__":
    run_bot()
