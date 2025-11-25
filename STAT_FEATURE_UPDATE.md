# Statistics Feature - Bot Information Update

## Update Summary
Added comprehensive bot information section to the `/stat` command statistics dashboard.

## Changes Made

### 1. Configuration Update (`features/config.py`)
**Added**:
- `BOT_START_TIME` - Global variable tracking when bot started (datetime in UTC)
- Imports for datetime and timezone

**Purpose**: Track bot uptime from startup

### 2. Statistics Module (`features/statistics.py`)
**Added Functions**:
- `collect_bot_info()` - Async function to gather bot information including:
  - Bot username, ID, and name from Telegram API
  - Data center ID (if available)
  - Uptime calculation from `BOT_START_TIME`
  - Python version
  - Platform/OS information (Linux, Windows, etc.)
  - System architecture (x86_64, aarch64, etc.)
  
- `format_uptime()` - Helper function to format uptime in human-readable format:
  - Examples: "2d 5h 30m 15s", "45m 20s", "5s"
  - Intelligently shows only relevant time units

**Modified Functions**:
- `collect_comprehensive_stats()` - Now calls `collect_bot_info()` and includes bot_info in stats
- `format_stats_output()` - Added new "🤖 BOT INFORMATION" section at the top of dashboard
- `export_stats_csv()` - Includes bot information in CSV export

**New Imports**:
- `sys` - For Python version detection
- `platform` - For OS and architecture detection
- `BOT_START_TIME, client` from config

## New Statistics Display

### Bot Information Section
The `/stat` command now shows a **🤖 BOT INFORMATION** section at the very top with:

```
┌─────────────────────────────────────────────┐
│  🤖 BOT INFORMATION                         │
└─────────────────────────────────────────────┘

Bot Name:           MovieBot
Username:           @moviebot
Bot ID:             123456789
Data Center:        DC-4

Uptime:             2d 5h 30m 15s
Started:            2025-11-23 10:15:30 UTC

Python:             3.11.5
Platform:           Linux 5.15
Architecture:       x86_64
```

## Updated Category Count
The `/stat` command now displays **7 comprehensive categories** (previously 6):

1. **🤖 Bot Information** (NEW)
   - Bot identity and connection details
   - Uptime tracking
   - System environment information

2. **👥 User Statistics**
3. **🎥 Content Statistics**
4. **📡 Channel Statistics**
5. **⚙️ System Statistics**
6. **🔍 Activity Statistics**
7. **⭐ Premium Statistics**

## Export Updates

### JSON Export
Bot information is included in JSON exports:
```json
{
  "bot_info": {
    "bot_name": "MovieBot",
    "bot_username": "moviebot",
    "bot_id": 123456789,
    "bot_dc_id": 4,
    "uptime_seconds": 186015,
    "uptime_formatted": "2d 5h 30m 15s",
    "start_time": "2025-11-23T10:15:30+00:00",
    "python_version": "3.11.5",
    "platform": "Linux",
    "platform_release": "5.15",
    "architecture": "x86_64"
  },
  ...
}
```

### CSV Export
Bot information rows added:
```csv
Category,Metric,Value
Bot,Bot Name,MovieBot
Bot,Username,moviebot
Bot,Bot ID,123456789
Bot,Uptime,2d 5h 30m 15s
Bot,Python Version,3.11.5
Bot,Platform,Linux
...
```

## Technical Details

### Uptime Calculation
```python
uptime_seconds = (datetime.now(timezone.utc) - BOT_START_TIME).total_seconds()
```

### Format Logic
- Shows days only if > 0
- Shows hours only if > 0
- Shows minutes only if > 0
- Always shows seconds (or if no other units)
- Example progression: "5s" → "2m 5s" → "1h 2m 5s" → "1d 1h 2m 5s"

### Error Handling
- If Telegram API fails: Shows "Unknown" for bot details
- If client not initialized: Gracefully handles with fallback values
- All errors logged for debugging

## Benefits

1. **Monitoring**: Admins can quickly see bot uptime and health
2. **Debugging**: Python version and platform info helpful for troubleshooting
3. **Transparency**: Clear bot identity confirmation
4. **Performance**: Shows how long bot has been running
5. **Environment**: Helps identify deployment environment issues

## Testing Recommendations

1. **Test after bot restart** - Verify uptime starts at 0
2. **Test uptime formatting** - Check various time ranges (seconds, minutes, hours, days)
3. **Test on different platforms** - Verify platform detection (Linux, Windows, etc.)
4. **Test Telegram API failure** - Simulate connection issues
5. **Test export formats** - Verify bot info in JSON and CSV exports
6. **Test with non-admin** - Ensure access control still works

## Files Modified

1. `features/config.py` - Added BOT_START_TIME tracker
2. `features/statistics.py` - Added bot info collection and formatting
3. `STAT_FEATURE_UPDATE.md` - This documentation (NEW)

## Compatibility

- ✅ Fully backward compatible
- ✅ No database schema changes required
- ✅ No breaking changes to existing functionality
- ✅ Works with existing exports and callbacks

---

**Version**: 1.1  
**Date**: 2025-11-25  
**Author**: Kilo Code