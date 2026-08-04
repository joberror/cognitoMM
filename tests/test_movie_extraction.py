#!/usr/bin/env python3
"""
Test script to analyze movie title extraction inconsistencies
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


# Test cases - common movie filename patterns
test_cases = [
    "Inception.2010.1080p.BluRay.x264-GROUP.mkv",
    "The.Dark.Knight.2008.2160p.HDR.WEBRip.mkv",
    "Dune.2021.IMAX.2160p.WEB-DL.DDP5.1.Atmos.DV.HEVC-GROUP.mkv",
    "Avatar.The.Way.of.Water.2022.1080p.BluRay.x265.mkv",
    "Interstellar.2014.REMASTERED.1080p.BluRay.x264.mkv",
    # Edge cases
    "2012.2009.1080p.BluRay.x264.mkv",  # Movie with year in title
    "The.Matrix.1999.EXTENDED.1080p.BluRay.x264.mkv",
    "Blade.Runner.2049.2017.Directors.Cut.2160p.BluRay.mkv",
    "Mad.Max.Fury.Road.2015.Black.and.Chrome.Edition.1080p.mkv",
]

print("=" * 80)
print("MOVIE TITLE EXTRACTION ANALYSIS")
print("=" * 80)
print()

for i, filename in enumerate(test_cases, 1):
    print(f"\n{'='*80}")
    print(f"Test Case #{i}")
    print(f"{'='*80}")
    print(f"Filename: {filename}")
    print()
    
    result = parse_metadata(filename=filename)
    
    print(f"EXTRACTED TITLE: '{result['title']}'")
    print()
    print("Other Metadata:")
    print(f"  Year:       {result['year']}")
    print(f"  Quality:    {result['quality']}")
    print(f"  Rip:        {result['rip']}")
    print(f"  Extension:  {result['extension']}")
    print(f"  Type:       {result['type']}")
    print()
    
    # Analyze what's in the title
    if result['title']:
        title_lower = result['title'].lower()
        issues = []
        
        # Check for year in title
        if re.search(r'(19\d{2}|20\d{2})', result['title']):
            issues.append("❌ YEAR included in title")
        
        # Check for quality markers
        if re.search(r'(480p|720p|1080p|2160p|4k)', title_lower):
            issues.append("❌ QUALITY marker included in title")
        
        # Check for rip type
        if re.search(r'(bluray|webrip|web-dl|hdrip|bdrip)', title_lower):
            issues.append("❌ RIP TYPE included in title")
        
        # Check for codec
        if re.search(r'(x264|x265|hevc|h\.264|h\.265)', title_lower):
            issues.append("❌ CODEC included in title")
        
        # Check for special tags
        if re.search(r'(imax|remastered|extended|directors cut|black and chrome)', title_lower):
            issues.append("⚠️  SPECIAL TAG included in title")
        
        # Check for group names
        if re.search(r'-[A-Z]+$', result['title']):
            issues.append("❌ GROUP NAME included in title")
        
        if issues:
            print("ISSUES DETECTED:")
            for issue in issues:
                print(f"  {issue}")
        else:
            print("✅ Title extraction looks clean")
    
    print()

print("\n" + "=" * 80)
print("ANALYSIS SUMMARY")
print("=" * 80)
print()
print("Current Regex Pattern (line 680-688 in main.py):")
print("  Splits at: IMDB ID, S##E##, Year, Quality, Rip Type")
print()
print("FINDINGS:")
print("  1. The regex DOES include year (19\\d{2}|20\\d{2}) as a split point")
print("  2. The regex DOES include quality (480p|720p|1080p|2160p|4K) as a split point")
print("  3. The regex DOES include rip type (WEBRip|BluRay|HDRip|DVDRip|CAM) as a split point")
print()
print("POTENTIAL ISSUES:")
print("  1. Special tags like IMAX, REMASTERED, EXTENDED are NOT in the split pattern")
print("  2. Codec information (x264, x265, HEVC) is NOT in the split pattern")
print("  3. Group names (-GROUP) are NOT in the split pattern")
print("  4. HDR, DV (Dolby Vision), Atmos are NOT in the split pattern")
print()
print("These tags appear AFTER the year in filenames, so they should be excluded")
print("by the year split. However, if they appear BEFORE the year, they will be")
print("included in the title.")
print()