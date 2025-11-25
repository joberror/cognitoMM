"""
Statistics Module

This module contains statistics collection and formatting functions
for the /stat and /quickstat commands.
"""

import asyncio
import json
import csv
import io
import sys
import platform
from datetime import datetime, timezone, timedelta
from .database import (
    users_col, movies_col, channels_col, premium_users_col,
    requests_col, logs_col
)
from .config import BOT_START_TIME, client


async def collect_comprehensive_stats(admin_id=None):
    """Collect all bot statistics from database in real-time"""
    try:
        stats = {}
        
        # Collect bot information
        stats['bot_info'] = await collect_bot_info(admin_id)
        
        # Use asyncio.gather for parallel data collection
        results = await asyncio.gather(
            # User statistics
            users_col.count_documents({}),
            users_col.count_documents({"last_seen": {"$gte": datetime.now(timezone.utc) - timedelta(days=7)}}),
            users_col.count_documents({"role": "banned"}),
            users_col.count_documents({"role": "admin"}),
            premium_users_col.count_documents({}),
            
            # Content statistics
            movies_col.count_documents({}),
            movies_col.count_documents({"type": {"$regex": "^(movie|film)$", "$options": "i"}}),
            movies_col.count_documents({"type": {"$regex": "^(series|tv|show)$", "$options": "i"}}),
            
            # Channel statistics
            channels_col.count_documents({}),
            channels_col.count_documents({"enabled": True}),
            
            # Request statistics
            requests_col.count_documents({"status": "pending"}),
            requests_col.count_documents({"status": "completed"}),
            
            # Log statistics
            logs_col.count_documents({}),
            
            return_exceptions=True
        )
        
        # Unpack results
        (stats['total_users'], stats['active_users_7d'], stats['banned_users'], 
         stats['admin_users'], stats['premium_users'], stats['total_content'],
         stats['total_movies'], stats['total_series'], stats['total_channels'],
         stats['enabled_channels'], stats['pending_requests'], stats['completed_requests'],
         stats['total_logs']) = results
        
        # Quality distribution (aggregation with normalization)
        quality_pipeline = [
            {"$group": {"_id": "$quality", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        quality_dist_raw = await movies_col.aggregate(quality_pipeline).to_list(length=None)
        
        # Normalize qualities (merge case variations and separate Unknown)
        quality_map = {}
        unknown_count = 0
        for item in quality_dist_raw:
            quality = item['_id']
            count = item['count']
            
            if quality is None or (isinstance(quality, str) and quality.lower() == 'unknown'):
                unknown_count += count
            else:
                # Normalize to uppercase
                normalized = quality.upper() if quality else 'UNKNOWN'
                
                # Merge 2160P with 4K (prefer 4K)
                if normalized == '2160P':
                    normalized = '4K'
                
                quality_map[normalized] = quality_map.get(normalized, 0) + count
        
        # Sort by count and create final list
        quality_dist = [{'_id': k, 'count': v} for k, v in sorted(quality_map.items(), key=lambda x: x[1], reverse=True)]
        
        # Add Unknown at the end if it exists
        if unknown_count > 0:
            quality_dist.append({'_id': 'Unknown', 'count': unknown_count})
        
        stats['quality_distribution'] = quality_dist[:10]  # Top 10
        
        # Year distribution (top 10 years, excluding future years)
        current_year = datetime.now(timezone.utc).year
        year_pipeline = [
            {"$match": {"year": {"$ne": None, "$gt": 0, "$lte": current_year}}},
            {"$group": {"_id": "$year", "count": {"$sum": 1}}},
            {"$sort": {"_id": -1}},
            {"$limit": 10}
        ]
        year_dist = await movies_col.aggregate(year_pipeline).to_list(length=10)
        stats['year_distribution'] = year_dist
        
        # Channel file counts
        channel_pipeline = [
            {"$group": {"_id": "$channel_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]
        channel_dist = await movies_col.aggregate(channel_pipeline).to_list(length=10)
        stats['channel_distribution'] = channel_dist
        
        # Get channel titles
        channel_titles = {}
        for ch_stat in channel_dist:
            ch_doc = await channels_col.find_one({"channel_id": ch_stat['_id']})
            if ch_doc:
                channel_titles[ch_stat['_id']] = ch_doc.get('channel_title', 'Unknown')
        stats['channel_titles'] = channel_titles
        
        # Top searches and search statistics
        search_pipeline = [
            {"$unwind": "$search_history"},
            {"$group": {"_id": "$search_history.q", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ]
        top_searches = await users_col.aggregate(search_pipeline).to_list(length=10)
        stats['top_searches'] = top_searches
        
        # Total search count and calculate average per day
        total_searches_pipeline = [
            {"$unwind": "$search_history"},
            {"$count": "total"}
        ]
        total_searches_result = await users_col.aggregate(total_searches_pipeline).to_list(length=1)
        total_searches = total_searches_result[0]['total'] if total_searches_result else 0
        stats['total_searches'] = total_searches
        
        # Calculate average searches per day (based on actual search history dates)
        if total_searches > 0:
            # Get earliest and latest search timestamps
            search_date_pipeline = [
                {"$unwind": "$search_history"},
                {"$group": {
                    "_id": None,
                    "earliest": {"$min": "$search_history.ts"},
                    "latest": {"$max": "$search_history.ts"}
                }}
            ]
            date_result = await users_col.aggregate(search_date_pipeline).to_list(length=1)
            
            if date_result:
                earliest = date_result[0].get('earliest')
                latest = date_result[0].get('latest')
                
                if earliest and latest:
                    # Calculate days between first and last search
                    time_span = (latest - earliest).total_seconds()
                    days_span = max(1, time_span / 86400)  # At least 1 day to avoid division by zero
                    stats['avg_searches_per_day'] = total_searches / days_span
                    stats['search_date_range'] = {
                        'earliest': earliest.isoformat(),
                        'latest': latest.isoformat(),
                        'days_span': days_span
                    }
                else:
                    stats['avg_searches_per_day'] = 0
            else:
                stats['avg_searches_per_day'] = 0
        else:
            stats['avg_searches_per_day'] = 0
        
        # Recent searches (last 20)
        recent_pipeline = [
            {"$unwind": "$search_history"},
            {"$sort": {"search_history.ts": -1}},
            {"$limit": 20},
            {"$project": {"query": "$search_history.q", "timestamp": "$search_history.ts"}}
        ]
        recent_searches = await users_col.aggregate(recent_pipeline).to_list(length=20)
        stats['recent_searches'] = recent_searches
        
        # Premium users with days remaining
        premium_users = await premium_users_col.find({}).to_list(length=100)
        premium_details = []
        premium_less_30 = 0
        premium_more_30 = 0
        
        for pu in premium_users:
            expires_at = pu.get('expires_at')
            if expires_at:
                days_remaining = (expires_at - datetime.now(timezone.utc)).days
                days_remaining = max(0, days_remaining)
                premium_details.append({
                    'user_id': pu.get('user_id'),
                    'days_remaining': days_remaining
                })
                
                # Count by expiry period
                if days_remaining <= 30:
                    premium_less_30 += 1
                else:
                    premium_more_30 += 1
        
        stats['premium_details'] = premium_details
        stats['premium_less_30_days'] = premium_less_30
        stats['premium_more_30_days'] = premium_more_30
        
        # Indexing statistics
        from .indexing import indexing_stats
        stats['indexing_stats'] = indexing_stats.copy()
        
        # Database size estimation (count-based)
        stats['db_estimated_size'] = (
            stats['total_content'] * 1024 +  # ~1KB per content entry
            stats['total_users'] * 512 +      # ~512B per user
            stats['total_logs'] * 256         # ~256B per log
        )
        
        # Timestamp
        stats['generated_at'] = datetime.now(timezone.utc).isoformat()
        
        return stats
        
    except Exception as e:
        print(f"❌ Error collecting stats: {e}")
        return None


async def collect_quick_stats():
    """Collect essential statistics for quick summary"""
    try:
        results = await asyncio.gather(
            users_col.count_documents({}),
            movies_col.count_documents({}),
            channels_col.count_documents({}),
            premium_users_col.count_documents({}),
            requests_col.count_documents({"status": "pending"}),
            users_col.count_documents({"last_seen": {"$gte": datetime.now(timezone.utc) - timedelta(days=7)}}),
            return_exceptions=True
        )
        
        return {
            'total_users': results[0],
            'total_content': results[1],
            'total_channels': results[2],
            'premium_users': results[3],
            'pending_requests': results[4],
            'active_users_7d': results[5],
            'generated_at': datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        print(f"❌ Error collecting quick stats: {e}")
        return None


def create_progress_bar(percentage, length=10):
    """Create a visual progress bar"""
    filled = int(length * percentage / 100)
    bar = "█" * filled + "░" * (length - filled)
    return f"{bar} {percentage:.1f}%"


async def collect_bot_info(admin_id=None):
    """Collect bot information including uptime and system details"""
    try:
        bot_info = {}
        
        # Admin who invoked the command
        if admin_id:
            bot_info['invoked_by_admin_id'] = admin_id
            # Try to get admin username from database
            try:
                from .database import users_col
                admin_doc = await users_col.find_one({"user_id": admin_id})
                if admin_doc:
                    bot_info['invoked_by_username'] = admin_doc.get('username') or f"User_{admin_id}"
                else:
                    bot_info['invoked_by_username'] = f"User_{admin_id}"
            except:
                bot_info['invoked_by_username'] = f"User_{admin_id}"
        
        # Calculate uptime
        uptime_seconds = (datetime.now(timezone.utc) - BOT_START_TIME).total_seconds()
        bot_info['uptime_seconds'] = uptime_seconds
        bot_info['uptime_formatted'] = format_uptime(uptime_seconds)
        bot_info['start_time'] = BOT_START_TIME.isoformat()
        
        # DIAGNOSTIC: Check client state
        from . import config
        actual_client = config.client
        print(f"🔍 [DIAGNOSTIC] Client check in collect_bot_info:")
        print(f"   - Imported client is None: {client is None}")
        print(f"   - config.client is None: {actual_client is None}")
        print(f"   - Client type: {type(actual_client)}")
        
        # Get bot details from Telegram - use fresh reference from config
        if actual_client:
            try:
                print(f"🔍 [DIAGNOSTIC] Attempting to get bot info from Telegram...")
                me = await actual_client.get_me()
                print(f"✅ [DIAGNOSTIC] Successfully got bot info: @{me.username}")
                bot_info['bot_username'] = me.username
                bot_info['bot_id'] = me.id
                bot_info['bot_name'] = me.first_name
                bot_info['bot_dc_id'] = me.dc_id if hasattr(me, 'dc_id') else None
            except Exception as e:
                print(f"⚠️ Could not get bot info from Telegram: {e}")
                import traceback
                print(f"🔍 [DIAGNOSTIC] Full traceback:")
                traceback.print_exc()
                bot_info['bot_username'] = 'Unknown'
                bot_info['bot_id'] = 'Unknown'
                bot_info['bot_name'] = 'Unknown'
        else:
            print(f"❌ [DIAGNOSTIC] Client is None - cannot fetch bot info")
            bot_info['bot_username'] = 'Unknown (No Client)'
            bot_info['bot_id'] = 'Unknown (No Client)'
            bot_info['bot_name'] = 'Unknown (No Client)'
        
        # System information
        bot_info['python_version'] = sys.version.split()[0]
        bot_info['platform'] = platform.system()
        bot_info['platform_release'] = platform.release()
        bot_info['architecture'] = platform.machine()
        
        return bot_info
    except Exception as e:
        print(f"❌ Error collecting bot info: {e}")
        return {
            'uptime_seconds': 0,
            'uptime_formatted': 'Unknown',
            'bot_username': 'Unknown',
            'bot_id': 'Unknown'
        }


def format_uptime(seconds):
    """Format uptime in human-readable format"""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")
    
    return " ".join(parts)


def format_number(num):
    """Format number with commas"""
    return f"{num:,}" if num else "0"


def format_percentage(part, total):
    """Calculate and format percentage"""
    if total == 0:
        return "0.0%"
    return f"{(part / total * 100):.1f}%"


def format_file_size_stat(bytes_size):
    """Format byte size to human readable"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"


def format_stats_output(stats):
    """Format statistics into a beautiful dashboard"""
    output = "```\n"
    output += "╔════════════════════════════════════════════════╗\n"
    output += "║       🎬 BOT STATISTICS DASHBOARD 📊          ║\n"
    output += "╚════════════════════════════════════════════════╝\n\n"
    
    # === BOT INFORMATION ===
    bot_info = stats.get('bot_info', {})
    if bot_info:
        output += "┌─────────────────────────────────────────────┐\n"
        output += "│  🤖 BOT INFORMATION                         │\n"
        output += "└─────────────────────────────────────────────┘\n\n"
        
        output += f"Bot Name:           {bot_info.get('bot_name', 'Unknown')}\n"
        output += f"Username:           @{bot_info.get('bot_username', 'Unknown')}\n"
        output += f"Bot ID:             {bot_info.get('bot_id', 'Unknown')}\n"
        
        if bot_info.get('bot_dc_id'):
            output += f"Data Center:        DC-{bot_info.get('bot_dc_id')}\n"
        
        output += f"\nUptime:             {bot_info.get('uptime_formatted', 'Unknown')}\n"
        
        start_time = bot_info.get('start_time', '')
        if start_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                start_formatted = start_dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                output += f"Started:            {start_formatted}\n"
            except:
                pass
        
        output += f"\nPython:             {bot_info.get('python_version', 'Unknown')}\n"
        output += f"Platform:           {bot_info.get('platform', 'Unknown')} {bot_info.get('platform_release', '')}\n"
        output += f"Architecture:       {bot_info.get('architecture', 'Unknown')}\n"
        
        # Admin who invoked
        if bot_info.get('invoked_by_admin_id'):
            output += f"\nInvoked by:         {bot_info.get('invoked_by_username', 'Unknown')} (ID: {bot_info.get('invoked_by_admin_id')})\n"
        
        output += "\n"
    
    # === USER STATISTICS ===
    output += "┌─────────────────────────────────────────────┐\n"
    output += "│  👥 USER STATISTICS                         │\n"
    output += "└─────────────────────────────────────────────┘\n\n"
    
    total_users = stats.get('total_users', 0)
    active_users = stats.get('active_users_7d', 0)
    banned_users = stats.get('banned_users', 0)
    admin_users = stats.get('admin_users', 0)
    premium_users = stats.get('premium_users', 0)
    
    output += f"Total Users:        {format_number(total_users)}\n"
    output += f"Active (7d):        {format_number(active_users)} ({format_percentage(active_users, total_users)})\n"
    output += f"Premium Users:      {format_number(premium_users)} ({format_percentage(premium_users, total_users)})\n"
    output += f"Admin Users:        {format_number(admin_users)}\n"
    output += f"Banned Users:       {format_number(banned_users)}\n\n"
    
    # Activity bar
    if total_users > 0:
        active_pct = (active_users / total_users) * 100
        output += f"Activity: {create_progress_bar(active_pct)}\n\n"
    
    # === CONTENT STATISTICS ===
    output += "┌─────────────────────────────────────────────┐\n"
    output += "│  🎥 CONTENT STATISTICS                      │\n"
    output += "└─────────────────────────────────────────────┘\n\n"
    
    total_content = stats.get('total_content', 0)
    total_movies = stats.get('total_movies', 0)
    total_series = stats.get('total_series', 0)
    
    output += f"Total Files:        {format_number(total_content)}\n"
    output += f"Movies:             {format_number(total_movies)} ({format_percentage(total_movies, total_content)})\n"
    output += f"Series/TV:          {format_number(total_series)} ({format_percentage(total_series, total_content)})\n\n"
    
    # Top qualities with progress bars
    quality_dist = stats.get('quality_distribution', [])
    if quality_dist:
        output += "Top Qualities:\n"
        for idx, q in enumerate(quality_dist[:5], 1):
            quality = q['_id'] or 'Unknown'
            count = q['count']
            pct = (count / total_content * 100) if total_content > 0 else 0
            bar = create_progress_bar(pct, length=8)
            output += f"  {idx}. {quality:12s} {bar}\n"
        output += "\n"
    
    # Top years with progress bars
    year_dist = stats.get('year_distribution', [])
    if year_dist:
        output += "Top Years:\n"
        for idx, y in enumerate(year_dist[:5], 1):
            year = y['_id']
            count = y['count']
            pct = (count / total_content * 100) if total_content > 0 else 0
            bar = create_progress_bar(pct, length=8)
            output += f"  {idx}. {year:6d}       {bar}\n"
        output += "\n"
    
    # === CHANNEL STATISTICS ===
    output += "┌─────────────────────────────────────────────┐\n"
    output += "│  📡 CHANNEL STATISTICS                      │\n"
    output += "└─────────────────────────────────────────────┘\n\n"
    
    total_channels = stats.get('total_channels', 0)
    enabled_channels = stats.get('enabled_channels', 0)
    
    output += f"Total Channels:     {format_number(total_channels)}\n"
    output += f"Enabled:            {format_number(enabled_channels)}\n"
    output += f"Disabled:           {format_number(total_channels - enabled_channels)}\n\n"
    
    # Top channels
    channel_dist = stats.get('channel_distribution', [])
    channel_titles = stats.get('channel_titles', {})
    if channel_dist:
        output += "Top Channels (by files):\n"
        for idx, ch in enumerate(channel_dist[:5], 1):
            ch_id = ch['_id']
            ch_name = channel_titles.get(ch_id, f"ID:{ch_id}")
            count = ch['count']
            # Add trophy icon for channel with most files (index 1)
            trophy = "🏆 " if idx == 1 else ""
            output += f"  {idx}. {trophy}{ch_name[:25]}: {format_number(count)}\n"
        output += "\n"
    
    # === SYSTEM STATISTICS ===
    output += "┌─────────────────────────────────────────────┐\n"
    output += "│  ⚙️  SYSTEM STATISTICS                       │\n"
    output += "└─────────────────────────────────────────────┘\n\n"
    
    db_size = stats.get('db_estimated_size', 0)
    indexing_stats_data = stats.get('indexing_stats', {})
    
    output += f"DB Est. Size:       {format_file_size_stat(db_size)}\n"
    output += f"Total Logs:         {format_number(stats.get('total_logs', 0))}\n\n"
    
    output += "Indexing Performance:\n"
    output += f"  Total Attempts:   {format_number(indexing_stats_data.get('total_attempts', 0))}\n"
    output += f"  Successful:       {format_number(indexing_stats_data.get('successful_inserts', 0))}\n"
    output += f"  Duplicates:       {format_number(indexing_stats_data.get('duplicate_errors', 0))}\n"
    output += f"  Errors:           {format_number(indexing_stats_data.get('other_errors', 0))}\n\n"
    
    # === ACTIVITY STATISTICS ===
    output += "┌─────────────────────────────────────────────┐\n"
    output += "│  🔍 ACTIVITY STATISTICS                     │\n"
    output += "└─────────────────────────────────────────────┘\n\n"
    
    pending_requests = stats.get('pending_requests', 0)
    completed_requests = stats.get('completed_requests', 0)
    total_searches = stats.get('total_searches', 0)
    avg_searches_per_day = stats.get('avg_searches_per_day', 0)
    
    output += f"Total Searches:     {format_number(total_searches)}\n"
    output += f"Avg Searches/Day:   {avg_searches_per_day:.1f}\n\n"
    
    output += f"Pending Requests:   {format_number(pending_requests)}\n"
    output += f"Completed Requests: {format_number(completed_requests)}\n\n"
    
    # Top searches
    top_searches = stats.get('top_searches', [])
    if top_searches:
        output += "Top Searches:\n"
        for idx, search in enumerate(top_searches[:5], 1):
            query = search['_id']
            count = search['count']
            output += f"  {idx}. {query[:30]}: {count}x\n"
        output += "\n"
    
    # === PREMIUM STATISTICS ===
    output += "┌─────────────────────────────────────────────┐\n"
    output += "│  ⭐ PREMIUM STATISTICS                      │\n"
    output += "└─────────────────────────────────────────────┘\n\n"
    
    premium_details = stats.get('premium_details', [])
    premium_less_30 = stats.get('premium_less_30_days', 0)
    premium_more_30 = stats.get('premium_more_30_days', 0)
    
    output += f"Total Premium:      {format_number(len(premium_details))}\n"
    output += f"≤ 30 Days:          {format_number(premium_less_30)}\n"
    output += f"> 30 Days:          {format_number(premium_more_30)}\n"
    
    if premium_details:
        # Calculate average days remaining
        avg_days = sum(p['days_remaining'] for p in premium_details) / len(premium_details)
        output += f"\nAvg Days Left:      {avg_days:.1f} days\n"
        
        # Group by days remaining
        expiring_soon = len([p for p in premium_details if p['days_remaining'] <= 7])
        expiring_month = len([p for p in premium_details if 7 < p['days_remaining'] <= 30])
        
        output += f"Expiring (7d):      {format_number(expiring_soon)}\n"
        output += f"Expiring (30d):     {format_number(expiring_month)}\n"
    
    output += "\n"
    
    # === FOOTER ===
    output += "╔════════════════════════════════════════════════╗\n"
    gen_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    output += f"║  Generated: {gen_time}           ║\n"
    output += "╚════════════════════════════════════════════════╝\n"
    output += "```"
    
    return output


def format_quick_stats_output(stats):
    """Format quick statistics into a compact summary"""
    output = "```\n"
    output += "═══════════════════════════════════════\n"
    output += "     🎬 QUICK STATS SUMMARY 📊\n"
    output += "═══════════════════════════════════════\n\n"
    
    total_users = stats.get('total_users', 0)
    total_content = stats.get('total_content', 0)
    total_channels = stats.get('total_channels', 0)
    premium_users = stats.get('premium_users', 0)
    pending_requests = stats.get('pending_requests', 0)
    active_users = stats.get('active_users_7d', 0)
    
    output += f"👥 Users:           {format_number(total_users)}\n"
    output += f"📊 Active (7d):     {format_number(active_users)}\n"
    output += f"⭐ Premium:         {format_number(premium_users)}\n"
    output += f"🎥 Content:         {format_number(total_content)}\n"
    output += f"📡 Channels:        {format_number(total_channels)}\n"
    output += f"📝 Requests:        {format_number(pending_requests)}\n\n"
    
    gen_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    output += f"Generated: {gen_time}\n"
    output += "═══════════════════════════════════════\n"
    output += "```"
    
    return output


async def export_stats_json(stats):
    """Export statistics to JSON format"""
    try:
        # Convert MongoDB objects to JSON-serializable format
        json_stats = json.loads(json.dumps(stats, default=str))
        json_str = json.dumps(json_stats, indent=2)
        return json_str
    except Exception as e:
        print(f"❌ Error exporting to JSON: {e}")
        return None


async def export_stats_csv(stats):
    """Export statistics to CSV format"""
    try:
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers
        writer.writerow(['Category', 'Metric', 'Value'])
        
        # Bot information
        bot_info = stats.get('bot_info', {})
        if bot_info:
            writer.writerow(['Bot', 'Bot Name', bot_info.get('bot_name', 'Unknown')])
            writer.writerow(['Bot', 'Username', bot_info.get('bot_username', 'Unknown')])
            writer.writerow(['Bot', 'Bot ID', bot_info.get('bot_id', 'Unknown')])
            writer.writerow(['Bot', 'Uptime', bot_info.get('uptime_formatted', 'Unknown')])
            writer.writerow(['Bot', 'Python Version', bot_info.get('python_version', 'Unknown')])
            writer.writerow(['Bot', 'Platform', bot_info.get('platform', 'Unknown')])
            if bot_info.get('invoked_by_admin_id'):
                writer.writerow(['Bot', 'Invoked By', f"{bot_info.get('invoked_by_username', 'Unknown')} (ID: {bot_info.get('invoked_by_admin_id')})"])
        
        # User statistics
        writer.writerow(['Users', 'Total Users', stats.get('total_users', 0)])
        writer.writerow(['Users', 'Active Users (7d)', stats.get('active_users_7d', 0)])
        writer.writerow(['Users', 'Premium Users', stats.get('premium_users', 0)])
        writer.writerow(['Users', 'Admin Users', stats.get('admin_users', 0)])
        writer.writerow(['Users', 'Banned Users', stats.get('banned_users', 0)])
        
        # Content statistics
        writer.writerow(['Content', 'Total Files', stats.get('total_content', 0)])
        writer.writerow(['Content', 'Movies', stats.get('total_movies', 0)])
        writer.writerow(['Content', 'Series', stats.get('total_series', 0)])
        
        # Channel statistics
        writer.writerow(['Channels', 'Total Channels', stats.get('total_channels', 0)])
        writer.writerow(['Channels', 'Enabled Channels', stats.get('enabled_channels', 0)])
        
        # Request statistics
        writer.writerow(['Requests', 'Pending', stats.get('pending_requests', 0)])
        writer.writerow(['Requests', 'Completed', stats.get('completed_requests', 0)])
        
        # System statistics
        writer.writerow(['System', 'DB Size (bytes)', stats.get('db_estimated_size', 0)])
        writer.writerow(['System', 'Total Logs', stats.get('total_logs', 0)])
        
        # Top searches
        top_searches = stats.get('top_searches', [])
        for idx, search in enumerate(top_searches[:10], 1):
            writer.writerow(['Top Searches', f"#{idx} {search['_id']}", search['count']])
        
        # Top qualities
        quality_dist = stats.get('quality_distribution', [])
        for idx, q in enumerate(quality_dist[:10], 1):
            writer.writerow(['Top Qualities', f"#{idx} {q['_id']}", q['count']])
        
        csv_str = output.getvalue()
        output.close()
        return csv_str
    except Exception as e:
        print(f"❌ Error exporting to CSV: {e}")
        return None