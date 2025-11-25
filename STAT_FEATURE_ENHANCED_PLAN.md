# 📊 Enhanced /stat Command - Implementation Plan with Export & QuickStat

## 🎯 Enhanced Features Overview

Building on the comprehensive stats plan, we're adding:

1. **Export Functionality**: Download stats as JSON or CSV
2. **Quick Stats Command**: `/quickstat` for rapid overview
3. **Interactive Buttons**: Export options in the stat output

## 🆕 Additional Commands

### 1. `/stat` - Full Statistics Dashboard
- Complete comprehensive statistics
- Interactive buttons for export options
- Real-time data collection
- All 6 categories of statistics

### 2. `/quickstat` - Quick Summary
- Essential metrics only (top 15-20 data points)
- Faster response time (< 3 seconds)
- Perfect for quick checks
- No export buttons (lightweight)

## 🎨 Enhanced Output Design

### Full /stat Command with Export Buttons

```
╔═══════════════════════════════════════════════════════╗
║           📊 BOT STATISTICS DASHBOARD                 ║
║                  Generated: 2025-01-20 14:30 UTC     ║
╚═══════════════════════════════════════════════════════╝

[... All 6 sections of statistics ...]

┌─────────────────────────────────────────────────────┐
│ 💾 EXPORT OPTIONS                                    │
└─────────────────────────────────────────────────────┘

[📥 Export as JSON]  [📊 Export as CSV]  [🔄 Refresh]
```

### /quickstat Output

```
⚡ QUICK STATS SUMMARY

👥 Users: 1,234 (1,012 active) | ⭐ 45 premium
🎬 Content: 45,678 files (71% movies, 29% series)
📺 Channels: 15 active | 📊 Top: MovieChannel (8,234)
🔍 Searches: 2,456 today | 🔥 Top: Spider-Man (847x)
📝 Requests: 23 pending | ⚙️ Success Rate: 98.5%
💾 Storage: 2.3 TB | 📈 Growth: +15% this week

Last Updated: 2025-01-20 14:30 UTC
Use /stat for detailed statistics
```

## 📦 Export Formats

### JSON Export Format
```json
{
  "generated_at": "2025-01-20T14:30:00Z",
  "bot_name": "MovieBot",
  "statistics": {
    "users": {
      "total": 1234,
      "active_7d": 1012,
      "active_30d": 1156,
      "new_today": 12,
      "new_7d": 89,
      "new_30d": 234,
      "premium": 45,
      "admins": 3,
      "banned": 18,
      "growth_rate": 15.3
    },
    "content": {
      "total_files": 45678,
      "movies": 32456,
      "series": 13222,
      "quality_distribution": {
        "4K": 8234,
        "1080p": 28456,
        "720p": 7890,
        "other": 1098
      },
      "total_storage_bytes": 2473901162496,
      "average_file_size_bytes": 54823936
    },
    "channels": {
      "total": 15,
      "active": 13,
      "disabled": 2,
      "top_channels": [
        {"name": "MovieChannel", "files": 8234},
        {"name": "HDMovies", "files": 6789}
      ]
    },
    "activity": {
      "total_searches": 156789,
      "searches_today": 2456,
      "searches_7d": 15678,
      "top_searches": [
        {"query": "Spider-Man", "count": 847},
        {"query": "Inception", "count": 723}
      ]
    },
    "system": {
      "indexing_success_rate": 98.5,
      "total_indexing_attempts": 50000,
      "successful_inserts": 45678,
      "duplicate_errors": 234,
      "other_errors": 88
    },
    "premium": {
      "total_premium_users": 45,
      "expiring_7d": 8,
      "expiring_30d": 15,
      "premium_features": ["recent", "request", "advanced_search"]
    }
  }
}
```

### CSV Export Format (Flattened)
```csv
Category,Metric,Value,Percentage,Timestamp
Users,Total Users,1234,,2025-01-20 14:30:00
Users,Active (7d),1012,82.0%,2025-01-20 14:30:00
Users,Premium,45,3.6%,2025-01-20 14:30:00
Content,Total Files,45678,,2025-01-20 14:30:00
Content,Movies,32456,71.0%,2025-01-20 14:30:00
Content,Series,13222,29.0%,2025-01-20 14:30:00
Content,4K Quality,8234,18.0%,2025-01-20 14:30:00
Channels,Total Channels,15,,2025-01-20 14:30:00
Activity,Searches Today,2456,,2025-01-20 14:30:00
System,Success Rate,98.5%,,2025-01-20 14:30:00
```

## 🔧 Technical Implementation Details

### File Structure

```python
# In commands.py

async def cmd_stat(client, message: Message):
    """Full comprehensive statistics with export options"""
    # 1. Check admin
    # 2. Collect all stats
    # 3. Format output
    # 4. Add export buttons
    # 5. Send message

async def cmd_quickstat(client, message: Message):
    """Quick summary statistics"""
    # 1. Check admin
    # 2. Collect essential stats only
    # 3. Format compact output
    # 4. Send message (no buttons)

async def collect_comprehensive_stats():
    """Collect all statistics in parallel"""
    # Use asyncio.gather for parallel collection
    # Return structured dict

async def collect_quick_stats():
    """Collect essential statistics only (optimized)"""
    # Fewer queries, faster response
    # Return minimal dict

async def format_full_stats_output(stats_dict):
    """Format comprehensive statistics with visual elements"""
    # Create beautiful multi-section output
    # Add progress bars, emojis, formatting
    # Return formatted string

async def format_quick_stats_output(stats_dict):
    """Format quick statistics summary"""
    # Single compact output
    # Essential metrics only
    # Return formatted string

async def export_stats_json(stats_dict, user_id):
    """Generate and send JSON file"""
    # 1. Convert stats to JSON
    # 2. Create temp file
    # 3. Send as document
    # 4. Clean up temp file

async def export_stats_csv(stats_dict, user_id):
    """Generate and send CSV file"""
    # 1. Flatten stats dict to CSV rows
    # 2. Create temp file with csv module
    # 3. Send as document
    # 4. Clean up temp file

def create_progress_bar(value, max_value, length=10, filled='█', empty='░'):
    """Create ASCII progress bar"""
    # Calculate percentage
    # Build bar string
    # Return formatted bar

def format_number(num):
    """Format number with commas (1,234,567)"""
    return f"{num:,}"

def format_percentage(part, total, decimals=1):
    """Calculate and format percentage"""
    if total == 0:
        return "0.0%"
    return f"{(part/total)*100:.{decimals}f}%"
```

### Callback Handlers (in callbacks.py)

```python
# Handle export button clicks
async def handle_stat_export_callback(client, callback_query):
    """Handle stat export button callbacks"""
    data = callback_query.data
    # Format: "stat_export:json:user_id" or "stat_export:csv:user_id"
    
    if "json" in data:
        await export_stats_json(...)
    elif "csv" in data:
        await export_stats_csv(...)
    elif "refresh" in data:
        await cmd_stat(client, callback_query.message)
    
    await callback_query.answer("Generating export...")
```

### Export Button Layout

```python
# In cmd_stat function
buttons = [
    [
        InlineKeyboardButton("📥 Export JSON", callback_data=f"stat_export:json:{uid}"),
        InlineKeyboardButton("📊 Export CSV", callback_data=f"stat_export:csv:{uid}")
    ],
    [
        InlineKeyboardButton("🔄 Refresh Stats", callback_data=f"stat_export:refresh:{uid}")
    ]
]
keyboard = InlineKeyboardMarkup(buttons)
```

## 📊 Quick Stats Metrics Selection

### Essential Metrics for /quickstat (15-20 items)

**User Metrics (4):**
- Total users
- Active users (7d)
- Premium users
- Growth rate

**Content Metrics (5):**
- Total files
- Movies count & percentage
- Series count & percentage
- Total storage
- Most common quality

**Channel Metrics (2):**
- Total active channels
- Top channel name & file count

**Activity Metrics (3):**
- Searches today
- Top search term & count
- Pending requests

**System Metrics (2):**
- Success rate
- Uptime or last index time

## 🎯 Performance Optimization

### Quick Stats Optimization
```python
# Use lean queries with projection
quick_user_stats = await users_col.aggregate([
    {
        "$facet": {
            "total": [{"$count": "count"}],
            "active": [
                {"$match": {"last_seen": {"$gte": seven_days_ago}}},
                {"$count": "count"}
            ],
            "premium": [
                {"$lookup": {
                    "from": "premium_users",
                    "localField": "user_id",
                    "foreignField": "user_id",
                    "as": "premium"
                }},
                {"$match": {"premium": {"$ne": []}}},
                {"$count": "count"}
            ]
        }
    }
]).to_list(length=1)
```

### Caching Strategy (Optional)
```python
# Cache stats for 5 minutes to reduce load
from functools import lru_cache
from datetime import datetime, timedelta

stats_cache = {
    'data': None,
    'timestamp': None,
    'ttl': 300  # 5 minutes
}

async def get_cached_stats(force_refresh=False):
    """Get stats with caching"""
    now = datetime.now(timezone.utc)
    
    if (not force_refresh and 
        stats_cache['data'] and 
        stats_cache['timestamp'] and
        (now - stats_cache['timestamp']).seconds < stats_cache['ttl']):
        return stats_cache['data']
    
    # Collect fresh stats
    stats = await collect_comprehensive_stats()
    stats_cache['data'] = stats
    stats_cache['timestamp'] = now
    return stats
```

## 🛡️ Error Handling

```python
try:
    stats = await asyncio.wait_for(
        collect_comprehensive_stats(),
        timeout=30.0
    )
except asyncio.TimeoutError:
    await message.reply_text(
        "⏰ **Stats Collection Timeout**\n\n"
        "The statistics are taking too long to collect.\n"
        "This might be due to large dataset. Try /quickstat instead."
    )
    return
except Exception as e:
    await log_action("stat_error", by=uid, extra={
        "error": str(e),
        "command": "stat"
    })
    await message.reply_text(
        "❌ **Error Collecting Statistics**\n\n"
        "An error occurred. Please try again or contact support."
    )
    return
```

## 📝 Updated ADMIN_HELP

```python
ADMIN_HELP = """
👑 Admin Commands

📊 Statistics & Analytics
/stat                      - Comprehensive bot statistics dashboard
  • Full analytics across all categories
  • Export to JSON or CSV
  • Real-time data collection
  • Visual charts and metrics

/quickstat                 - Quick statistics summary
  • Essential metrics only
  • Fast response time
  • Perfect for quick checks

[... rest of admin help ...]
"""
```

## 🚀 Implementation Checklist

- [ ] Create `collect_comprehensive_stats()` function
- [ ] Create `collect_quick_stats()` function  
- 