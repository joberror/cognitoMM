# Terms Acceptance Testing Guide

## 🧪 Comprehensive Testing Checklist

This guide will help you test the Terms of Use and Privacy Policy acceptance system.

---

## ✅ Pre-Testing Setup

### 1. Bot Status
- [x] Bot is running: `@CognitoMMBot`
- [x] Bot ID: `8336034036`
- [x] MongoDB connected
- [x] Auto-delete monitor active

### 2. Test Accounts Needed
You'll need:
1. **New user account** (never used the bot before)
2. **Existing user account** (has used the bot before)
3. **Admin account** (your account or another admin)

---

## 📝 Test Scenarios

### Test 1: New User - First Time Experience

**Objective:** Verify new users see terms and must accept them

**Steps:**
1. Open Telegram with a **new account** (or clear your user record from database)
2. Search for `@CognitoMMBot`
3. Send `/start` command

**Expected Results:**
- ✅ Bot displays full Terms of Use and Privacy Policy
- ✅ Message is formatted with markdown (headers, bold text, etc.)
- ✅ Two buttons appear at the bottom:
  - "✅ Yes, I Agree"
  - "❌ Decline"
- ✅ No other functionality is accessible yet

**Database Check:**
```javascript
// In MongoDB, check:
db.users.findOne({user_id: YOUR_USER_ID})
// Should show: terms_accepted: false or undefined
```

---

### Test 2: New User - Accept Terms

**Objective:** Verify accepting terms grants full access

**Steps:**
1. From Test 1, click "✅ Yes, I Agree" button

**Expected Results:**
- ✅ Message updates to show: "✅ Terms Accepted"
- ✅ Confirmation message appears: "Thank you for accepting..."
- ✅ Message includes: "Use /help to see available commands"
- ✅ Alert popup shows: "✅ Terms accepted! Welcome to MovieBot!"

**Database Check:**
```javascript
db.users.findOne({user_id: YOUR_USER_ID})
// Should show:
// {
//   user_id: YOUR_USER_ID,
//   terms_accepted: true,
//   terms_accepted_at: ISODate("2025-01-..."),
//   last_seen: ISODate("2025-01-...")
// }
```

**Logs Check:**
```javascript
db.logs.find({action: "terms_accepted"}).sort({timestamp: -1}).limit(1)
// Should show the acceptance was logged
```

---

### Test 3: New User - Decline Terms

**Objective:** Verify declining terms blocks access

**Steps:**
1. Use a different new account
2. Send `/start`
3. Click "❌ Decline" button

**Expected Results:**
- ✅ Message updates to show: "❌ Terms Declined"
- ✅ Message explains: "You cannot use this bot without accepting the terms"
- ✅ Message suggests: "Use /start to view the terms again"
- ✅ Alert popup shows: "You must accept the terms to use this bot"

**Database Check:**
```javascript
db.users.findOne({user_id: YOUR_USER_ID})
// Should show: terms_accepted: false or undefined
```

---

### Test 4: Access Without Acceptance - Commands

**Objective:** Verify commands are blocked without terms acceptance

**Steps:**
1. From Test 3 (declined user), try these commands:
   - `/help`
   - `/search Avengers`
   - `/recent`
   - `/metadata Inception`

**Expected Results for EACH command:**
- ✅ Command is blocked
- ✅ Bot responds with: "⚠️ Terms Acceptance Required"
- ✅ Message says: "You must accept our Terms of Use and Privacy Policy"
- ✅ Message directs: "Please use /start to view and accept the terms"

---

### Test 5: Access Without Acceptance - Inline Queries

**Objective:** Verify inline queries are blocked without terms acceptance

**Steps:**
1. From Test 3 (declined user)
2. In any chat, type: `@CognitoMMBot Avengers`

**Expected Results:**
- ✅ Single result appears: "⚠️ Terms Acceptance Required"
- ✅ Description: "You must accept Terms of Use to use this bot"
- ✅ Clicking it shows message directing to `/start`

---

### Test 6: Access Without Acceptance - Callback Buttons

**Objective:** Verify callback buttons are blocked without terms acceptance

**Steps:**
1. From Test 3 (declined user)
2. If you have any old messages with buttons (pagination, get file, etc.), click them

**Expected Results:**
- ✅ Alert popup appears: "⚠️ You must accept the Terms of Use first. Use /start to accept."
- ✅ Button action does not execute

---

### Test 7: Returning User - Already Accepted

**Objective:** Verify users who already accepted don't see terms again

**Steps:**
1. Use account from Test 2 (accepted terms)
2. Send `/start` command again

**Expected Results:**
- ✅ Bot shows: "👋 Welcome back, [Name]!"
- ✅ Message says: "You're all set to use the MovieBot"
- ✅ Message includes: "Use /help to see available commands"
- ✅ NO terms displayed
- ✅ NO acceptance buttons shown

---

### Test 8: Returning User - Full Access

**Objective:** Verify accepted users have full bot access

**Steps:**
1. From Test 7, try various commands:
   - `/help`
   - `/search Avengers`
   - `/recent`
   - Inline query: `@CognitoMMBot Matrix`

**Expected Results:**
- ✅ All commands work normally
- ✅ Search returns results
- ✅ Inline queries work
- ✅ Buttons work (pagination, get file, etc.)
- ✅ No terms-related blocks

---

### Test 9: Admin Bypass

**Objective:** Verify admins can use bot without accepting terms

**Steps:**
1. Use an **admin account** (check ADMINS in .env or role=admin in database)
2. Ensure this admin has NOT accepted terms (or clear their acceptance)
3. Try commands WITHOUT using `/start`:
   - `/help`
   - `/search Inception`
   - `/channel_stats`
   - Inline query

**Expected Results:**
- ✅ All commands work immediately
- ✅ No terms acceptance required
- ✅ No blocking messages
- ✅ Admin has full access

**Note:** Admins still see terms if they use `/start`, but acceptance is optional.

---

### Test 10: Terms File Length Handling

**Objective:** Verify long terms are split correctly (if over 4000 chars)

**Current Status:**
- TERMS_AND_PRIVACY.md is 225 lines
- Estimated ~8000-10000 characters
- Should be split into 2-3 messages

**Steps:**
1. Use new account
2. Send `/start`

**Expected Results:**
- ✅ Terms are split into multiple messages
- ✅ First message(s) contain terms content
- ✅ Last message has the acceptance buttons
- ✅ All messages are readable and properly formatted
- ✅ No truncation or cut-off mid-sentence

---

### Test 11: Error Handling - Missing Terms File

**Objective:** Verify graceful error if terms file is missing

**Steps:**
1. Temporarily rename `TERMS_AND_PRIVACY.md` to `TERMS_AND_PRIVACY.md.backup`
2. Restart bot
3. Use new account and send `/start`

**Expected Results:**
- ✅ Bot shows: "❌ Error Loading Terms"
- ✅ Message says: "Unable to load Terms of Use and Privacy Policy"
- ✅ Message directs: "Please contact the administrator"
- ✅ No crash or exception
- ✅ Console shows error log

**Cleanup:**
4. Rename file back to `TERMS_AND_PRIVACY.md`
5. Restart bot

---

### Test 12: Re-acceptance After Decline

**Objective:** Verify users can accept after declining

**Steps:**
1. Use account from Test 3 (declined terms)
2. Send `/start` again
3. Click "✅ Yes, I Agree"

**Expected Results:**
- ✅ Terms displayed again
- ✅ Acceptance works normally
- ✅ Database updated with acceptance
- ✅ User now has full access

---

### Test 13: Database Persistence

**Objective:** Verify acceptance survives bot restart

**Steps:**
1. Use account that accepted terms
2. Note the user_id
3. Stop the bot (Ctrl+C)
4. Restart the bot
5. Send `/start` from same account

**Expected Results:**
- ✅ Bot shows "Welcome back" message
- ✅ No terms displayed
- ✅ User still has full access
- ✅ Database record intact

---

### Test 14: Concurrent Users

**Objective:** Verify multiple users can accept simultaneously

**Steps:**
1. Use 2-3 different new accounts
2. All send `/start` at roughly the same time
3. All click "✅ Yes, I Agree" within seconds of each other

**Expected Results:**
- ✅ All users see terms correctly
- ✅ All acceptances are recorded
- ✅ No database conflicts
- ✅ All users get confirmation
- ✅ All users have access

---

## 🔍 Database Verification Queries

### Check User Acceptance Status
```javascript
// Find users who accepted terms
db.users.find({terms_accepted: true})

// Find users who haven't accepted
db.users.find({$or: [{terms_accepted: false}, {terms_accepted: {$exists: false}}]})

// Count acceptance rate
db.users.aggregate([
  {$group: {
    _id: "$terms_accepted",
    count: {$sum: 1}
  }}
])
```

### Check Acceptance Logs
```javascript
// Recent acceptances
db.logs.find({action: "terms_accepted"}).sort({timestamp: -1}).limit(10)

// Acceptance count by date
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

## 🐛 Common Issues & Solutions

### Issue 1: Terms Not Displaying
**Symptoms:** `/start` shows welcome message instead of terms for new user
**Cause:** User record already exists with `terms_accepted: true`
**Solution:** 
```javascript
db.users.updateOne({user_id: YOUR_USER_ID}, {$set: {terms_accepted: false}})
// Or delete the user record
db.users.deleteOne({user_id: YOUR_USER_ID})
```

### Issue 2: Buttons Not Working
**Symptoms:** Clicking buttons does nothing
**Cause:** Callback handler not registered or error in handler
**Solution:** Check bot logs for errors, restart bot

### Issue 3: Commands Still Work Without Acceptance
**Symptoms:** User can use commands without accepting terms
**Cause:** User might be admin or check is bypassed
**Solution:** Verify user is not in ADMINS list, check `is_admin()` function

### Issue 4: Terms File Not Found
**Symptoms:** Error message when starting bot or using `/start`
**Cause:** `TERMS_AND_PRIVACY.md` missing or wrong location
**Solution:** Ensure file is in bot root directory, check file permissions

---

## 📊 Success Criteria

All tests should pass with these results:

- ✅ New users see terms on first `/start`
- ✅ Accepting terms grants full access
- ✅ Declining terms blocks access
- ✅ Returning users see welcome message
- ✅ Commands blocked without acceptance
- ✅ Inline queries blocked without acceptance
- ✅ Callback buttons blocked without acceptance
- ✅ Admins bypass terms requirement
- ✅ Long terms split correctly
- ✅ Error handling works
- ✅ Database persistence works
- ✅ Concurrent users handled correctly

---

## 🎯 Quick Test Script

For rapid testing, use this sequence:

```bash
# 1. Check bot is running
curl -s https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getMe

# 2. Test with new user
# - Send /start
# - Click "Yes, I Agree"
# - Send /help
# - Send /search test

# 3. Test with same user again
# - Send /start (should see welcome back)

# 4. Test admin bypass
# - Use admin account
# - Send /search test (without /start)
# - Should work immediately
```

---

## 📝 Test Results Template

Copy this template to record your test results:

```
## Test Results - [Date]

### Environment
- Bot: @CognitoMMBot
- MongoDB: Connected
- Test Accounts: 3 (new, existing, admin)

### Test Results
- [ ] Test 1: New User First Time - PASS/FAIL
- [ ] Test 2: Accept Terms - PASS/FAIL
- [ ] Test 3: Decline Terms - PASS/FAIL
- [ ] Test 4: Commands Blocked - PASS/FAIL
- [ ] Test 5: Inline Queries Blocked - PASS/FAIL
- [ ] Test 6: Callbacks Blocked - PASS/FAIL
- [ ] Test 7: Returning User - PASS/FAIL
- [ ] Test 8: Full Access - PASS/FAIL
- [ ] Test 9: Admin Bypass - PASS/FAIL
- [ ] Test 10: Message Splitting - PASS/FAIL
- [ ] Test 11: Error Handling - PASS/FAIL
- [ ] Test 12: Re-acceptance - PASS/FAIL
- [ ] Test 13: Persistence - PASS/FAIL
- [ ] Test 14: Concurrent Users - PASS/FAIL

### Issues Found
1. [Issue description]
2. [Issue description]

### Notes
[Any additional observations]
```

---

## 🚀 Ready to Test!

Your bot is running and ready for testing. Start with Test 1 and work through the checklist systematically.

Good luck! 🎉

