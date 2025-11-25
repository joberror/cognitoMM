# Statistics Commands - Admin Guide

## Quick Reference

### `/stat` - Full Statistics Dashboard
**Access**: Admin only  
**Response Time**: 5-30 seconds (depending on data size)  
**Features**: Complete dashboard with 6 categories + export options

### `/quickstat` - Quick Summary
**Access**: Admin only  
**Response Time**: 1-10 seconds  
**Features**: Essential metrics only (fast)

## Command Details

### `/stat` Command

#### What It Shows
1. **👥 User Statistics**
   - Total users
   - Active users (last 7 days)
   - Premium users
   - Admin users
   - Banned users
   - Activity percentage with visual bar

2. **🎥 Content Statistics**
   - Total files
   - Movies count & percentage
   - Series count & percentage
   - Top 5 qualities (e.g., 1080p, 720p)
   - Top 5 years (most recent content)

3. **📡 Channel Statistics**
   - Total channels
   - Enabled/disabled channels
   - Top 5 channels by file count

4. **⚙️ System Statistics**
   - Database estimated size
   - Total logs
   - Indexing performance metrics
   - Success/error rates

5. **🔍 Activity Statistics**
   - Pending requests
   - Completed requests
   - Top 5 searches (most popular)

6. **⭐ Premium Statistics**
   - Total premium users
   - Average days remaining
   - Users expiring within 7 days
   - Users expiring within 30 days

#### Export Options
- **📥 Export JSON**: Download structured data for analysis
- **📥 Export CSV**: Download spreadsheet-compatible format

#### Example Output
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

[Additional sections...]
```

### `/quickstat` Command

#### What It Shows
- 👥 Total Users
- 📊 Active Users (7d)
- ⭐ Premium Users
- 🎥 Total Content
- 📡 Total Channels
- 📝 Pending Requests

#### Example Output
```
═══════════════════════════════════════
     🎬 QUICK STATS SUMMARY 📊
═══════════════════════════════════════

👥 Users:           1,234
📊 Active (7d):     567
⭐ Premium:         89
🎥 Content:         45,678
📡 Channels:        12
📝 Requests:        23

Generated: 2025-11-25 01:00:00 UTC
═══════════════════════════════════════
```

## When to Use Which Command

### Use `/stat` when:
- ✅ You need comprehensive data
- ✅ You want to export data
- ✅ You're analyzing trends
- ✅ You're preparing reports
- ✅ You have time to wait (up to 30s)

### Use `/quickstat` when:
- ✅ You need quick overview
- ✅ You're checking basic metrics
- ✅ You want instant results
- ✅ You're on mobile/slow connection
- ✅ You don't need detailed breakdowns

## Export Guide

### JSON Export
**Best For**:
- API integration
- Data analysis tools
- Custom reporting
- Backup/archival

**Format**:
```json
{
  "total_users": 1234,
  "active_users_7d": 567,
  "premium_users": 89,
  "quality_distribution": [...]
}
```

### CSV Export
**Best For**:
- Excel/Google Sheets
- Quick analysis
- Sharing with non-technical staff
- Simple reporting

**Format**:
```csv
Category,Metric,Value
Users,Total Users,1234
Users,Active Users,567
```

## Tips & Best Practices

### Performance Tips
1. **Use `/quickstat` first** for quick checks
2. **Use `/stat` when needed** for detailed analysis
3. **Export during low-traffic** times if possible
4. **Cache results** if analyzing repeatedly

### Monitoring Suggestions
1. **Daily**: Use `/quickstat` for health check
2. **Weekly**: Use `/stat` for trend analysis
3. **Monthly**: Export data for historical records
4. **Before decisions**: Full stats for informed choices

### Interpreting Metrics

#### Activity Rate
- **>50%**: Excellent engagement
- **30-50%**: Good engagement
- **<30%**: Consider re-engagement strategies

#### Content Balance
- **Healthy**: 60-70% movies, 30-40% series
- **Monitor**: Extreme imbalances

#### Premium Conversion
- **Good**: >5% premium rate
- **Average**: 2-5% premium rate
- **Low**: <2% (consider value proposition)

#### Request Queue
- **Healthy**: <50 pending requests
- **Monitor**: 50-100 pending
- **Action needed**: >100 pending

## Troubleshooting

### Command Not Working
**Issue**: "🚫 Admins only"  
**Solution**: You need admin privileges. Contact owner.

**Issue**: "⏰ Timeout"  
**Solution**: Database is slow. Try `/quickstat` or retry later.

**Issue**: "❌ Error"  
**Solution**: Check bot logs. May need database maintenance.

### Export Not Working
**Issue**: No file received  
**Solution**: Check bot permissions, try again.

**Issue**: File is corrupted  
**Solution**: Contact developer, database may have issues.

## Security Notes

### Access Control
- ✅ Commands are **admin-only**
- ✅ Export buttons are **admin-only**
- ✅ All actions are **logged**
- ✅ Sessions **expire** after use

### Data Privacy
- Stats are **aggregated**
- No personal user data in exports
- User IDs in premium details (not exported)
- All exports are **timestamped**

## Support

### For Help
1. Check this guide first
2. Review implementation docs
3. Check bot logs
4. Contact developer

### Feature Requests
- Additional metrics
- New export formats
- Scheduled reports
- Custom dashboards

---

**Version**: 1.0  
**Last Updated**: 2025-11-25  
**Author**: Kilo Code