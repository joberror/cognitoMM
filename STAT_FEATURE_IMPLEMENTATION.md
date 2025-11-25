# Statistics Feature Implementation

## Overview
Comprehensive `/stat` and `/quickstat` commands for admin-only bot statistics with export functionality.

## Features Implemented

### 1. `/stat` Command - Full Dashboard
**Location**: `features/commands.py` (lines 2295-2358)

**Features**:
- **6 Statistics Categories**:
  1. 👥 User Statistics (total, active 7d, premium, admin, banned)
  2. 🎥 Content Statistics (movies, series, quality/year distributions)
  3. 📡 Channel Statistics (total, enabled, top channels by files)
  4. ⚙️ System Statistics (DB size, logs, indexing performance)
  5. 🔍 Activity Statistics (pending/completed requests, top searches)
  6. ⭐ Premium Statistics (total, avg days remaining, expiring soon)

- **Visual Elements**:
  - ASCII box-drawing characters for sections
  - Progress bars for activity metrics
  - Percentage calculations with formatted numbers
  - Top-N lists (top 5 qualities, years, channels, searches)

- **Export Functionality**:
  - JSON export (structured data)
  - CSV export (spreadsheet compatible)
  - Interactive buttons for download
  - Timestamped filenames

- **Performance Features**:
  - 30-second timeout protection
  - Parallel data collection using `asyncio.gather()`
  - Comprehensive error handling
  - Loading indicators

### 2. `/quickstat` Command - Quick Summary
**Location**: `features/commands.py` (lines 2361-2410)

**Features**:
- Essential metrics only (6 key stats)
- 10-second timeout for fast response
- Compact formatted output
- No export buttons (simplified)

### 3. Statistics Module
**Location**: `features/statistics.py`

**Functions**:
- `collect_comprehensive_stats()` - Gathers all bot data with parallel queries
- `collect_quick_stats()` - Collects essential metrics only
- `format_stats_output()` - Creates beautiful dashboard with ASCII art
- `format_quick_stats_output()` - Creates compact summary
- `export_stats_json()` - Exports to JSON format
- `export_stats_csv()` - Exports to CSV format
- `create_progress_bar()` - Visual progress bars
- `format_number()` - Number formatting with commas
- `format_percentage()` - Percentage calculations
- `format_file_size_stat()` - Human-readable file sizes

### 4. Callback Handlers
**Location**: `features/callbacks.py` (lines 1084-1157)

**Handlers**:
- `stats_export:json:{id}` - JSON export handler
- `stats_export:csv:{id}` - CSV export handler
- Session management with expiry
- Admin-only access control
- Comprehensive error handling

### 5. Command Registration
**Location**: `features/commands.py` (lines 127-129)

Commands registered in `handle_command()` router:
- `/stat` → `cmd_stat()`
- `/quickstat` → `cmd_quickstat()`

### 6. Admin Help Documentation
**Location**: `features/commands.py` (lines 160-167)

Updated `ADMIN_HELP` with new commands and feature descriptions.

## Statistics Collected

### User Metrics
- Total users count
- Active users (last 7 days)
- Banned users count
- Admin users count
- Premium users count
- Activity percentage with progress bar

### Content Metrics
- Total files indexed
- Movies count and percentage
- Series/TV count and percentage
- Top 5 qualities distribution
- Top 5 years distribution

### Channel Metrics
- Total channels
- Enabled/disabled channels
- Top 5 channels by file count
- Channel titles mapping

### System Metrics
- Estimated database size
- Total logs count
- Indexing performance:
  - Total attempts
  - Successful inserts
  - Duplicate errors
  - Other errors

### Activity Metrics
- Pending requests count
- Completed requests count
- Top 5 searches with frequency
- Recent searches (last 20)

### Premium Metrics
- Total premium users
- Average days remaining
- Users expiring within 7 days
- Users expiring within 30 days

## Visual Design

### Dashboard Layout
```
╔════════════════════════════════════════════════╗
║       🎬 BOT STATISTICS DASHBOARD 📊          ║
╚════════════════════════════════════════════════╝

┌─────────────────────────────────────────────┐
│  👥 USER STATISTICS                         │
└─────────────────────────────────────────────┘

Total Users:        1,234
Active (7d):        567 (45.9%)
Premium Users:      89 (7.2%)
Admin Users:        5
Banned Users:       12

Activity: ██████████░░░░░░ 45.9%

[Additional sections follow same pattern]
```

### Progress Bars
- Length: 10 characters
- Filled: █ (full block)
- Empty: ░ (light shade)
- Format: `██████████░░░░░░ 45.9%`

### Number Formatting
- Comma separators: `1,234,567`
- Percentages: `45.9%`
- File sizes: `123.45 MB`

## Export Formats

### JSON Export
```json
{
  "total_users": 1234,
  "active_users_7d": 567,
  "premium_users": 89,
  "total_content": 45678,
  "quality_distribution": [
    {"_id": "1080p", "count": 12345}
  ],
  "generated_at": "2025-11-25T01:00:00Z"
}
```

### CSV Export
```csv
Category,Metric,Value
Users,Total Users,1234
Users,Active Users (7d),567
Content,Total Files,45678
...
```

## Security

### Admin-Only Access
- Both commands require admin privileges
- Checked via `is_admin(uid)` function
- Returns "🚫 Admins only." for unauthorized users

### Export Security
- Session-based export (UUID tokens)
- User verification on callbacks
- Automatic session cleanup
- Timestamped filenames prevent overwrites

## Performance Optimization

### Parallel Data Collection
```python
results = await asyncio.gather(
    users_col.count_documents({}),
    movies_col.count_documents({}),
    channels_col.count_documents({}),
    # ... more queries
    return_exceptions=True
)
```

### Timeout Protection
- `/stat`: 30-second timeout
- `/quickstat`: 10-second timeout
- Graceful fallback messages

### Efficient Aggregations
- MongoDB aggregation pipelines
- Limited result sets (top 10)
- Indexed field queries

## Error Handling

### Comprehensive Try-Catch
- Database connection errors
- Timeout errors
- Data parsing errors
- Export generation errors

### User-Friendly Messages
- Loading indicators
- Timeout notifications
- Error explanations
- Retry suggestions

### Logging
- Action logging for audits
- Error logging with details
- Export tracking

## Usage Examples

### Basic Usage
```
Admin: /stat
Bot: [Shows loading message]
Bot: [Displays full dashboard with export buttons]

Admin: Clicks "📥 Export JSON"
Bot: [Sends JSON file as document]
```

### Quick Stats
```
Admin: /quickstat
Bot: [Shows compact summary in ~2 seconds]
```

## Testing Checklist

- [x] Command registration
- [x] Admin access control
- [x] Data collection functions
- [x] Output formatting
- [x] Export buttons display
- [x] JSON export handler
- [x] CSV export handler
- [ ] Test with empty database
- [ ] Test with large dataset
- [ ] Test timeout scenarios
- [ ] Test concurrent requests
- [ ] Test export downloads
- [ ] Test error scenarios

## Future Enhancements

### Potential Additions
1. **Caching**: Cache stats for 5-10 minutes to reduce DB load
2. **Scheduling**: Automatic daily/weekly stats reports
3. **Charts**: Image-based charts (matplotlib/plotly)
4. **Comparison**: Compare stats over time periods
5. **Filters**: Filter by date range, channel, etc.
6. **PDF Export**: Professional report generation
7. **Email Reports**: Send stats via email
8. **Real-time Updates**: Live dashboard with WebSocket

### Performance Improvements
1. **Database Indexes**: Ensure all queried fields are indexed
2. **Query Optimization**: Combine related queries
3. **Result Caching**: Redis cache for frequent queries
4. **Lazy Loading**: Load sections on demand

## Dependencies

### Existing
- `asyncio` - Async operations
- `datetime` - Timestamps
- `motor` - MongoDB async driver
- `hydrogram` - Telegram bot framework

### New
- `json` - JSON export
- `csv` - CSV export
- `io` - String buffer for CSV

## Files Modified

1. **features/statistics.py** (NEW) - 448 lines
   - Statistics collection and formatting functions

2. **features/commands.py** (MODIFIED)
   - Added `/stat` command handler (64 lines)
   - Added `/quickstat` command handler (49 lines)
   - Updated imports (7 lines)
   - Updated command router (2 lines)
   - Updated ADMIN_HELP (8 lines)

3. **features/callbacks.py** (MODIFIED)
   - Added export callback handlers (74 lines)

## Total Code Added
- **~642 lines** of new code
- **3 files** modified/created
- **2 commands** implemented
- **2 export formats** supported
- **6 statistics categories** included

## Conclusion

The statistics feature is fully implemented with:
✅ Comprehensive data collection
✅ Beautiful visual design
✅ Export functionality (JSON/CSV)
✅ Admin-only security
✅ Performance optimization
✅ Error handling
✅ Documentation

Ready for testing and deployment!