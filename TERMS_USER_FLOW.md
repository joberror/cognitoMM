# Terms Acceptance User Flow

## Visual Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER STARTS BOT                         │
│                         Sends: /start                           │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │  Is User       │
                    │  Banned?       │
                    └────┬───────┬───┘
                         │       │
                    YES  │       │  NO
                         │       │
                         ▼       ▼
                    ┌────────┐  ┌──────────────────┐
                    │ Show   │  │ Has User Already │
                    │ Banned │  │ Accepted Terms?  │
                    │ Message│  └────┬─────────┬───┘
                    └────────┘       │         │
                                YES  │         │  NO
                                     │         │
                                     ▼         ▼
                        ┌──────────────────┐  ┌─────────────────────┐
                        │ Show Welcome     │  │ Load Terms from     │
                        │ Back Message     │  │ TERMS_AND_PRIVACY.md│
                        │                  │  └──────────┬──────────┘
                        │ "Welcome back!"  │             │
                        │ Use /help        │             ▼
                        └──────────────────┘  ┌─────────────────────┐
                                              │ Display Full Terms  │
                                              │ with Markdown       │
                                              │ Formatting          │
                                              └──────────┬──────────┘
                                                         │
                                                         ▼
                                              ┌─────────────────────┐
                                              │ Show Two Buttons:   │
                                              │ ✅ Yes, I Agree     │
                                              │ ❌ Decline          │
                                              └──────┬──────────┬───┘
                                                     │          │
                                          ACCEPT     │          │  DECLINE
                                                     │          │
                                                     ▼          ▼
                                    ┌──────────────────────┐  ┌──────────────────┐
                                    │ Update Database:     │  │ Update Message:  │
                                    │ terms_accepted=true  │  │ "Terms Declined" │
                                    │ terms_accepted_at=   │  │                  │
                                    │ current_timestamp    │  │ "Cannot use bot  │
                                    └──────────┬───────────┘  │ without terms"   │
                                               │              └──────────────────┘
                                               ▼                       │
                                    ┌──────────────────────┐           │
                                    │ Log Action:          │           │
                                    │ "terms_accepted"     │           │
                                    └──────────┬───────────┘           │
                                               │                       │
                                               ▼                       │
                                    ┌──────────────────────┐           │
                                    │ Show Success:        │           │
                                    │ "Terms Accepted!"    │           │
                                    │ "Use /help"          │           │
                                    └──────────┬───────────┘           │
                                               │                       │
                                               ▼                       ▼
                                    ┌──────────────────────┐  ┌──────────────────┐
                                    │ USER CAN NOW USE     │  │ USER BLOCKED     │
                                    │ ALL BOT FEATURES     │  │ FROM BOT         │
                                    └──────────────────────┘  └──────────────────┘
```

---

## Command Execution Flow (After /start)

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER SENDS ANY COMMAND                       │
│              (e.g., /search, /help, /metadata)                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │  Is Command    │
                    │  /start?       │
                    └────┬───────┬───┘
                         │       │
                    YES  │       │  NO
                         │       │
                         ▼       ▼
                    ┌────────┐  ┌──────────────────┐
                    │ Execute│  │  Is User         │
                    │ /start │  │  Banned?         │
                    │ Flow   │  └────┬─────────┬───┘
                    └────────┘       │         │
                                YES  │         │  NO
                                     │         │
                                     ▼         ▼
                        ┌──────────────────┐  ┌─────────────────────┐
                        │ Show Banned      │  │ Has User Accepted   │
                        │ Message & STOP   │  │ Terms?              │
                        └──────────────────┘  └────┬────────────┬───┘
                                                   │            │
                                              YES  │            │  NO
                                                   │            │
                                                   ▼            ▼
                                    ┌──────────────────────┐  ┌──────────────────┐
                                    │ EXECUTE COMMAND      │  │ Show Message:    │
                                    │                      │  │ "Must accept     │
                                    │ (Search, Help, etc.) │  │ terms first"     │
                                    └──────────────────────┘  │                  │
                                                              │ "Use /start"     │
                                                              └──────────────────┘
```

---

## Callback Query Flow (Button Clicks)

```
┌─────────────────────────────────────────────────────────────────┐
│                  USER CLICKS INLINE BUTTON                      │
│           (e.g., Get File, Pagination, etc.)                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │  Is Callback   │
                    │  terms#accept  │
                    │  or decline?   │
                    └────┬───────┬───┘
                         │       │
                    YES  │       │  NO
                         │       │
                         ▼       ▼
            ┌──────────────────┐  ┌──────────────────┐
            │ Handle Terms     │  │  Is User Admin?  │
            │ Acceptance       │  └────┬─────────┬───┘
            │ (See /start flow)│       │         │
            └──────────────────┘  YES  │         │  NO
                                       │         │
                                       ▼         ▼
                        ┌──────────────────┐  ┌─────────────────────┐
                        │ EXECUTE CALLBACK │  │ Has User Accepted   │
                        │ (Admin bypass)   │  │ Terms?              │
                        └──────────────────┘  └────┬────────────┬───┘
                                                   │            │
                                              YES  │            │  NO
                                                   │            │
                                                   ▼            ▼
                                    ┌──────────────────────┐  ┌──────────────────┐
                                    │ EXECUTE CALLBACK     │  │ Show Alert:      │
                                    │                      │  │ "Must accept     │
                                    │ (Send file, etc.)    │  │ terms first"     │
                                    └──────────────────────┘  └──────────────────┘
```

---

## Inline Query Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                  USER TYPES INLINE QUERY                        │
│              (@botname search term)                             │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │  Is User       │
                    │  Admin?        │
                    └────┬───────┬───┘
                         │       │
                    YES  │       │  NO
                         │       │
                         ▼       ▼
            ┌──────────────────┐  ┌──────────────────┐
            │ EXECUTE SEARCH   │  │ Has User Accepted│
            │ (Admin bypass)   │  │ Terms?           │
            └──────────────────┘  └────┬─────────┬───┘
                                       │         │
                                  YES  │         │  NO
                                       │         │
                                       ▼         ▼
                        ┌──────────────────┐  ┌─────────────────────┐
                        │ EXECUTE SEARCH   │  │ Return Single Result│
                        │                  │  │ "Terms Required"    │
                        │ Show Results     │  │                     │
                        └──────────────────┘  │ "Use /start"        │
                                              └─────────────────────┘
```

---

## Database State Transitions

```
NEW USER (No database record)
    │
    │ /start command
    ▼
USER RECORD CREATED
{
  user_id: 123456789,
  last_seen: <timestamp>,
  terms_accepted: false  // Default
}
    │
    │ User clicks "Yes, I Agree"
    ▼
TERMS ACCEPTED
{
  user_id: 123456789,
  last_seen: <timestamp>,
  terms_accepted: true,
  terms_accepted_at: <timestamp>
}
    │
    │ User can now use all features
    ▼
ACTIVE USER
- Can search movies
- Can request files
- Can use inline queries
- All features unlocked
```

---

## Admin Privilege Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         ADMIN USER                              │
│              (user_id in ADMINS env or role=admin)              │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │  ALL CHECKS    │
                    │  BYPASSED      │
                    └────────┬───────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ Terms Check:   │
                    │ SKIPPED        │
                    └────────┬───────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ Access Control:│
                    │ GRANTED        │
                    └────────┬───────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ FULL ACCESS    │
                    │ TO ALL FEATURES│
                    └────────────────┘
```

---

## Error Handling Flow

```
┌─────────────────────────────────────────────────────────────────┐
│              TERMS FILE LOADING ERROR                           │
│         (TERMS_AND_PRIVACY.md not found or corrupt)             │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ Show Error:    │
                    │ "Unable to load│
                    │ terms"         │
                    └────────┬───────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ Log Error to   │
                    │ Console        │
                    └────────┬───────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ User Cannot    │
                    │ Accept Terms   │
                    └────────┬───────┘
                             │
                             ▼
                    ┌────────────────┐
                    │ Admin Must Fix │
                    │ Terms File     │
                    └────────────────┘
```

---

## Key Decision Points

1. **Is user banned?** → YES: Block access | NO: Continue
2. **Is command /start?** → YES: Show terms flow | NO: Check acceptance
3. **Has accepted terms?** → YES: Allow access | NO: Block with message
4. **Is user admin?** → YES: Bypass all checks | NO: Enforce checks
5. **Terms file exists?** → YES: Load and display | NO: Show error

---

## User Experience Summary

### First Visit:
1. User sends `/start`
2. Sees full terms and privacy policy
3. Must click "Yes, I Agree" to proceed
4. Gets confirmation and can use bot

### Subsequent Visits:
1. User sends `/start`
2. Sees "Welcome back!" message
3. Can immediately use all features

### Without Acceptance:
1. User tries any command
2. Gets blocked with message
3. Directed to use `/start` to accept terms

