#!/usr/bin/env python3
"""
Test script to analyze movie title extraction inconsistencies
"""

import re

# Copy of the parse_metadata function from main.py
BRACKET_TAG_RE = re.compile(r"\[([^\]]+)\]|\(([^\)]+)\)|\{([^\}]+)\}")

def parse_metadata(caption: str = None, filename: str = None) -> dict:
    """
    Robust parsing:
    - detects bracketed tags [BluRay], (720p), {AAC}, IMDB tt1234567
    - extracts title heuristically, year, quality, rip, source, extension, resolution, audio, imdb, type, season, episode
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
        "audio_channels": None,
        "video_codec": None,
        "bit_depth": None,
        "hdr_format": None,
        "imdb": None,
        "type": None,
        "season": None,
        "episode": None,
    }

    if not text:
        return md

    # Extract extension BEFORE normalization
    ext_match = re.search(r"\.(mkv|mp4|avi|mov|webm|m4v|3gp|ts|m2ts|flv)$", text, re.I)
    if ext_match:
        md["extension"] = ext_match.group(0).lower()

    # Extract audio channels BEFORE normalization
    audio_ch_match = re.search(r"(\d+(?:\.\d+)?CH)", text, re.I)
    if audio_ch_match:
        md["audio_channels"] = audio_ch_match.group(1).upper()

    # Normalize spacing
    t = re.sub(r"[_\.]+", " ", text)

    # IMDB id
    m = re.search(r"(tt\d{6,8})", t, re.I)
    if m:
        md["imdb"] = m.group(1)

    # bracketed tags
    brackets = BRACKET_TAG_RE.findall(t)
    bracket_texts = [next(filter(None, g)) for g in brackets if any(g)]
    for bt in bracket_texts:
        bt_l = bt.lower()
        if re.search(r"1080p|720p|2160p|4k|480p", bt_l):
            md["quality"] = re.search(r"(480p|720p|1080p|2160p|4K)", bt, re.I).group(1)
        if re.search(r"webrip|bluray|hdrip|dvdrip|bd5|bdrip|web-dl|web dl", bt_l):
            md["rip"] = bt
        if re.search(r"netflix|amazon|prime|disney|hbo|hulu|apple", bt_l):
            md["source"] = bt
        if re.search(r"aac|dts-hd|dts-x|dts|truehd|ac3|eac3|flac|mp3|m4a|atmos", bt_l):
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

    # Extension fallback
    if not md["extension"]:
        m = re.search(r"(mkv|mp4|avi|mov|webm|m4v|3gp|ts|m2ts|flv)", t, re.I)
        if m:
            md["extension"] = "." + m.group(1).lower()

    # Resolution
    m = re.search(r"(\d{3,4}x\d{3,4})", t)
    if m:
        md["resolution"] = m.group(1)

    # Audio inline
    m = re.search(r"(AAC|DTS-HD|DTS-X|DTS|TrueHD|AC3|EAC3|FLAC|MP3|M4A|Atmos)", t, re.I)
    if m and not md["audio"]:
        md["audio"] = m.group(1)

    # Season/Episode
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

    # Heuristic title extraction - THIS IS THE KEY PART
    clean = re.sub(r"(\[.*?\]|\(.*?\)|\{.*?\})", " ", t)  # remove bracket groups
    clean = re.sub(r"(\.|\_)+", " ", clean)
    
    # Split at various markers - LINE 680-688 in main.py
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