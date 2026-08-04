#!/usr/bin/env python3
"""
Test script for series name extraction from parse_metadata()
Tests the regex pattern changes at line 601 in main.py
"""

import re
import sys
import os

# Ensure project root is on the path so the features package is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# parse_metadata now lives in the features package (canonical parser module)
from features.metadata_parser import parse_metadata


def run_tests():
    """Run the three test cases"""
    print("=" * 80)
    print("SERIES NAME EXTRACTION TEST")
    print("=" * 80)
    print()
    
    # Test cases
    test_cases = [
        {
            "filename": "Star.Wars.Visions.S02E09.DUAL-AUDIO.JAP-ENG.1080p.10bit.WEBRip.6CH.x265.HEVC-PSA.mkv",
            "expected": "Star Wars Visions",
            "description": "Test Case 1: Star Wars Visions S02E09"
        },
        {
            "filename": "The.Witcher.S02E05.Turn.Your.Back.2160p.10bit.HDR.WEBRip.6CH.x265.HEVC-PSA.mkv",
            "expected": "The Witcher",
            "description": "Test Case 2: The Witcher S02E05"
        },
        {
            "filename": "Hazbin.Hotel.S02E04.1080p.10bit.WEBRip.6CH.x265.HEVC-PSA - @MovieCaban.mkv",
            "expected": "Hazbin Hotel",
            "description": "Test Case 3: Hazbin Hotel S02E04"
        }
    ]
    
    all_passed = True
    results = []
    
    for i, test in enumerate(test_cases, 1):
        print(f"Test Case {i}: {test['description']}")
        print("-" * 80)
        print(f"Filename: {test['filename']}")
        print(f"Expected: \"{test['expected']}\"")
        
        # Parse metadata
        metadata = parse_metadata(filename=test['filename'])
        extracted_title = metadata.get('title', '')
        
        print(f"Extracted: \"{extracted_title}\"")
        
        # Check if it matches
        passed = extracted_title == test['expected']
        status = "✅ PASS" if passed else "❌ FAIL"
        
        print(f"Status: {status}")
        print()
        
        # Store result
        results.append({
            'test_num': i,
            'description': test['description'],
            'filename': test['filename'],
            'expected': test['expected'],
            'extracted': extracted_title,
            'passed': passed
        })
        
        if not passed:
            all_passed = False
    
    # Summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print()
    
    passed_count = sum(1 for r in results if r['passed'])
    total_count = len(results)
    
    print(f"Total Tests: {total_count}")
    print(f"Passed: {passed_count}")
    print(f"Failed: {total_count - passed_count}")
    print()
    
    if all_passed:
        print("🎉 ALL TESTS PASSED! 🎉")
        print()
        print("The series name extraction is working correctly.")
        print("The regex pattern successfully extracts only the series title,")
        print("excluding season/episode information.")
    else:
        print("⚠️ SOME TESTS FAILED")
        print()
        print("Failed tests:")
        for r in results:
            if not r['passed']:
                print(f"  • Test {r['test_num']}: {r['description']}")
                print(f"    Expected: \"{r['expected']}\"")
                print(f"    Got: \"{r['extracted']}\"")
        print()
    
    print("=" * 80)
    
    return all_passed, results


if __name__ == "__main__":
    all_passed, results = run_tests()
    
    # Exit with appropriate code
    exit(0 if all_passed else 1)