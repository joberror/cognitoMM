#!/usr/bin/env python3
"""
Test edge cases and problematic scenarios for movie title extraction
"""

import re

BRACKET_TAG_RE = re.compile(r"\[([^\]]+)\]|\(([^\)]+)\)|\{([^\}]+)\}")

def parse_metadata(caption: str = None, filename: str = None) -> dict:
    """Copy of parse_metadata from main.py"""
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

    ext_match = re.search(r"\.(mkv|mp4|avi|mov|webm|m4v|3gp|ts|m2ts|flv)$", text, re.I)
    if ext_match:
        md["extension"] = ext_match.group(0).lower()

    audio_ch_match = re.search(r"(\d+(?:\.\d+)?CH)", text, re.I)
    if audio_ch_match:
        md["audio_channels"] = audio_ch_match.group(1).upper()

    t = re.sub(r"[_\.]+", " ", text)

    m = re.search(r"(tt\d{6,8})", t, re.I)
    if m:
        md["imdb"] = m.group(1)

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

    m = re.search(r"(480p|720p|1080p|2160p|4K)", t, re.I)
    if m and not md["quality"]:
        md["quality"] = m.group(1)

    m = re.search(r"(WEBRip|BluRay|HDRip|DVDRip|BRRip|CAM|HDTS|WEB-DL|WEB DL)", t, re.I)
    if m and not md["rip"]:
        md["rip"] = m.group(1)

    m = re.search(r"(Netflix|Amazon|Prime Video|Disney\+|HBO|Hulu|Apple ?TV)", t, re.I)
    if m and not md["source"]:
        md["source"] = m.group(1)

    if not md["extension"]:
        m = re.search(r"(mkv|mp4|avi|mov|webm|m4v|3gp|ts|m2ts|flv)", t, re.I)
        if m:
            md["extension"] = "." + m.group(1).lower()

    m = re.search(r"(\d{3,4}x\d{3,4})", t)
    if m:
        md["resolution"] = m.group(1)

    m = re.search(r"(AAC|DTS-HD|DTS-X|DTS|TrueHD|AC3|EAC3|FLAC|MP3|M4A|Atmos)", t, re.I)
    if m and not md["audio"]:
        md["audio"] = m.group(1)

    m = re.search(r"[sS](\d{1,2})[ ._-]?[eE](\d{1,2})", t)
    if not m:
        m = re.search(r"(\d{1,2})x(\d{1,2})", t)
    if m:
        md["type"] = "Series"
        md["season"] = int(m.group(1))
        md["episode"] = int(m.group(2))
    else:
        md["type"] = "Movie"

    m = re.search(r"(19\d{2}|20\d{2})", t)
    if m:
        md["year"] = int(m.group(1))

    # THE CRITICAL TITLE EXTRACTION LOGIC
    clean = re.sub(r"(\[.*?\]|\(.*?\)|\{.*?\})", " ", t)
    clean = re.sub(r"(\.|\_)+", " ", clean)
    
    split_at = re.search(
        r"(tt\d{6,8}|"
        r"[sS]\d{1,2}[eE]\d{1,2}|"
        r"[sS]\d{1,2}(?:\s|\.|-|_)|"
        r"\d{1,2}x\d{1,2}|"
        r"19\d{2}|20\d{2}|"
        r"480p|720p|1080p|2160p|4K|"
        r"WEBRip|BluRay|HDRip|DVDRip|CAM)",
        clean, re.I
    )
    if split_at:
        title_guess = clean[:split_at.start()].strip()
    else:
        title_guess = clean.strip()

    if title_guess:
        title_guess = title_guess.split("\n")[0].strip(" -_.")
        md["title"] = title_guess

    return md


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