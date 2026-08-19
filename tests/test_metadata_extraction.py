#!/usr/bin/env python3
"""
Test Enhanced Metadata Extraction Implementation

Tests the parse_metadata() function with 5 test cases covering:
- Audio channels (2CH, 5.1CH, 6CH, 7.1CH)
- Video codecs (x264/AVC, x265/HEVC, VP9)
- Bit depth (8bit, 10bit, 12bit)
- HDR formats (HDR, HDR10, HDR10+, Dolby Vision)
- Enhanced audio formats (TrueHD, DTS-HD, M4A)
"""

import sys
import os
from typing import Dict, Any

# Ensure project root is on the path so the features package is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# parse_metadata now lives in the features package (was previously in main.py)
from features.metadata_parser import parse_metadata


class TestResult:
    """Store test results for reporting"""
    def __init__(self, test_name: str):
        self.test_name = test_name
        self.passed = True
        self.failures = []
        self.actual = {}
        self.expected = {}
    
    def add_failure(self, field: str, expected: Any, actual: Any):
        """Record a field mismatch"""
        self.passed = False
        self.failures.append({
            'field': field,
            'expected': expected,
            'actual': actual
        })
    
    def set_metadata(self, expected: Dict, actual: Dict):
        """Store full metadata for reporting"""
        self.expected = expected
        self.actual = actual


def compare_field(result: TestResult, field: str, expected: Any, actual: Any) -> bool:
    """Compare a single field and record any mismatch"""
    if expected != actual:
        result.add_failure(field, expected, actual)
        return False
    return True


def test_case_1_star_wars_visions():
    """
    Test Case 1: Star Wars Visions
    Filename: Star.Wars.Visions.S02E09.DUAL-AUDIO.JAP-ENG.1080p.10bit.WEBRip.6CH.x265.HEVC-PSA.mkv
    """
    result = TestResult("Test Case 1: Star Wars Visions")
    
    filename = "Star.Wars.Visions.S02E09.DUAL-AUDIO.JAP-ENG.1080p.10bit.WEBRip.6CH.x265.HEVC-PSA.mkv"
    
    expected = {
        "title": "Star Wars Visions",
        "type": "Series",
        "season": 2,
        "episode": 9,
        "quality": "1080p",
        "rip": "WEBRip",
        "audio_channels": "6CH",
        "video_codec": "x265/HEVC",
        "bit_depth": "10bit",
        "extension": ".mkv"
    }
    
    actual = parse_metadata(caption=None, filename=filename)
    result.set_metadata(expected, actual)
    
    # Compare each field
    compare_field(result, "title", expected["title"], actual.get("title"))
    compare_field(result, "type", expected["type"], actual.get("type"))
    compare_field(result, "season", expected["season"], actual.get("season"))
    compare_field(result, "episode", expected["episode"], actual.get("episode"))
    compare_field(result, "quality", expected["quality"], actual.get("quality"))
    compare_field(result, "rip", expected["rip"], actual.get("rip"))
    compare_field(result, "audio_channels", expected["audio_channels"], actual.get("audio_channels"))
    compare_field(result, "video_codec", expected["video_codec"], actual.get("video_codec"))
    compare_field(result, "bit_depth", expected["bit_depth"], actual.get("bit_depth"))
    compare_field(result, "extension", expected["extension"], actual.get("extension"))
    
    return result


def test_case_2_the_witcher():
    """
    Test Case 2: The Witcher
    Filename: The.Witcher.S02E05.Turn.Your.Back.2160p.10bit.HDR.WEBRip.6CH.x265.HEVC-PSA.mkv
    """
    result = TestResult("Test Case 2: The Witcher")
    
    filename = "The.Witcher.S02E05.Turn.Your.Back.2160p.10bit.HDR.WEBRip.6CH.x265.HEVC-PSA.mkv"
    
    expected = {
        "title": "The Witcher",
        "type": "Series",
        "season": 2,
        "episode": 5,
        "quality": "2160p",
        "rip": "WEBRip",
        "audio_channels": "6CH",
        "video_codec": "x265/HEVC",
        "bit_depth": "10bit",
        "hdr_format": "HDR",
        "extension": ".mkv"
    }
    
    actual = parse_metadata(caption=None, filename=filename)
    result.set_metadata(expected, actual)
    
    # Compare each field
    compare_field(result, "title", expected["title"], actual.get("title"))
    compare_field(result, "type", expected["type"], actual.get("type"))
    compare_field(result, "season", expected["season"], actual.get("season"))
    compare_field(result, "episode", expected["episode"], actual.get("episode"))
    compare_field(result, "quality", expected["quality"], actual.get("quality"))
    compare_field(result, "rip", expected["rip"], actual.get("rip"))
    compare_field(result, "audio_channels", expected["audio_channels"], actual.get("audio_channels"))
    compare_field(result, "video_codec", expected["video_codec"], actual.get("video_codec"))
    compare_field(result, "bit_depth", expected["bit_depth"], actual.get("bit_depth"))
    compare_field(result, "hdr_format", expected["hdr_format"], actual.get("hdr_format"))
    compare_field(result, "extension", expected["extension"], actual.get("extension"))
    
    return result


def test_case_3_hazbin_hotel():
    """
    Test Case 3: Hazbin Hotel
    Filename: Hazbin.Hotel.S02E04.1080p.10bit.WEBRip.6CH.x265.HEVC-PSA - @MovieCaban.mkv
    """
    result = TestResult("Test Case 3: Hazbin Hotel")
    
    filename = "Hazbin.Hotel.S02E04.1080p.10bit.WEBRip.6CH.x265.HEVC-PSA - @MovieCaban.mkv"
    
    expected = {
        "title": "Hazbin Hotel",
        "type": "Series",
        "season": 2,
        "episode": 4,
        "quality": "1080p",
        "rip": "WEBRip",
        "audio_channels": "6CH",
        "video_codec": "x265/HEVC",
        "bit_depth": "10bit",
        "extension": ".mkv"
    }
    
    actual = parse_metadata(caption=None, filename=filename)
    result.set_metadata(expected, actual)
    
    # Compare each field
    compare_field(result, "title", expected["title"], actual.get("title"))
    compare_field(result, "type", expected["type"], actual.get("type"))
    compare_field(result, "season", expected["season"], actual.get("season"))
    compare_field(result, "episode", expected["episode"], actual.get("episode"))
    compare_field(result, "quality", expected["quality"], actual.get("quality"))
    compare_field(result, "rip", expected["rip"], actual.get("rip"))
    compare_field(result, "audio_channels", expected["audio_channels"], actual.get("audio_channels"))
    compare_field(result, "video_codec", expected["video_codec"], actual.get("video_codec"))
    compare_field(result, "bit_depth", expected["bit_depth"], actual.get("bit_depth"))
    compare_field(result, "extension", expected["extension"], actual.get("extension"))
    
    return result


def test_case_4_dune_dolby_vision():
    """
    Test Case 4: Movie with Dolby Vision
    Filename: Dune.2021.2160p.HDR10+.Dolby.Vision.TrueHD.7.1CH.x265-RELEASE.mkv
    """
    result = TestResult("Test Case 4: Dune (Dolby Vision)")
    
    filename = "Dune.2021.2160p.HDR10+.Dolby.Vision.TrueHD.7.1CH.x265-RELEASE.mkv"
    
    expected = {
        "title": "Dune",
        "year": 2021,
        "type": "Movie",
        "quality": "2160p",
        "audio": "TrueHD",
        "audio_channels": "7.1CH",
        "video_codec": "x265/HEVC",
        "hdr_format": "Dolby Vision"  # Priority over HDR10+
    }
    
    actual = parse_metadata(caption=None, filename=filename)
    result.set_metadata(expected, actual)
    
    # Compare each field
    compare_field(result, "title", expected["title"], actual.get("title"))
    compare_field(result, "year", expected["year"], actual.get("year"))
    compare_field(result, "type", expected["type"], actual.get("type"))
    compare_field(result, "quality", expected["quality"], actual.get("quality"))
    compare_field(result, "audio", expected["audio"], actual.get("audio"))
    compare_field(result, "audio_channels", expected["audio_channels"], actual.get("audio_channels"))
    compare_field(result, "video_codec", expected["video_codec"], actual.get("video_codec"))
    compare_field(result, "hdr_format", expected["hdr_format"], actual.get("hdr_format"))
    
    return result


def test_case_5_avatar_dts_hd():
    """
    Test Case 5: DTS-HD Audio
    Filename: Avatar.2009.1080p.BluRay.DTS-HD.MA.5.1CH.x264-GROUP.mkv
    """
    result = TestResult("Test Case 5: Avatar (DTS-HD)")
    
    filename = "Avatar.2009.1080p.BluRay.DTS-HD.MA.5.1CH.x264-GROUP.mkv"
    
    expected = {
        "title": "Avatar",
        "year": 2009,
        "type": "Movie",
        "quality": "1080p",
        "rip": "BluRay",
        "audio": "DTS-HD MA",  # Filename says "DTS-HD.MA" (Master Audio)
        "audio_channels": "5.1CH",
        "video_codec": "x264/AVC"
    }
    
    actual = parse_metadata(caption=None, filename=filename)
    result.set_metadata(expected, actual)
    
    # Compare each field
    compare_field(result, "title", expected["title"], actual.get("title"))
    compare_field(result, "year", expected["year"], actual.get("year"))
    compare_field(result, "type", expected["type"], actual.get("type"))
    compare_field(result, "quality", expected["quality"], actual.get("quality"))
    compare_field(result, "rip", expected["rip"], actual.get("rip"))
    compare_field(result, "audio", expected["audio"], actual.get("audio"))
    compare_field(result, "audio_channels", expected["audio_channels"], actual.get("audio_channels"))
    compare_field(result, "video_codec", expected["video_codec"], actual.get("video_codec"))
    
    return result


def print_test_result(result: TestResult):
    """Print detailed test result"""
    status = "✅ PASSED" if result.passed else "❌ FAILED"
    print(f"\n{'='*80}")
    print(f"{status} - {result.test_name}")
    print(f"{'='*80}")
    
    if result.passed:
        print("All fields extracted correctly!")
    else:
        print(f"\n❌ {len(result.failures)} field(s) failed:\n")
        for failure in result.failures:
            print(f"  Field: {failure['field']}")
            print(f"    Expected: {failure['expected']}")
            print(f"    Actual:   {failure['actual']}")
    
    # Show full metadata comparison
    print(f"\n📊 Full Metadata Comparison:")
    print(f"\n  Expected:")
    for key, value in result.expected.items():
        print(f"    {key}: {value}")
    
    print(f"\n  Actual:")
    for key in result.expected.keys():
        actual_value = result.actual.get(key)
        match = "✓" if actual_value == result.expected[key] else "✗"
        print(f"    {match} {key}: {actual_value}")


def test_case_6_fauda_series_with_year_and_metadata_brackets():
    """
    Test Case 6: Fauda — series with year + metadata brackets
    Filename: Fauda (2015) S02E11 (1080p HEBREW NF WEB-DL x265 HEVC 10bit DDP 5.1 theincognito) [UTR].mkv
    The BRACKET_SUFFIX regex used to match (2015) S02E11 (1080p ...) as one
    giant paren group and strip it all, leaving just 'Fauda' classified as Movie.
    """
    result = TestResult("Test Case 6: Fauda series with year + metadata brackets")
    filename = "Fauda (2015) S02E11 (1080p HEBREW NF WEB-DL x265 HEVC 10bit DDP 5.1 theincognito) [UTR].mkv"
    expected = {
        'title': 'Fauda',
        'type': 'Series',
        'year': 2015,
        'season': 2,
        'episode': 11,
        'quality': '1080p',
        'video_codec': 'x265/HEVC'
    }
    actual = parse_metadata(filename)
    result.set_metadata(expected, actual)
    compare_field(result, 'title', expected['title'], actual.get('title'))
    compare_field(result, 'type', expected['type'], actual.get('type'))
    compare_field(result, 'year', expected['year'], actual.get('year'))
    compare_field(result, 'season', expected['season'], actual.get('season'))
    compare_field(result, 'episode', expected['episode'], actual.get('episode'))
    compare_field(result, 'quality', expected['quality'], actual.get('quality'))
    compare_field(result, 'video_codec', expected['video_codec'], actual.get('video_codec'))
    return result


def test_case_7_dynasty_series_with_episode_title():
    """
    Test Case 7: Dynasty — series with episode title + metadata brackets
    Filename: Dynasty (2017) S03E20 My Hangover's Arrived (1080p AMZN Webrip x265 10bit EAC3 5.1 - HxD) [TAoE].mkv
    Same bracket-stripping bug as Case 6.
    """
    result = TestResult("Test Case 7: Dynasty series with episode title + metadata brackets")
    filename = "Dynasty (2017) S03E20 My Hangover's Arrived (1080p AMZN Webrip x265 10bit EAC3 5.1 - HxD) [TAoE].mkv"
    expected = {
        'title': 'Dynasty',
        'type': 'Series',
        'year': 2017,
        'season': 3,
        'episode': 20,
        'quality': '1080p',
        'video_codec': 'x265/HEVC'
    }
    actual = parse_metadata(filename)
    result.set_metadata(expected, actual)
    compare_field(result, 'title', expected['title'], actual.get('title'))
    compare_field(result, 'type', expected['type'], actual.get('type'))
    compare_field(result, 'year', expected['year'], actual.get('year'))
    compare_field(result, 'season', expected['season'], actual.get('season'))
    compare_field(result, 'episode', expected['episode'], actual.get('episode'))
    compare_field(result, 'quality', expected['quality'], actual.get('quality'))
    compare_field(result, 'video_codec', expected['video_codec'], actual.get('video_codec'))
    return result


def main():
    """Run all test cases and report results"""
    print("🧪 Testing Enhanced Metadata Extraction")
    print("=" * 80)
    print("\nRunning 5 test cases...\n")
    
    # Run all tests
    test_results = [
        test_case_1_star_wars_visions(),
        test_case_2_the_witcher(),
        test_case_3_hazbin_hotel(),
        test_case_4_dune_dolby_vision(),
        test_case_5_avatar_dts_hd(),
        test_case_6_fauda_series_with_year_and_metadata_brackets(),
        test_case_7_dynasty_series_with_episode_title()
    ]
    
    # Print individual results
    for result in test_results:
        print_test_result(result)
    
    # Summary
    passed = sum(1 for r in test_results if r.passed)
    total = len(test_results)
    
    print(f"\n{'='*80}")
    print(f"📊 TEST SUMMARY")
    print(f"{'='*80}")
    print(f"\n✅ Passed: {passed}/{total}")
    print(f"❌ Failed: {total - passed}/{total}")
    
    if passed == total:
        print(f"\n🎉 All tests passed! Enhanced metadata extraction is working correctly.")
        return 0
    else:
        print(f"\n⚠️  Some tests failed. Review the failures above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())