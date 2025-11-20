# Movie/Series Request Feature

## Overview

The request feature allows users to submit requests for movies or series that are not currently available in the bot's database. Admins can view, manage, and fulfill these requests through a dedicated interface.

## User Functionality

### `/request` Command

Users can submit requests for movies or series using the `/request` command.

#### Request Flow

1. **Invoke Command**: User types `/request`
2. **Warning**: Bot displays warning to check database first
3. **Interactive Prompts**: Bot guides user through the following steps:
   - **Step 1**: Content Type (Movie or Series)
   - **Step 2**: Title/Name
   - **Step 3**: Release Year
4. **TMDb Search**: Bot automatically searches TMDb and displays top 5 results
5. **Selection**: User selects the correct result from the list
6. **Validation**: Bot validates all inputs and checks for duplicates
7. **Confirmation**: User receives confirmation with queue position

#### Rate Limiting

- **Per User Limits**:
  - Maximum 3 pending requests at any time
  - 1 request per 24-hour period
- **Global Limit**:
  - Maximum 20 requests per day across all users
- **Admin Exemption**:
  - Admins are exempt from all rate limits for testing purposes

#### Input Validation

- **Content Type**: Must be "Movie" or "Series"
- **Title**: Minimum 2 characters
- **Year**: Must be a 4-digit number between 1900 and current year + 2
- **TMDb Selection**: User must select from top 5 TMDb results or skip
  - IMDB link automatically extracted from TMDb data
  - If no results found, user can continue without IMDB link

#### Duplicate Detection

The bot uses fuzzy matching (85% similarity threshold) to detect duplicate requests based on:

- Title similarity
- Year match

If a similar request is found, the user is notified and can choose to proceed or cancel.

#### Cancellation

Users can type `CANCEL` at any step to abort the request process.

## Admin Functionality

### `/request_list` Command

Admins can view and manage all pending requests using the `/request_list` command.

#### Request List Display

- **Pagination**: 9 requests per page
- **Information Shown**:
  - Request ID (click-to-copy)
  - Content Type ([M] for Movie, [S] for Series)
  - Title
  - Year
  - Username
  - User ID
  - Request Date (YYYY-MM-DD HH:MM format)
  - IMDB Link (if provided)

#### Admin Actions

1. **Mark Done**: Mark individual requests as completed

   - Click the `Done [#]` button for the specific request
   - User is automatically notified
   - Request status updated to "completed"

2. **Mark All Done**: Mark all pending requests as completed

   - Click the `Mark All Done` button
   - All users are notified
   - All requests updated to "completed"

3. **Navigation**: Use `← Prev` and `Next →` buttons to navigate pages

#### User Notifications

When a request is marked as done, the requesting user receives an automatic notification:

```
✅ Request Fulfilled!

Your request for [Title] ([Year]) has been fulfilled.

Thank you for using our service!
```

## Database Schema

### `requests` Collection

```javascript
{
  "_id": ObjectId,
  "user_id": Integer,
  "username": String,
  "content_type": String,  // "Movie" or "Series"
  "title": String,
  "year": String,
  "imdb_link": String,     // Optional
  "request_date": DateTime,
  "status": String,        // "pending" or "completed"
  "completed_at": DateTime,  // Optional
  "completed_by": Integer    // Optional, admin user_id
}
```

**Indexes**:

- `user_id` (non-unique)
- `status` (non-unique)
- `request_date` (non-unique)

### `user_request_limits` Collection

```javascript
{
  "_id": ObjectId,
  "user_id": Integer,
  "last_request_date": DateTime
}
```

**Indexes**:

- `user_id` (unique)

## Technical Implementation

### Modules

1. **`features/request_management.py`**

   - Rate limiting logic
   - Request validation
   - Duplicate detection
   - IMDB link validation
   - Queue position calculation

2. **`features/commands.py`**

   - `/request` command handler
   - `/request_list` command handler
   - Request list pagination

3. **`features/callbacks.py`**
   - `req_done:` - Mark single request as done
   - `req_page:` - Request list pagination
   - `req_all_done:` - Mark all requests as done

### Error Handling

- All user inputs are validated
- Timeout handling (120 seconds for most steps, 60 seconds for confirmations)
- Database error handling
- Notification failure handling (logged but doesn't block completion)

## Testing

Run the test suite to validate the request feature:

```bash
python tests/test_request_feature.py
```

Tests cover:

- IMDB link validation
- Rate limiting enforcement
- Duplicate detection
- Database operations

## Usage Examples

### User Request Example

```
User: /request
Bot: What type of content are you requesting?
     Reply with: Movie or Series

User: Movie
Bot: What is the title/name?

User: Inception
Bot: What is the release year?

User: 2010
Bot: IMDB Link (optional but recommended)
     Reply with the IMDB link or type SKIP

User: https://www.imdb.com/title/tt1375666/
Bot: ✅ Request Submitted Successfully!

     Type: Movie
     Title: Inception
     Year: 2010
     IMDB: https://www.imdb.com/title/tt1375666/

     📊 Queue Position: #5
     📝 Your Pending Requests: 1/3
```

### Admin Management Example

```
Admin: /request_list
Bot: [Displays paginated list with buttons]

     Request List - Page 1/2
     Total Pending: 12

     #1 [M] Inception (2010)
         User: john_doe (ID: 123456)
         Date: 2024-01-15 14:30
         IMDB: https://www.imdb.com/title/tt1375666/

     [Done [1]] [Done [2]] [Done [3]]
     [Mark All Done] [Next →]
```

## Future Enhancements

Potential improvements for future versions:

- Request priority system
- Request categories/genres
- Automatic duplicate merging
- Request statistics dashboard
- Email notifications
- Request expiration (auto-close old requests)
