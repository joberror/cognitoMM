#!/usr/bin/env python3
"""
Test script for movie title extraction with years in titles.
Tests the context-aware multi-year detection algorithm in parse_metadata().
"""

import sys
from typing import Dict, Any, Tuple

# Import the parse_metadata function from main.py
from main import parse_metadata


class TestCase:
    """Represents a single test case for movie title extraction."""
    
    def __init__(self, filename: str, expected_title: str, expected_year: int, reason: str):
        self.filename = filename
        self.expected_title = expected_title
        self.expected_year = expected_year
        self.reason = reason
        self.passed = False
        self.actual_title = None
        self.actual_year = None
        self.errors = []


def run_test(test_case: TestCase) -> bool:
    """
    Run a single test case and update its results.
    
    Args:
        test_case: The test case to run
        
    Returns:
        True if test passed, False otherwise
    """
    try:
        # Parse the metadata
        metadata = parse_metadata(test_case.filename)
        
        # Extract actual values
        test_case.actual_title = metadata.get('title', '')
        test_case.actual_year = metadata.get('year')
        
        # Check title match
        title_match = test_case.actual_title == test_case.expected_title
        if not title_match:
            test_case.errors.append(
                f"Title mismatch: expected '{test_case.expected_title}', got '{test_case.actual_title}'"
            )
        
        # Check year match
        year_match = test_case.actual_year == test_case.expected_year
        if not year_match:
            test_case.errors.append(
                f"Year mismatch: expected {test_case.expected_year}, got {test_case.actual_year}"
            )
        
        # Test passes if both title and year match
        test_case.passed = title_match and year_match
        
        return test_case.passed
        
    except Exception as e:
        test_case.errors.append(f"Exception during parsing: {str(e)}")
        test_case.passed = False
        return False


def print_test_result(test_num: int, test_case: TestCase):
    """Print detailed results for a single test case."""
    status = "✅ PASS" if test_case.passed else "❌ FAIL"
    
    print(f"\n{'='*80}")
    print(f"Test {test_num}: {status}")
    print(f"{'='*80}")
    print(f"Filename: {test_case.filename}")
    print(f"Reason:   {test_case.reason}")
    print(f"\nExpected:")
    print(f"  Title: '{test_case.expected_title}'")
    print(f"  Year:  {test_case.expected_year}")
    print(f"\nActual:")
    print(f"  Title: '{test_case.actual_title}'")
    print(f"  Year:  {test_case.actual_year}")
    
    if test_case.errors:
        print(f"\nErrors:")
        for error in test_case.errors:
            print(f"  - {error}")


def main():
    """Run all test cases and report results."""
    
    # Define all test cases
    test_cases = [
        # Problem Cases (Previously Failing, Should Now Work)
        TestCase(
            filename="2012.2009.1080p.BluRay.x264.mkv",
            expected_title="2012",
            expected_year=2009,
            reason="Title contains year '2012', release year is '2009'"
        ),
        TestCase(
            filename="1917.2019.1080p.BluRay.x264.mkv",
            expected_title="1917",
            expected_year=2019,
            reason="Title contains year '1917', release year is '2019'"
        ),
        TestCase(
            filename="2001.A.Space.Odyssey.1968.1080p.BluRay.mkv",
            expected_title="2001 A Space Odyssey",
            expected_year=1968,
            reason="Title contains year '2001', release year is '1968'"
        ),
        
        # Working Cases (Must Remain Working)
        TestCase(
            filename="Inception.2010.1080p.BluRay.x264-GROUP.mkv",
            expected_title="Inception",
            expected_year=2010,
            reason="Standard movie filename format"
        ),
        TestCase(
            filename="The.Dark.Knight.2008.2160p.HDR.WEBRip.mkv",
            expected_title="The Dark Knight",
            expected_year=2008,
            reason="Standard movie filename format"
        ),
        
        # Edge Cases
        TestCase(
            filename="1984.1984.1080p.BluRay.x264.mkv",
            expected_title="1984",
            expected_year=1984,
            reason="Title and release year are the same"
        ),
        TestCase(
            filename="Avatar.The.Way.of.Water.2022.1080p.BluRay.x265.mkv",
            expected_title="Avatar The Way of Water",
            expected_year=2022,
            reason="Multi-word title with year"
        ),
        TestCase(
            filename="Interstellar.2014.REMASTERED.1080p.BluRay.x264.mkv",
            expected_title="Interstellar",
            expected_year=2014,
            reason="Title with special tag (REMASTERED) after year"
        ),
    ]
    
    print("="*80)
    print("MOVIE TITLE EXTRACTION TEST SUITE")
    print("Testing context-aware multi-year detection algorithm")
    print("="*80)
    
    # Run all tests
    results = []
    for i, test_case in enumerate(test_cases, 1):
        passed = run_test(test_case)
        results.append(passed)
        print_test_result(i, test_case)
    
    # Print summary
    passed_count = sum(results)
    total_count = len(results)
    
    print(f"\n{'='*80}")
    print("TEST SUMMARY")
    print(f"{'='*80}")
    print(f"Total Tests:  {total_count}")
    print(f"Passed:       {passed_count} ✅")
    print(f"Failed:       {total_count - passed_count} ❌")
    print(f"Success Rate: {(passed_count/total_count)*100:.1f}%")
    print(f"{'='*80}")
    
    # Categorize results
    print("\nRESULTS BY CATEGORY:")
    print("-" * 80)
    
    print("\n📋 Problem Cases (Previously Failing):")
    for i in range(3):
        status = "✅" if results[i] else "❌"
        print(f"  {status} Test {i+1}: {test_cases[i].filename}")
    
    print("\n📋 Working Cases (Must Remain Working):")
    for i in range(3, 5):
        status = "✅" if results[i] else "❌"
        print(f"  {status} Test {i+1}: {test_cases[i].filename}")
    
    print("\n📋 Edge Cases:")
    for i in range(5, 8):
        status = "✅" if results[i] else "❌"
        print(f"  {status} Test {i+1}: {test_cases[i].filename}")
    
    # Exit with appropriate code
    sys.exit(0 if passed_count == total_count else 1)


if __name__ == "__main__":
    main()