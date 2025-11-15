"""
Metadata Parser Module

This module contains robust metadata parsing functionality for extracting
movie and series information from filenames and captions.
"""

import re
import os

# -------------------------
# Robust metadata parser
# -------------------------
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
        "audio_channels": None,     # NEW - 2CH, 5.1CH, 6CH, 7.1CH
        "video_codec": None,        # NEW - x264, x265, HEVC, AVC, VP9
        "bit_depth": None,          # NEW - 8bit, 10bit, 12bit
        "hdr_format": None,         # NEW - HDR, HDR10, HDR10+, Dolby Vision, DV
        "imdb": None,
        "type": None,
        "season": None,
        "episode": None,
    }

    if not text:
        return md

    # Extract extension BEFORE normalization (to preserve the period)
    ext_match = re.search(r"\.(mkv|mp4|avi|mov|webm|m4v|3gp|ts|m2ts|flv)$", text, re.I)
    if ext_match:
        md["extension"] = ext_match.group(0).lower()

    # Extract audio channels BEFORE normalization (to preserve decimal points like 7.1CH)
    audio_ch_match = re.search(r"(\d+(?:\.\d+)?CH)", text, re.I)
    if audio_ch_match:
        md["audio_channels"] = audio_ch_match.group(1).upper()

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
        if re.search(r"aac|dts-hd|dts-x|dts|truehd|ac3|eac3|flac|mp3|m4a|atmos", bt_l):
            md["audio"] = bt
        
        # Audio channels (bracketed)
        if re.search(r"\d+ch|\d+\.\d+ch", bt_l):
            m = re.search(r"(\d+(?:\.\d+)?ch)", bt, re.I)
            if m:
                md["audio_channels"] = m.group(1)
        
        # Video codec (bracketed)
        if re.search(r"x264|x265|h\.?264|h\.?265|hevc|avc|vp9", bt_l):
            if re.search(r"x265|h\.?265|hevc", bt_l):
                md["video_codec"] = "x265/HEVC"
            elif re.search(r"x264|h\.?264|avc", bt_l):
                md["video_codec"] = "x264/AVC"
            elif re.search(r"vp9", bt_l):
                md["video_codec"] = "VP9"
        
        # Bit depth (bracketed)
        if re.search(r"\d+bit", bt_l):
            m = re.search(r"(8bit|10bit|12bit)", bt, re.I)
            if m:
                md["bit_depth"] = m.group(1)
        
        # HDR format (bracketed)
        if re.search(r"hdr|dolby.?vision|dv", bt_l):
            if re.search(r"dolby.?vision|dv", bt_l):
                md["hdr_format"] = "Dolby Vision"
            elif re.search(r"hdr10\+", bt_l):
                md["hdr_format"] = "HDR10+"
            elif re.search(r"hdr10", bt_l):
                md["hdr_format"] = "HDR10"
            elif re.search(r"hdr", bt_l):
                md["hdr_format"] = "HDR"

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

    # Extension - already extracted before normalization
    # This is a fallback in case it wasn't found earlier
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
    
    # Audio channels (inline) - match patterns like 7.1CH, 5.1CH, 6CH, 2CH
    m = re.search(r"(\d+(?:\.\d+)?CH)", t, re.I)
    if m and not md["audio_channels"]:
        # Ensure we capture the full channel specification (e.g., "7.1CH" not just "1CH")
        md["audio_channels"] = m.group(1).upper()
    
    # Video codec (inline)
    if not md["video_codec"]:
        if re.search(r"x265|H\.?265|HEVC", t, re.I):
            md["video_codec"] = "x265/HEVC"
        elif re.search(r"x264|H\.?264|AVC", t, re.I):
            md["video_codec"] = "x264/AVC"
        elif re.search(r"VP9", t, re.I):
            md["video_codec"] = "VP9"
    
    # Bit depth (inline)
    m = re.search(r"(8bit|10bit|12bit)", t, re.I)
    if m and not md["bit_depth"]:
        md["bit_depth"] = m.group(1)
    
    # HDR format (inline)
    if not md["hdr_format"]:
        if re.search(r"Dolby.?Vision|DV", t, re.I):
            md["hdr_format"] = "Dolby Vision"
        elif re.search(r"HDR10\+", t, re.I):
            md["hdr_format"] = "HDR10+"
        elif re.search(r"HDR10", t, re.I):
            md["hdr_format"] = "HDR10"
        elif re.search(r"HDR", t, re.I):
            md["hdr_format"] = "HDR"

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

    # Year - Multi-year detection with context-aware selection
    # Find all years with their positions
    all_years = []
    for match in re.finditer(r'(19\d{2}|20\d{2})', t):
        all_years.append({
            'value': int(match.group(1)),
            'position': match.start()
        })
    
    # Determine which year is the release year
    release_year = None
    split_position = None
    
    if len(all_years) == 0:
        # No year found
        pass
    elif len(all_years) == 1:
        # Single year - use it
        release_year = all_years[0]['value']
        split_position = all_years[0]['position']
    else:
        # Multiple years - find metadata markers
        metadata_pattern = r'(480p|720p|1080p|2160p|4K|WEBRip|BluRay|HDRip|DVDRip|BRRip|CAM|HDTS|WEB-DL)'
        metadata_match = re.search(metadata_pattern, t, re.I)
        
        if metadata_match:
            # Find year closest to (but before) metadata markers
            metadata_pos = metadata_match.start()
            candidates = [y for y in all_years if y['position'] < metadata_pos]
            if candidates:
                # Use the year closest to metadata
                release_year_obj = max(candidates, key=lambda y: y['position'])
            else:
                # All years after metadata - use last year
                release_year_obj = all_years[-1]
        else:
            # No metadata markers - use last year
            release_year_obj = all_years[-1]
        
        release_year = release_year_obj['value']
        split_position = release_year_obj['position']
    
    # Set the year in metadata
    if release_year:
        md["year"] = release_year

    # Heuristic title extraction:
    # - remove bracket tags and known tokens, then take leading chunk before year/quality/rip/imdb
    clean = re.sub(r"(\[.*?\]|\(.*?\)|\{.*?\})", " ", t)  # remove bracket groups
    clean = re.sub(r"(\.|\_)+", " ", clean)
    # split at imdb or season/episode or quality or rip (year removed from pattern)
    split_at = re.search(
        r"(tt\d{6,8}|"                           # IMDB ID
        r"[sS]\d{1,2}[eE]\d{1,2}|"              # S##E## or s##e##
        r"[sS]\d{1,2}(?:\s|\.|-|_)|"            # S## followed by separator
        r"\d{1,2}x\d{1,2}|"                      # ##x## format
        r"480p|720p|1080p|2160p|4K|"            # Quality
        r"WEBRip|BluRay|HDRip|DVDRip|CAM)",     # Rip type
        clean, re.I
    )
    
    # Determine split position for title extraction
    if split_position is not None:
        # Use the selected year position
        title_guess = clean[:split_position].strip()
    elif split_at:
        # No year, use other markers
        title_guess = clean[:split_at.start()].strip()
    else:
        # No markers found
        title_guess = clean.strip()

    # Take first line and remove trailing separators
    if title_guess:
        title_guess = title_guess.split("\n")[0].strip(" -_.")
        md["title"] = title_guess

    return md