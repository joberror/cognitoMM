# Terms Acceptance - Quick Reference Card

## 🎯 At a Glance

### What Was Implemented
✅ Mandatory Terms of Use & Privacy Policy acceptance  
✅ First-time users must accept before using bot  
✅ Returning users see welcome message  
✅ Admins bypass requirement  
✅ All access points protected (commands, inline, callbacks)  

---

## 📱 User Experience

### New User
```
User: /start
Bot: [Shows full Terms & Privacy Policy]
     [✅ Yes, I Agree] [❌ Decline]

User: [Clicks "Yes, I Agree"]
Bot: ✅ Terms Accepted!
     You can now use all features.
     Use /help to see commands.
```

### Returning User
```
User: /start
Bot: 👋 Welcome back, [Name]!
     You're all set to use the MovieBot.
     Use /help to see available commands.
```

### Without Acceptance
```
User: /search Avengers
Bot: ⚠️ Terms Acceptance Required
     You must accept our Terms of Use first.
     Please use /start to view and accept.
```

---

## 🔧 Technical Details

### Database Fields
```javascript
{
  user_id: 123456789,
  terms_accepted: true,           // Boolean flag
  terms_accepted_at: ISODate(),   // Timestamp
  last_seen: ISODate(),
  role: "user"
}
```

### Key Functions
- `has_accepted_terms(user_id)` - Check if user accepted
- `load_terms_and_privacy()` - Load terms from file
- `check_terms_acceptance(message)` - Enforce on commands

### Access Control Points
1. **Command Handler** (Line 1237-1245)
   - Checks before executing any command except `/start`
   
2. **Callback Handler** (Line 1864-1927)
   - Handles acceptance buttons
   - Checks before processing other callbacks
   
3. **Inline Query Handler** (Line 3081-3118)
   - Checks before processing queries

---

## 📁 Files

### Created
- `TERMS_AND_PRIVACY.md` - The terms document (225 lines)
- `TERMS_IMPLEMENTATION.md` - Technical documentation
- `TERMS_USER_FLOW.md` - Visual flow diagrams
- `TESTING_GUIDE.md` - Comprehensive test plan
- `TERMS_QUICK_REFERENCE.md` - This file

### Modified
- `main.py` - All implementation code

---

## 🗄️ Database Queries

### Check User Status
```javascript
// Has user accepted?
db.users.findOne({user_id: 123456789})

// All users who accepted
db.users.find({terms_accepted: true})

// Users who haven't accepted
db.users.find({
  $or: [
    {terms_accepted: false},
    {terms_accepted: {$exists: false}}
  ]
})
```

### Check Logs
```javascript
// Recent acceptances
db.logs.find({action: "terms_accepted"})
  .sort({timestamp: -1})
  .limit(10)
```

### Force Re-acceptance (if terms change)
```javascript
// Reset all users
db.users.updateMany(
  {},
  {$set: {terms_accepted: false}}
)

// Reset specific user
db.users.updateOne(
  {user_id: 123456789},
  {$set: {terms_accepted: false}}
)
```

---

## 🔍 Testing Quick Commands

### Test New User Flow
1. Clear user record: `db.users.deleteOne({user_id: YOUR_ID})`
2. Send `/start` in Telegram
3. Click "✅ Yes, I Agree"
4. Verify access granted

### Test Blocking
1. Use account without acceptance
2. Try `/search test`
3. Should be blocked with message

### Test Admin Bypass
1. Use admin account
2. Try `/search test` without `/start`
3. Should work immediately

---

## 🐛 Troubleshooting

### Terms Not Showing
**Problem:** New user sees welcome instead of terms  
**Fix:** Clear user record from database
```javascript
db.users.deleteOne({user_id: USER_ID})
```

### Commands Not Blocked
**Problem:** User can use bot without accepting  
**Fix:** Check if user is admin
```javascript
// Check admin status
db.users.findOne({user_id: USER_ID})
// Should NOT have role: "admin"
// User ID should NOT be in ADMINS env variable
```

### Buttons Not Working
**Problem:** Clicking buttons does nothing  
**Fix:** Check bot logs for errors, restart bot

### File Not Found Error
**Problem:** "Unable to load terms" message  
**Fix:** Ensure `TERMS_AND_PRIVACY.md` exists in bot directory
```bash
ls -la TERMS_AND_PRIVACY.md
```

---

## 📊 Monitoring

### Check Acceptance Rate
```javascript
db.users.aggregate([
  {$group: {
    _id: "$terms_accepted",
    count: {$sum: 1}
  }}
])
```

### Daily Acceptances
```javascript
db.logs.aggregate([
  {$match: {action: "terms_accepted"}},
  {$group: {
    _id: {$dateToString: {format: "%Y-%m-%d", date: "$timestamp"}},
    count: {$sum: 1}
  }},
  {$sort: {_id: -1}}
])
```

---

## 🔄 Updating Terms

### To Update Content
1. Edit `TERMS_AND_PRIVACY.md`
2. Save file
3. No code changes needed
4. Bot loads updated content automatically

### To Force Re-acceptance
```javascript
// Option 1: Reset all users
db.users.updateMany({}, {$set: {terms_accepted: false}})

// Option 2: Add versioning (requires code change)
// Add TERMS_VERSION constant in main.py
// Update check to compare versions
```

---

## 🎨 Customization

### Change Button Text
Edit line ~1405 in `main.py`:
```python
InlineKeyboardButton("✅ Yes, I Agree", callback_data="terms#accept")
InlineKeyboardButton("❌ Decline", callback_data="terms#decline")
```

### Change Messages
Edit lines 1353-1429 in `main.py` (cmd_start function)

### Change Auto-Split Length
Edit line ~1395 in `main.py`:
```python
max_length = 4000  # Adjust this value
```

---

## 📞 Support

### Bot Information
- **Bot Username:** @CognitoMMBot
- **Bot Name:** Cognito
- **Bot ID:** 8336034036

### Files Location
- **Bot Root:** `/home/iamjoberror/myGit/cognitoMM`
- **Terms File:** `TERMS_AND_PRIVACY.md`
- **Main Code:** `main.py`

### Key Code Sections
- Terms helpers: Lines 693-749
- /start command: Lines 1353-1429
- Callback handler: Lines 1864-1927
- Command handler: Lines 1237-1245
- Inline handler: Lines 3081-3118

---

## ✅ Deployment Checklist

Before going live:
- [x] Bot running successfully
- [x] MongoDB connected
- [x] Terms file exists and is readable
- [ ] Test with new user account
- [ ] Test acceptance flow
- [ ] Test decline flow
- [ ] Test returning user
- [ ] Test admin bypass
- [ ] Test command blocking
- [ ] Test inline query blocking
- [ ] Verify database updates
- [ ] Check logs for errors

---

## 🚀 Current Status

**Bot Status:** ✅ Running  
**MongoDB:** ✅ Connected  
**Auto-Delete:** ✅ Active  
**Terms System:** ✅ Implemented  

**Ready for Testing!**

---

## 💡 Tips

1. **Test thoroughly** before announcing to users
2. **Monitor logs** for the first few hours
3. **Check database** to ensure acceptances are recorded
4. **Have backup** of database before forcing re-acceptance
5. **Communicate clearly** if you update terms and require re-acceptance

---

## 📈 Success Metrics

Track these to measure success:
- **Acceptance Rate:** % of users who accept vs decline
- **Time to Accept:** How long users take to decide
- **Drop-off Rate:** % who decline and never return
- **Re-acceptance:** If terms change, how many re-accept

---

## 🎉 You're All Set!

The Terms Acceptance system is fully implemented and ready to use.

**Next Steps:**
1. Review `TESTING_GUIDE.md` for detailed test scenarios
2. Test with a new user account
3. Verify all functionality works as expected
4. Monitor for any issues
5. Enjoy your legally protected bot! 🎬

---

**Questions?** Check the other documentation files:
- `TERMS_IMPLEMENTATION.md` - Technical details
- `TERMS_USER_FLOW.md` - Visual diagrams
- `TESTING_GUIDE.md` - Test scenarios

