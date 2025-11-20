"""
Test TMDb Integration

This test validates the TMDb API integration for searching movies and TV series.
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from features.tmdb_integration import search_tmdb, format_tmdb_result
from features.config import TMDB_API


async def test_tmdb_search():
    """Test TMDb search functionality"""
    print("\n🧪 Testing TMDb Search...")
    
    # Check if API key is configured
    if not TMDB_API or TMDB_API == "your_api_key_here":
        print("⚠️  TMDB_API not configured in .env file")
        print("   Please add your TMDb API key to test this feature")
        return
    
    print(f"✅ TMDb API key configured: {TMDB_API[:10]}...")
    
    # Test 1: Search for a popular movie
    print("\n📽️  Test 1: Searching for 'Inception' (2010)...")
    results = await search_tmdb("Inception", "2010", "Movie")
    
    if results:
        print(f"✅ Found {len(results)} result(s)")
        for idx, result in enumerate(results, 1):
            print(f"   {idx}. {result.get('title')} ({result.get('year')}) - IMDB: {result.get('imdb_id')}")
    else:
        print("❌ No results found")
    
    # Test 2: Search for a TV series
    print("\n📺 Test 2: Searching for 'Breaking Bad' (2008)...")
    results = await search_tmdb("Breaking Bad", "2008", "Series")
    
    if results:
        print(f"✅ Found {len(results)} result(s)")
        for idx, result in enumerate(results, 1):
            print(f"   {idx}. {result.get('title')} ({result.get('year')}) - IMDB: {result.get('imdb_id')}")
    else:
        print("❌ No results found")
    
    # Test 3: Search with no year
    print("\n🔍 Test 3: Searching for 'The Matrix' (no year)...")
    results = await search_tmdb("The Matrix", "", "Movie")
    
    if results:
        print(f"✅ Found {len(results)} result(s)")
        for idx, result in enumerate(results[:3], 1):  # Show only first 3
            print(f"   {idx}. {result.get('title')} ({result.get('year')}) - IMDB: {result.get('imdb_id')}")
    else:
        print("❌ No results found")
    
    # Test 4: Search for non-existent content
    print("\n❓ Test 4: Searching for non-existent content...")
    results = await search_tmdb("XYZ123NonExistent", "2099", "Movie")
    
    if not results:
        print("✅ Correctly returned no results for non-existent content")
    else:
        print(f"⚠️  Unexpected: Found {len(results)} result(s)")
    
    print("\n" + "=" * 60)
    print("✅ TMDb Integration Tests Complete!")
    print("=" * 60)


async def main():
    """Run all tests"""
    print("=" * 60)
    print("🧪 TMDB INTEGRATION TEST SUITE")
    print("=" * 60)
    
    try:
        await test_tmdb_search()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

