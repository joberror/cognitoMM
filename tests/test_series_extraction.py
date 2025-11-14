#!/usr/bin/env python3
"""
Test script for series name extraction from parse_metadata()
Tests the regex pattern changes at line 601 in main.py
"""

import re

# Copy the BRACKET_TAG_RE from main.py
BRACKET_TAG_RE = re.compile(r"\[([^\]]+)\]|\(([^\)]+)\)|\{([^\}]+)\}")

def parse_metadata(caption: str = None, filename: str = None) -> dict:
    """
    Robust parsing - copied from main.py with focus on title extraction
    """
    text = (caption or "") + " " + (filename or "")
    text = text.strip()

    md = {
        "title": None,
        "year": None,
        "quality": None,
        "rip": None,
        "source": None,
        "extension": None,
        "resolution": None,
        "audio": None,
        "imdb": None,
        "type": None,
        "season": None,
        "episode": None,
    }

    if not text:
        return md

    # Normalize spacing
    t = re.sub(r"[_\.]+", " ", text)

    # IMDB id
    m = re.search(r"(tt\d{6,8})", t, re.I)
    if m:
        md["imdb"] = m.group(1)

    # bracketed tags (often contain rip/source/quality)
    brackets = BRACKET_TAG_RE.findall(t)
    # flatten matches (three groups per findall)
    bracket_texts = [next(filter(None, g)) for g in brackets if any(g)]
    for bt in bracket_texts:
        bt_l = bt.lower()
        if re.search(r"1080p|720p|2160p|4k|480p", bt_l):
            md["quality"] = re.search(r"(480p|720p|1080p|2160p|4K)", bt, re.I).group(1)
        if re.search(r"webrip|bluray|hdrip|dvdrip|bd5|bdrip|web-dl|web dl", bt_l):
            md["rip"] = bt
        if re.search(r"netflix|amazon|prime|disney|hbo|hulu|apple", bt_l):
            md["source"] = bt
        if re.search(r"aac|dts|ac3|eac3|flac|mp3|atmos", bt_l):
            md["audio"] = bt

    # Quality (inline)
    m = re.search(r"(480p|720p|1080p|2160p|4K)", t, re.I)
    if m and not md["quality"]:
        md["quality"] = m.group(1)

    # Rip inline
    m = re.search(r"(WEBRip|BluRay|HDRip|DVDRip|BRRip|CAM|HDTS|WEB-DL|WEB DL)", t, re.I)
    if m and not md["rip"]:
        md["rip"] = m.group(1)

    # Source inline
    m = re.search(r"(Netflix|Amazon|Prime Video|Disney\+|HBO|Hulu|Apple ?TV)", t, re.I)
    if m and not md["source"]:
        md["source"] = m.group(1)

    # Extension
    m = re.search(r"\.(mkv|mp4|avi|mov|webm)", t, re.I)
    if m:
        md["extension"] = "." + m.group(1).lower()

    # Resolution
    m = re.search(r"(\d{3,4}x\d{3,4})", t)
    if m:
        md["resolution"] = m.group(1)

    # Audio inline
    m = re.search(r"(AAC|DTS|AC3|EAC3|FLAC|MP3|Atmos)", t, re.I)
    if m and not md["audio"]:
        md["audio"] = m.group(1)

    # Season/Episode S01E02 or S1 E2 or 1x02
    m = re.search(r"[sS](\d{1,2})[ ._-]?[eE](\d{1,2})", t)
    if not m:
        m = re.search(r"(\d{1,2})x(\d{1,2})", t)
    if m:
        md["type"] = "Series"
        md["season"] = int(m.group(1))
        md["episode"] = int(m.group(2))
    else:
        md["type"] = "Movie"

    # Year
    m = re.search(r"(19\d{2}|20\d{2})", t)
    if m:
        md["year"] = int(m.group(1))

    # Heuristic title extraction:
    # - remove bracket tags and known tokens, then take leading chunk before year/quality/rip/imdb
    clean = re.sub(r"(\[.*?\]|\(.*?\)|\{.*?\})", " ", t)  # remove bracket groups
    clean = re.sub(r"(\.|\_)+", " ", clean)
    # split at imdb or year or quality or rip
    split_at = re.search(
        r"(tt\d{6,8}|"                           # IMDB ID
        r"[sS]\d{1,2}[eE]\d{1,2}|"              # S##E## or s##e##
        r"[sS]\d{1,2}(?:\s|\.|-|_)|"            # S## followed by separator
        r"\d{1,2}x\d{1,2}|"                      # ##x## format
        r"19\d{2}|20\d{2}|"                      # Year
        r"480p|720p|1080p|2160p|4K|"            # Quality
        r"WEBRip|BluRay|HDRip|DVDRip|CAM)",     # Rip type
        clean, re.I
    )
    if split_at:
        title_guess = clean[:split_at.start()].strip()
    else:
        title_guess = clean.strip()

    # Take first line and remove trailing separators
    if title_guess:
        title_guess = title_guess.split("\n")[0].strip(" -_.")
        md["title"] = title_guess

    return md


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