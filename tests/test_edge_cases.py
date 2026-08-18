#!/usr/bin/env python3
"""
Test edge cases and problematic scenarios for movie title extraction
"""

import sys
import os

# Ensure project root is on the path so the features package is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# parse_metadata now lives in the features package (canonical parser module)
from features.metadata_parser import parse_metadata


print("=" * 80)
print("EDGE CASE ANALYSIS - Movies with Years in Title")
print("=" * 80)

edge_cases = [
    # Movies with years in the title
    ("2012.2009.1080p.BluRay.x264.mkv", "2012", 2009),
    ("1917.2019.1080p.BluRay.x264.mkv", "1917", 2019),
    ("2001.A.Space.Odyssey.1968.1080p.BluRay.mkv", "2001 A Space Odyssey", 1968),
    ("1984.1984.1080p.BluRay.x264.mkv", "1984", 1984),
    
    # Movies with numbers that look like years
    ("300.2006.1080p.BluRay.x264.mkv", "300", 2006),
    ("2012.2009.EXTENDED.1080p.BluRay.x264.mkv", "2012", 2009),
    
    # Normal movies (control group)
    ("Inception.2010.1080p.BluRay.x264.mkv", "Inception", 2010),
    ("The.Matrix.1999.1080p.BluRay.x264.mkv", "The Matrix", 1999),
]

print("\nTesting edge cases where movie title contains a year-like number:\n")

for filename, expected_title, expected_year in edge_cases:
    result = parse_metadata(filename=filename)
    
    title_ok = result['title'] == expected_title
    year_ok = result['year'] == expected_year
    
    status = "✅" if (title_ok and year_ok) else "❌"
    
    print(f"{status} {filename}")
    print(f"   Expected: title='{expected_title}', year={expected_year}")
    print(f"   Got:      title='{result['title']}', year={result['year']}")
    
    if not title_ok or not year_ok:
        print(f"   ⚠️  ISSUE: ", end="")
        if not title_ok:
            print(f"Title mismatch! ", end="")
        if not year_ok:
            print(f"Year mismatch!", end="")
        print()
    print()

print("\n" + "=" * 80)
print("ROOT CAUSE ANALYSIS")
print("=" * 80)
print()
print("The regex pattern at line 680-688 splits at the FIRST occurrence of a year pattern.")
print("This causes issues when:")
print()
print("1. Movie title contains a year (e.g., '2012', '1917', '1984')")
print("   - The regex matches the year IN THE TITLE instead of the release year")
print("   - Result: Empty or incorrect title extraction")
print()
print("2. The year pattern (19\\d{2}|20\\d{2}) is too greedy")
print("   - It matches ANY 4-digit number starting with 19 or 20")
print("   - It doesn't distinguish between title years and release years")
print()
print("COMPARISON WITH SERIES HANDLING:")
print("Series titles were fixed to exclude season/episode info from the title.")
print("Movies need similar treatment to exclude metadata that appears AFTER the title.")
print()
print("The current implementation works for MOST movies because:")
print("- The year typically appears after the title in filenames")
print("- The regex splits at the first year, which is usually correct")
print()
print("But it FAILS when:")
print("- The movie title itself contains a year")
print("- The first year in the filename is part of the title, not the release year")
print()