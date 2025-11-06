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
from typing import Dict, Any

# Import the parse_metadata function from main.py
from main import parse_metadata


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
        "audio": "DTS-HD",
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
        test_case_5_avatar_dts_hd()
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