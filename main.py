"""
Movie Bot - Entry Point

This is the main entry point for the Movie Bot application.
It initializes the database connection and starts the bot using the modular structure
from the features package.

The application uses:
- Hydrogram for Telegram bot functionality
- MongoDB for data storage
- Modular architecture for maintainability
"""

# Import the bot initialization and main function from features
from features.bot import run_bot

if __name__ == "__main__":
    # Start the bot with all functionality from the modular structure
    run_bot()