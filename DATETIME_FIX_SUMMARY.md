# Datetime Timezone Fix - /my_stat Command

## Problem
When invoking the `/my_stat` command, users were getting the following error:

**Bot Response:**
```
❌ Unable to retrieve statistics

Your user profile might not be fully initialized yet.
Try using the bot for a while and check back later
```

**Terminal Error:**
```
❌ Error collecting user stats: can't subtract offset-naive and offset-aware datetimes
TypeError: can't subtract offset-naive and offset-aware datetimes
```

## Root Cause
The error occurred because the code was trying to subtract timezone-naive datetime objects (stored in old database records) from timezone-aware datetime objects (`datetime.now(timezone.utc)`). Python's datetime library doesn't allow arithmetic operations between naive and aware datetime objects.

This typically happens when:
1. Old data was stored in the database before timezone support was added
2. Some code paths stored datetime objects without timezone information

## Solution
Added timezone awareness checks before all datetime arithmetic operations in `features/statistics.py`. The fix ensures that any timezone-naive datetime retrieved from the database is converted to timezone-aware (UTC) before performing arithmetic operations.

### Files Modified
- `features/statistics.py`

### Changes Made

1. **Fixed `collect_user_stats()` function** (Lines 788-803):
   - Added timezone check for `last_seen` before calculating activity score
   - Added timezone check for `joined_date` before calculating account age

2. **Fixed `format_user_stats_output()` function** (Lines 871-889):
   - Added timezone check for `last_seen` before formatting display

3. **Fixed `collect_comprehensive_stats()` function** (Lines 196-214):
   - Added timezone check for `expires_at` in premium user statistics

4. **Fixed `collect_user_stats()` function - Premium section** (Lines 737-747):
   - Added timezone check for `premium_expires` before calculating days remaining

### Code Pattern Applied
```python
# Before (caused error with naive datetimes)
days_since_last_seen = (datetime.now(timezone.utc) - stats['last_seen']).days

# After (handles both naive and aware datetimes)
last_seen = stats['last_seen']
if last_seen.tzinfo is None:
    # If naive, assume it's UTC
    last_seen = last_seen.replace(tzinfo=timezone.utc)

days_since_last_seen = (datetime.now(timezone.utc) - last_seen).days
```

## Testing
Created and ran a test to verify the fix handles both timezone-aware and timezone-naive datetime objects correctly. The test passed successfully.

## Impact
- Users can now successfully use the `/my_stat` command without errors
- The fix handles both old (naive) and new (aware) datetime data from the database
- No data migration required - the conversion happens at runtime

## Prevention
To prevent similar issues in the future:
1. Always store datetime objects with timezone information: `datetime.now(timezone.utc)`
2. When retrieving datetime from database, check for timezone awareness before arithmetic operations
3. Consider adding database migration to update old naive datetimes to timezone-aware format
