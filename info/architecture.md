# 🎬 Telegram Movie Bot Architecture

## 🧠 Overview

A Telegram bot system that monitors multiple channels for movie uploads, extracts rich metadata, stores it in MongoDB Atlas, and supports search, user management, and channel control.

---

## 📦 Core Features

### ✅ 1. Channel Monitoring

* Listen to updates from one or more Telegram channels
* Detect new movie file uploads (video or document with video MIME type)
* Use **MTProto API** via **Kurigram**

---

### ✅ 2. Metadata Extraction

Parse movie descriptions to extract:

* 🎞️ **Title**
* 📅 **Year**
* 🧵 **Rip type** (e.g., WEBRip, BluRay)
* 🌐 **Source** (e.g., Netflix, Amazon)
* 🎚️ **Quality** (e.g., 720p, 1080p)
* 📁 **Extension** (.mp4, .mkv)
* 🖥️ **Resolution**
* 🔊 **Audio format** (e.g., AAC, DTS)
* 🎬 **Movie type** (Movie or Series)
* 📺 **Season, Episode, Scene info**

---

### ✅ 3. Telegram File Details

Extract:

* 📦 **File size**
* 🕒 **Upload date**
* 🔗 **Telegram channel URL**
* 📄 **Caption text**
* 🆔 **Message ID** for retrieval

---

### ✅ 4. MongoDB Atlas Integration

* Store extracted metadata in a **cloud-hosted MongoDB Atlas database**
* Use a **structured schema** for efficient querying
* Index fields like **title, year, quality, and type**

#### Example Schema (JSON)

```json
{
  "title": "Avengers: Endgame",
  "year": 2019,
  "rip": "BluRay",
  "source": "Marvel",
  "quality": "1080p",
  "extension": ".mkv",
  "resolution": "1920x1080",
  "audio": "DTS",
  "type": "Movie",
  "season": null,
  "episode": null,
  "scene": null,
  "file_size": 2147483648,
  "upload_date": "2025-09-29T04:51:00",
  "channel_url": "https://t.me/MarvelMovies",
  "message_id": 12345,
  "caption": "Avengers Endgame (2019) BluRay 1080p DTS"
}
```

#### Python Setup (PyMongo)

```python
from pymongo import MongoClient, ASCENDING

# Connect to MongoDB Atlas
client = MongoClient("mongodb+srv://<username>:<password>@<cluster-url>/")
db = client["telegram_movies"]
collection = db["movies"]

# Insert a sample movie document
sample_movie = {
    "title": "Avengers: Endgame",
    "year": 2019,
    "rip": "BluRay",
    "source": "Marvel",
    "quality": "1080p",
    "extension": ".mkv",
    "resolution": "1920x1080",
    "audio": "DTS",
    "type": "Movie",
    "season": None,
    "episode": None,
    "scene": None,
    "file_size": 2147483648,
    "upload_date": "2025-09-29T04:51:00",
    "channel_url": "https://t.me/MarvelMovies",
    "message_id": 12345,
    "caption": "Avengers Endgame (2019) BluRay 1080p DTS"
}

collection.insert_one(sample_movie)
print("Movie inserted successfully")
```

#### Create Indexes for Fast Search

```python
# Create indexes for common search fields
collection.create_index([("title", ASCENDING)])
collection.create_index([("year", ASCENDING)])
collection.create_index([("quality", ASCENDING)])
collection.create_index([("type", ASCENDING)])
collection.create_index([("season", ASCENDING), ("episode", ASCENDING)])

print("Indexes created successfully")
```

---

### ✅ 5. Auto-Indexing

* Continuously listen for new updates
* Automatically parse and store new movie entries
* Avoid duplicates using **hash** or **message ID**

---

### ✅ 6. Search Engine

Allow users to search by:

* Title
* Year
* Quality
* Type (Movie/Series)
* Season/Episode

Return matching entries with **download links** or **Telegram file references**

#### Example Search Queries (Python)

```python
# Search by title
results = collection.find({"title": {"$regex": "Avengers", "$options": "i"}})
for r in results:
    print(r["title"], r["quality"], r["channel_url"])

# Search by year
results = collection.find({"year": 2019})
for r in results:
    print(r["title"], r["year"])

# Search by quality
results = collection.find({"quality": "1080p"})
for r in results:
    print(r["title"], r["quality"])

# Search by type (Movie/Series)
results = collection.find({"type": "Movie"})
for r in results:
    print(r["title"], r["type"])

# Search by season & episode
results = collection.find({"season": 1, "episode": 3})
for r in results:
    print(r["title"], "S", r["season"], "E", r["episode"])

# Example: Search for all Marvel 1080p Movies
results = collection.find({
    "source": {"$regex": "Marvel", "$options": "i"},
    "quality": "1080p",
    "type": "Movie"
})
for r in results:
    print(r["title"], "-", r["quality"], "-", r["channel_url"])
```

---

### ✅ 7. User Management

* Track user interactions
* Store preferences or search history
* Implement **access control** (e.g., admin-only features)
* *(Optional)* Rate limiting or subscription tiers

---

### ✅ 8. Channel Management

* Add/remove channels dynamically
* Store channel metadata in the database
* Assign admin rights to bot or user account
* Enable/disable monitoring per channel
* Log channel activity and errors

---

## 🧪 System Workflow

```mermaid
graph TD
    A[Telegram Channels] --> B[Bot Client (Kurigram)]
    B --> C[Update Listener]
    C --> D[Media Filter]
    D --> E[Metadata Extractor]
    E --> F[MongoDB Atlas]
    F --> G[Search Engine]
    G --> H[User Interface (Bot Commands)]
    H --> I[User Manager]
    B --> J[Channel Manager]
```

---

## 🧭 Implementation Roadmap (Recommended Order)

| Step | Feature                            | Why First?                        |
| ---- | ---------------------------------- | --------------------------------- |
| 1️⃣  | MongoDB Setup                      | Foundation for all data storage   |
| 2️⃣  | Telegram Client Setup              | Core connection to Telegram       |
| 3️⃣  | Channel Monitoring                 | Enables real-time updates         |
| 4️⃣  | Media Filter + Metadata Extraction | Core logic for parsing movie info |
| 5️⃣  | Auto-Indexing                      | Keeps database updated            |
| 6️⃣  | Channel Management                 | Adds flexibility and control      |
| 7️⃣  | Telegram File Details              | Completes metadata set            |
| 8️⃣  | Search Engine                      | Enables user interaction          |
| 9️⃣  | User Management                    | Tracks and controls access        |
| 🔟   | Bot Commands & UI                  | Final polish for usability        |

---
