"""
Test Request Feature

This test file validates the movie/series request functionality including:
- Rate limiting
- Request validation
- Duplicate detection
- IMDB link validation

The rate-limit and duplicate-detection tests run against an in-memory
FakeRequestCollection instead of the real MongoDB (which is unavailable in CI):
the production code paths are identical (features/request_management.py only
talks to the collections through find_one/count_documents/find/insert_one/
update_one/delete_many), so the tests are self-contained and never touch a
live database.
"""

import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import features.request_management as request_management
from features.request_management import (
    check_rate_limits,
    update_user_limits,
    check_duplicate_request,
    validate_imdb_link
)


# ---------------------------
# In-memory collection fakes
# ---------------------------

class FakeCursor:
    """Object with an async to_list(), returned by find()."""

    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return self._docs


class FakeRequestCollection:
    """In-memory stand-in for a motor collection.

    Supports the subset of the collection API used by
    features/request_management.py and these tests: find_one,
    count_documents, find(...).to_list, insert_one, update_one ($set + upsert)
    and delete_many. Comparison operators ($gte/$gt/$lte/$lt) are supported for
    date-range queries.
    """

    def __init__(self, docs=None):
        self.docs = list(docs or [])

    @staticmethod
    def _matches(doc, query):
        for key, expected in (query or {}).items():
            if isinstance(expected, dict):
                # Comparison operators, e.g. {"request_date": {"$gte": t}}
                value = doc.get(key)
                for op, target in expected.items():
                    if op == "$gte":
                        if value is None or not (value >= target):
                            return False
                    elif op == "$gt":
                        if value is None or not (value > target):
                            return False
                    elif op == "$lte":
                        if value is None or not (value <= target):
                            return False
                    elif op == "$lt":
                        if value is None or not (value < target):
                            return False
                    else:
                        raise NotImplementedError(f"operator {op!r} not faked")
            else:
                if doc.get(key) != expected:
                    return False
        return True

    async def find_one(self, query, **kwargs):
        # **kwargs (e.g. sort) accepted for motor-signature parity even though
        # the exercised code paths never pass them.
        for doc in self.docs:
            if self._matches(doc, query):
                return dict(doc)
        return None

    async def count_documents(self, query):
        return sum(1 for doc in self.docs if self._matches(doc, query))

    def find(self, query):
        return FakeCursor([
            dict(doc) for doc in self.docs if self._matches(doc, query)
        ])

    async def insert_one(self, doc):
        new_doc = dict(doc)
        new_doc.setdefault("_id", len(self.docs) + 1)
        self.docs.append(new_doc)

    async def update_one(self, query, update, upsert=False):
        for doc in self.docs:
            if self._matches(doc, query):
                for field, value in (update or {}).get("$set", {}).items():
                    doc[field] = value
                return
        if upsert:
            self.docs.append(dict((update or {}).get("$set", {})))

    async def delete_many(self, query):
        self.docs = [doc for doc in self.docs if not self._matches(doc, query)]


def _install_fakes(monkeypatch=None):
    """Swap request_management's collections for in-memory fakes.

    Under pytest the fakes are installed via monkeypatch (auto-restored); when
    run standalone (python tests/test_request_feature.py) they are assigned
    directly on the module.
    """
    requests = FakeRequestCollection()
    limits = FakeRequestCollection()
    if monkeypatch is not None:
        monkeypatch.setattr(request_management, "requests_col", requests)
        monkeypatch.setattr(request_management, "user_request_limits_col", limits)
    else:
        request_management.requests_col = requests
        request_management.user_request_limits_col = limits
    return requests, limits


# ---------------------------
# Tests
# ---------------------------

async def test_imdb_validation():
    """Test IMDB link validation"""
    print("\n🧪 Testing IMDB Link Validation...")
    
    valid_links = [
        "https://www.imdb.com/title/tt1234567/",
        "https://imdb.com/title/tt1234567/",
        "http://www.imdb.com/title/tt1234567",
        "https://m.imdb.com/title/tt1234567/",
        "imdb.com/title/tt1234567/",
        "tt1234567",
        "",  # Empty is valid (optional)
    ]
    
    invalid_links = [
        "https://google.com",
        "imdb.com/title/abc123",
        "not a link",
        "tt",
    ]
    
    for link in valid_links:
        result = await validate_imdb_link(link)
        assert result == True, f"Expected {link} to be valid"
        print(f"  ✅ Valid: {link or '(empty)'}")
    
    for link in invalid_links:
        result = await validate_imdb_link(link)
        assert result == False, f"Expected {link} to be invalid"
        print(f"  ✅ Invalid: {link}")
    
    print("✅ IMDB validation tests passed!")


async def _test_rate_limits():
    """Test rate limiting functionality (in-memory collections)"""
    print("\n🧪 Testing Rate Limits...")
    
    test_user_id = 999999999  # Test user ID
    
    # Clean up any existing test data
    await request_management.requests_col.delete_many({"user_id": test_user_id})
    await request_management.user_request_limits_col.delete_many({"user_id": test_user_id})
    
    # Test 1: User should be able to request initially
    can_request, error = await check_rate_limits(test_user_id)
    assert can_request == True, "User should be able to make first request"
    print("  ✅ First request allowed")
    
    # Simulate a request
    await request_management.requests_col.insert_one({
        "user_id": test_user_id,
        "username": "test_user",
        "content_type": "Movie",
        "title": "Test Movie",
        "year": "2024",
        "imdb_link": None,
        "request_date": datetime.now(timezone.utc),
        "status": "pending"
    })
    await update_user_limits(test_user_id)
    
    # Test 2: User should not be able to request again today
    can_request, error = await check_rate_limits(test_user_id)
    assert can_request == False, "User should not be able to make second request today"
    assert "Daily Limit Reached" in error, "Error should mention daily limit"
    print("  ✅ Daily limit enforced")
    
    # Test 3: Add more pending requests to test max pending limit
    # First, set last_request_date to yesterday to bypass daily limit
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    await request_management.user_request_limits_col.update_one(
        {"user_id": test_user_id},
        {"$set": {"last_request_date": yesterday}}
    )
    
    # Add 2 more pending requests (total 3)
    for i in range(2):
        await request_management.requests_col.insert_one({
            "user_id": test_user_id,
            "username": "test_user",
            "content_type": "Movie",
            "title": f"Test Movie {i+2}",
            "year": "2024",
            "imdb_link": None,
            "request_date": datetime.now(timezone.utc),
            "status": "pending"
        })
    
    # Test 4: User should not be able to request (max pending reached)
    can_request, error = await check_rate_limits(test_user_id)
    assert can_request == False, "User should not be able to make request (max pending)"
    assert "Request Limit Reached" in error, "Error should mention request limit"
    print("  ✅ Max pending requests enforced")
    
    # Clean up
    await request_management.requests_col.delete_many({"user_id": test_user_id})
    await request_management.user_request_limits_col.delete_many({"user_id": test_user_id})
    
    print("✅ Rate limit tests passed!")


async def test_rate_limits(monkeypatch):
    _install_fakes(monkeypatch)
    await _test_rate_limits()


async def _test_duplicate_detection():
    """Test duplicate request detection (in-memory collections)"""
    print("\n🧪 Testing Duplicate Detection...")
    
    test_user_id = 999999998
    
    # Clean up
    await request_management.requests_col.delete_many({"user_id": test_user_id})
    
    # Add a request
    await request_management.requests_col.insert_one({
        "user_id": test_user_id,
        "username": "test_user",
        "content_type": "Movie",
        "title": "The Matrix",
        "year": "1999",
        "imdb_link": None,
        "request_date": datetime.now(timezone.utc),
        "status": "pending"
    })
    
    # Test 1: Exact duplicate should be detected
    is_dup, similar = await check_duplicate_request("The Matrix", "1999", test_user_id)
    assert is_dup == True, "Exact duplicate should be detected"
    print("  ✅ Exact duplicate detected")
    
    # Test 2: Similar title should be detected
    is_dup, similar = await check_duplicate_request("The Matrix Reloaded", "1999", test_user_id)
    # This might not be detected as duplicate due to lower similarity
    print(f"  ℹ️  Similar title detection: {is_dup}")
    
    # Test 3: Different year should not be duplicate
    is_dup, similar = await check_duplicate_request("The Matrix", "2003", test_user_id)
    assert is_dup == False, "Different year should not be duplicate"
    print("  ✅ Different year not detected as duplicate")
    
    # Clean up
    await request_management.requests_col.delete_many({"user_id": test_user_id})
    
    print("✅ Duplicate detection tests passed!")


async def test_duplicate_detection(monkeypatch):
    _install_fakes(monkeypatch)
    await _test_duplicate_detection()


async def main():
    """Run all tests standalone (python tests/test_request_feature.py)"""
    print("=" * 60)
    print("🧪 REQUEST FEATURE TEST SUITE")
    print("=" * 60)
    
    _install_fakes()  # in-memory collections - no database required
    
    try:
        await test_imdb_validation()
        await _test_rate_limits()
        await _test_duplicate_detection()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
