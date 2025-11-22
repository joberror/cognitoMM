# Premium System Documentation

## Overview

The Premium System allows administrators to grant premium access to users, enabling them to access exclusive features. The system provides a flexible interface for managing premium users and controlling which features require premium access.

## Features

### Admin Interface

Admins can access the premium management system using the `/premium` command, which provides a button-based interface with the following options:

1. **Add Users** - Grant premium access to users with a specified duration
2. **Edit Users** - Modify premium duration for existing users (add or remove days)
3. **Remove Users** - Revoke premium access from users
4. **Manage Features** - Control which features are premium-only

### Default Premium Features

The system comes with three default premium features:

1. **recent** - `/recent` command (displays recently added content)
2. **request** - `/request` command (submit movie/series requests)
3. **get_all** - "Get All" button in search results (bulk download)

All default features are **enabled** (premium-only) by default.

## Database Schema

### `premium_users` Collection

Stores information about users with premium access.

```javascript
{
  "_id": ObjectId,
  "user_id": Integer,           // Telegram user ID (unique)
  "username": String,           // Username or display name
  "added_date": DateTime,       // When premium was granted
  "added_by": Integer,          // Admin user ID who granted premium
  "expiry_date": DateTime,      // When premium expires
  "last_updated": DateTime,     // Last modification date
  "last_updated_by": Integer    // Admin user ID who last modified
}
```

**Indexes:**
- `user_id` (unique)

### `premium_features` Collection

Stores information about features that can be restricted to premium users.

```javascript
{
  "_id": ObjectId,
  "feature_name": String,       // Feature identifier (unique)
  "description": String,        // Human-readable description
  "enabled": Boolean,           // true = premium-only, false = available to all
  "added_date": DateTime,       // When feature was added
  "added_by": Integer,          // Admin user ID who added feature
  "last_updated": DateTime,     // Last modification date
  "last_updated_by": Integer    // Admin user ID who last modified
}
```

**Indexes:**
- `feature_name` (unique)

## Usage Guide

### For Admins

#### Adding Premium Users

1. Use `/premium` command
2. Click "Add Users" button
3. Send the User ID (numeric)
4. Send the number of days for premium access
5. Confirmation message will be displayed

#### Editing Premium Users

1. Use `/premium` command
2. Click "Edit Users" button
3. Send the User ID
4. View current premium details
5. Send days to add (positive number) or remove (negative number)
6. Confirmation message will be displayed

#### Removing Premium Users

1. Use `/premium` command
2. Click "Remove Users" button
3. Send the User ID
4. View user details and confirm with "YES"
5. Confirmation message will be displayed

#### Managing Features

1. Use `/premium` command
2. Click "Manage Features" button
3. View list of all features with their status (ON/OFF)
   - **ON** = Premium-only (restricted)
   - **OFF** = Available to all users
4. Click on a feature to toggle its status
5. Click "Add New Feature" to add custom features

#### Adding Custom Features

1. Navigate to Manage Features
2. Click "Add New Feature"
3. Send feature name (alphanumeric and underscores only)
4. Send feature description
5. Feature will be added and enabled (premium-only) by default

### For Users

Premium users have access to features marked as premium-only. When a non-premium user tries to access a premium feature, they will see:

```
⭐ Premium Feature

The [feature name] is a premium-only feature.

Contact an admin to get premium access.
```

Admins always have access to all features regardless of premium status.

## Technical Implementation

### Modules

1. **`features/database.py`**
   - Added `premium_users_col` and `premium_features_col` collections
   - Created unique indexes for both collections

2. **`features/premium_management.py`** (NEW)
   - Core premium management functions
   - Helper functions for checking premium status
   - User and feature management operations
   - Default feature initialization

3. **`features/premium_commands.py`** (NEW)
   - Interactive user input handlers
   - Add/Edit/Remove user flows
   - Add feature flow

4. **`features/commands.py`**
   - Added `/premium` command handler
   - Added premium checks to `/recent` and `/request` commands
   - Updated admin help text

5. **`features/callbacks.py`**
   - Premium button callback handlers
   - Feature toggle callbacks
   - User input event triggers

6. **`features/search.py`**
   - Added premium check for "Get All" button

7. **`features/indexing.py`**
   - Added premium user input handler integration

8. **`features/__init__.py`**
   - Exported premium collections and functions

## Key Functions

### Premium Management Functions

- `initialize_premium_features()` - Sets up default premium features
- `is_premium_user(user_id)` - Checks if user has active premium
- `get_premium_user(user_id)` - Retrieves premium user document
- `add_premium_user(user_id, days, admin_id, username)` - Adds/extends premium
- `edit_premium_user(user_id, days_delta, admin_id)` - Modifies premium duration
- `remove_premium_user(user_id, admin_id)` - Removes premium access
- `get_days_remaining(user_id)` - Calculates remaining premium days
- `is_feature_premium_only(feature_name)` - Checks if feature requires premium
- `toggle_feature(feature_name, admin_id)` - Toggles feature on/off
- `add_premium_feature(feature_name, description, admin_id)` - Adds new feature
- `get_all_premium_features()` - Lists all features
- `get_all_premium_users()` - Lists all premium users
- `cleanup_expired_premium()` - Maintenance function for expired premium

## Notes

- All datetime values use UTC timezone
- Premium expiry is checked in real-time when features are accessed
- Admins bypass all premium checks
- Premium duration can be extended by adding more days
- Expired premium can be reactivated by adding days
- Feature toggles take effect immediately
- No icons are used in any output messages

