# Quick Start Guide - Request Feature

## For Users

### How to Request a Movie or Series

1. **Start the request**:

   ```
   /request
   ```

2. **Read the warning**: Make sure to search the database first!

3. **Follow the prompts**:

   - **Step 1**: Type `Movie` or `Series`
   - **Step 2**: Enter the title (e.g., `Inception`)
   - **Step 3**: Enter the year (e.g., `2010`)

4. **Select from TMDb results**:

   - Bot searches TMDb and shows top 5 results
   - Type the number (1-5) to select
   - Or type `SKIP` to continue without IMDB link

5. **Receive confirmation**:
   - Queue position
   - Remaining request slots
   - Notification when fulfilled

### Important Limits

- **Maximum 3 pending requests** at any time
- **1 request per day** per user
- **20 requests per day** globally (all users)

### Tips

- ✅ You can type `CANCEL` at any step to abort
- ✅ IMDB link is optional but recommended
- ✅ You'll be notified if a similar request already exists
- ✅ You'll receive a notification when your request is fulfilled

## For Admins

### How to View Requests

1. **View the request list**:

   ```
   /request_list
   ```

2. **Navigate the list**:
   - Use `← Prev` and `Next →` buttons to navigate pages
   - 9 requests shown per page

### How to Fulfill Requests

**Option 1: Mark Single Request**

- Click the `Done [#]` button next to the request
- User is automatically notified

**Option 2: Mark All Requests**

- Click the `Mark All Done` button
- All users are automatically notified

### Request Information Displayed

Each request shows:

- `[M]` = Movie, `[S]` = Series
- Title and year
- Username and user ID
- Request date (YYYY-MM-DD HH:MM)
- IMDB link (if provided)

### Example Display

```
Request List - Page 1/2
Total Pending: 12
==================================================

#1 [M] Inception (2010)
    User: john_doe (ID: 123456)
    Date: 2024-01-15 14:30
    IMDB: https://www.imdb.com/title/tt1375666/

#2 [S] Breaking Bad (2008)
    User: jane_smith (ID: 789012)
    Date: 2024-01-15 15:45

[Done [1]] [Done [2]] [Done [3]]
[← Prev] [Mark All Done] [Next →]
```

## Testing

### Run the Test Suite

```bash
python tests/test_request_feature.py
```

This validates:

- IMDB link validation
- Rate limiting
- Duplicate detection

### Manual Testing Checklist

**User Tests**:

- [ ] Submit a movie request
- [ ] Submit a series request
- [ ] Try to submit 4th request (should fail)
- [ ] Try to submit 2nd request same day (should fail)
- [ ] Submit duplicate request (should warn)
- [ ] Cancel a request mid-flow
- [ ] Submit request with IMDB link
- [ ] Submit request without IMDB link

**Admin Tests**:

- [ ] View request list
- [ ] Navigate between pages
- [ ] Mark single request as done
- [ ] Verify user receives notification
- [ ] Mark all requests as done
- [ ] Verify all users receive notifications

## Troubleshooting

### User Issues

**"Request Limit Reached"**

- You have 3 pending requests
- Wait for admin to fulfill some requests

**"Daily Limit Reached"**

- You already made a request today
- Try again tomorrow (24 hours from last request)

**"Global Daily Limit Reached"**

- Bot has reached 20 requests for today
- Try again tomorrow

**"Request timeout"**

- You took too long to respond
- Start over with `/request`

### Admin Issues

**"Request list expired"**

- The pagination data expired
- Use `/request_list` again

**"Request not found"**

- Request was already completed or deleted
- Refresh with `/request_list`

## Configuration

To modify rate limits, edit `features/request_management.py`:

```python
MAX_PENDING_REQUESTS_PER_USER = 3  # Max pending per user
MAX_REQUESTS_PER_DAY_PER_USER = 1  # Max per day per user
MAX_GLOBAL_REQUESTS_PER_DAY = 20   # Max per day globally
```

To modify duplicate detection threshold, edit:

```python
similarity = fuzz.ratio(title.lower(), req.get("title", "").lower())
if similarity >= 85:  # Change this threshold (0-100)
```

## Database Queries

### View all pending requests

```javascript
db.requests.find({ status: "pending" });
```

### View completed requests

```javascript
db.requests.find({ status: "completed" });
```

### View user's requests

```javascript
db.requests.find({ user_id: 123456 });
```

### Count pending requests

```javascript
db.requests.countDocuments({ status: "pending" });
```

### View user limits

```javascript
db.user_request_limits.find({ user_id: 123456 });
```

## Support

For detailed documentation, see:

- `REQUEST_FEATURE.md` - Complete feature documentation
- `IMPLEMENTATION_SUMMARY.md` - Technical implementation details
- `tests/test_request_feature.py` - Test examples
