# This is a telegram bot that has a lot to do with movie files.

## Note: 
Below are pre-set details of the bot (ENV)
- Telegram Bot API ID
- Telegram Bot API HASH
- Mongo Database URL
- Bot Token
- Bot Username
- Bot Admin

1. First thing first
Set up a requirements of recommended packages for telegram bot development that can handle channel files

2. Database
For a start,create and add the below table, and their respective indexes (table name: index name) to the databse. Use recommended index format.
- Users : Telegram Name, Telegram ID, Date Added
- Admins : Telegram Name, Telegram ID, Level
- Channels : Channel Name, Channel ID, Date Added
