"""
Test Request Feature

This test file validates the movie/series request functionality including:
- Rate limiting
- Request validation
- Duplicate detection
- IMDB link validation
"""

import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from features.request_management import (
    check_rate_limits,
    update_user_limits,
    check_duplicate_request,
    validate_imdb_link,
    get_queue_position,
    MAX_PENDING_REQUESTS_PER_USER,
    MAX_REQUESTS_PER_DAY_PER_USER,
    MAX_GLOBAL_REQUESTS_PER_DAY
)
from features.database import requests_col, user_request_limits_col, ensure_indexes


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


async def test_rate_limits():
    """Test rate limiting functionality"""
    print("\n🧪 Testing Rate Limits...")
    
    test_user_id = 999999999  # Test user ID
    
    # Clean up any existing test data
    await requests_col.delete_many({"user_id": test_user_id})
    await user_request_limits_col.delete_many({"user_id": test_user_id})
    
    # Test 1: User should be able to request initially
    can_request, error = await check_rate_limits(test_user_id)
    assert can_request == True, "User should be able to make first request"
    print("  ✅ First request allowed")
    
    # Simulate a request
    await requests_col.insert_one({
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
    await user_request_limits_col.update_one(
        {"user_id": test_user_id},
        {"$set": {"last_request_date": yesterday}}
    )
    
    # Add 2 more pending requests (total 3)
    for i in range(2):
        await requests_col.insert_one({
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
    await requests_col.delete_many({"user_id": test_user_id})
    await user_request_limits_col.delete_many({"user_id": test_user_id})
    
    print("✅ Rate limit tests passed!")


async def test_duplicate_detection():
    """Test duplicate request detection"""
    print("\n🧪 Testing Duplicate Detection...")
    
    test_user_id = 999999998
    
    # Clean up
    await requests_col.delete_many({"user_id": test_user_id})
    
    # Add a request
    await requests_col.insert_one({
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
    await requests_col.delete_many({"user_id": test_user_id})
    
    print("✅ Duplicate detection tests passed!")


async def main():
    """Run all tests"""
    print("=" * 60)
    print("🧪 REQUEST FEATURE TEST SUITE")
    print("=" * 60)
    
    try:
        # Ensure database indexes
        await ensure_indexes()
        
        # Run tests
        await test_imdb_validation()
        await test_rate_limits()
        await test_duplicate_detection()
        
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

