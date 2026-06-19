"""
Metadata Parser Module

This module contains robust metadata parsing functionality for extracting
movie and series information from filenames and captions.
"""

import re
import os
from .filename_parser import MovieFilenameParser

# -------------------------
# Robust metadata parser
# -------------------------
BRACKET_TAG_RE = re.compile(r"\[([^\]]+)\]|\(([^\)]+)\)|\{([^\}]+)\}")

# Initialize parser instance once
_filename_parser = MovieFilenameParser()

def parse_metadata(caption: str = None, filename: str = None) -> dict:
    """
    Robust parsing:
    - uses MovieFilenameParser to extract robust details from the filename/caption
    - detects bracketed tags [BluRay], (720p), {AAC}, IMDB tt1234567
    - extracts title heuristically, year, quality, rip, source, extension, resolution, audio, imdb, type, season, episode
    - includes additional robust metadata fields from the filename parser
    """
    text = (caption or "") + " " + (filename or "")
    text = text.strip()

    # Pre-populate base metadata dictionary with defaults
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
        "type": "Movie",
        "season": None,
        "episode": None,
        # New extra fields from the filename parser
        "episode_end": None,
        "episode_title": None,
        "release_group": None,
        "edition": None,
        "language": None,
        "subtitles": None,
        "is_proper": False,
        "is_repack": False,
        "is_remux": False,
        "is_extended": False,
        "is_directors_cut": False,
        "is_unrated": False,
        "is_3d": False,
        "is_hardcoded_subs": False,
        "is_complete_series": False,
        "season_pack": False,
        "tags": [],
        "original_filename": None,
    }

    if not text:
        return md

    # 1. Parse using the new robust MovieFilenameParser
    parsed_media = _filename_parser.parse(text)

    # 2. Extract values from the new parser
    if parsed_media:
        md["original_filename"] = parsed_media.original_filename
        md["title"] = parsed_media.title
        md["year"] = parsed_media.year
        md["season"] = parsed_media.season
        md["episode"] = parsed_media.episode
        md["episode_end"] = parsed_media.episode_end
        md["episode_title"] = parsed_media.episode_title
        md["type"] = "Series" if parsed_media.is_series else "Movie"
        md["resolution"] = parsed_media.resolution
        md["quality"] = parsed_media.quality
        
        # In MovieFilenameParser, both rip types and publisher sources are stored in parsed_media.source.
        # Map them intelligently.
        if parsed_media.source:
            if re.search(r"webrip|bluray|hdrip|dvdrip|bd5|bdrip|web-dl|web dl|brrip|cam|hdts", parsed_media.source, re.I):
                md["rip"] = parsed_media.source
            else:
                md["source"] = parsed_media.source
                
        # Map container to extension
        if parsed_media.container:
            md["extension"] = f".{parsed_media.container.lower()}"
            
        # Map video codec
        if parsed_media.video_codec:
            # Ensure compatible formatting for tests
            if parsed_media.video_codec == "x265":
                md["video_codec"] = "x265/HEVC"
            elif parsed_media.video_codec == "x264":
                md["video_codec"] = "x264/AVC"
            else:
                md["video_codec"] = parsed_media.video_codec
                
        # Map audio codec to audio
        md["audio"] = parsed_media.audio_codec
        
        # Map audio channels
        if parsed_media.audio_channels:
            ch = parsed_media.audio_channels
            if re.match(r"^\d+(\.\d+)?$", ch):
                md["audio_channels"] = f"{ch}CH"
            else:
                md["audio_channels"] = ch
                
        # Map hdr to hdr_format
        md["hdr_format"] = parsed_media.hdr
        
        # Map other extra fields
        md["release_group"] = parsed_media.release_group
        md["edition"] = parsed_media.edition
        md["language"] = parsed_media.language
        md["subtitles"] = parsed_media.subtitles
        md["is_proper"] = parsed_media.is_proper
        md["is_repack"] = parsed_media.is_repack
        md["is_remux"] = parsed_media.is_remux
        md["is_extended"] = parsed_media.is_extended
        md["is_directors_cut"] = parsed_media.is_directors_cut
        md["is_unrated"] = parsed_media.is_unrated
        md["is_3d"] = parsed_media.is_3d
        md["is_hardcoded_subs"] = parsed_media.is_hardcoded_subs
        md["is_complete_series"] = parsed_media.is_complete_series
        md["season_pack"] = parsed_media.season_pack
        md["tags"] = parsed_media.tags

    # 3. Supplement with original parser's specific / fallback rules to ensure 100% test compatibility
    
    # Extension fallback (before normalization)
    if not md["extension"]:
        ext_match = re.search(r"\.(mkv|mp4|avi|mov|webm|m4v|3gp|ts|m2ts|flv)$", text, re.I)
        if ext_match:
            md["extension"] = ext_match.group(0).lower()
            
    # Audio channels fallback / specific regex
    audio_ch_match = re.search(r"(\d+(?:\.\d+)?CH)", text, re.I)
    if audio_ch_match:
        md["audio_channels"] = audio_ch_match.group(1).upper()

    t = re.sub(r"[_\.]+", " ", text)

    # IMDB ID (not extracted by MovieFilenameParser)
    imdb_match = re.search(r"(tt\d{6,8})", t, re.I)
    if imdb_match:
        md["imdb"] = imdb_match.group(1)

    # Bracket tag fallback extraction for rip, source, audio
    brackets = BRACKET_TAG_RE.findall(t)
    bracket_texts = [next(filter(None, g)) for g in brackets if any(g)]
    for bt in bracket_texts:
        bt_l = bt.lower()
        if re.search(r"1080p|720p|2160p|4k|480p", bt_l) and not md["quality"]:
            md["quality"] = re.search(r"(480p|720p|1080p|2160p|4K)", bt, re.I).group(1)
        if re.search(r"webrip|bluray|hdrip|dvdrip|bd5|bdrip|web-dl|web dl", bt_l) and not md["rip"]:
            md["rip"] = bt
        if re.search(r"netflix|amazon|prime|disney|hbo|hulu|apple", bt_l) and not md["source"]:
            md["source"] = bt
        if re.search(r"aac|dts-hd|dts-x|dts|truehd|ac3|eac3|flac|mp3|m4a|atmos", bt_l) and not md["audio"]:
            md["audio"] = bt
            
        # Audio channels in brackets
        if re.search(r"\d+ch|\d+\.\d+ch", bt_l) and not md["audio_channels"]:
            ch_m = re.search(r"(\d+(?:\.\d+)?ch)", bt, re.I)
            if ch_m:
                md["audio_channels"] = ch_m.group(1).upper()
                
        # Video codec in brackets
        if re.search(r"x264|x265|h\.?264|h\.?265|hevc|avc|vp9", bt_l) and not md["video_codec"]:
            if re.search(r"x265|h\.?265|hevc", bt_l):
                md["video_codec"] = "x265/HEVC"
            elif re.search(r"x264|h\.?264|avc", bt_l):
                md["video_codec"] = "x264/AVC"
            elif re.search(r"vp9", bt_l):
                md["video_codec"] = "VP9"
                
        # Bit depth in brackets
        if re.search(r"\d+bit", bt_l) and not md["bit_depth"]:
            depth_m = re.search(r"(8bit|10bit|12bit)", bt, re.I)
            if depth_m:
                md["bit_depth"] = depth_m.group(1)
                
        # HDR format in brackets
        if re.search(r"hdr|dolby.?vision|dv", bt_l) and not md["hdr_format"]:
            if re.search(r"dolby.?vision|dv", bt_l):
                md["hdr_format"] = "Dolby Vision"
            elif re.search(r"hdr10\+", bt_l):
                md["hdr_format"] = "HDR10+"
            elif re.search(r"hdr10", bt_l):
                md["hdr_format"] = "HDR10"
            elif re.search(r"hdr", bt_l):
                md["hdr_format"] = "HDR"

    # Quality inline fallback
    quality_match = re.search(r"(480p|720p|1080p|2160p|4K)", t, re.I)
    if quality_match and not md["quality"]:
        md["quality"] = quality_match.group(1)

    # Rip inline fallback
    rip_match = re.search(r"(WEBRip|BluRay|HDRip|DVDRip|BRRip|CAM|HDTS|WEB-DL|WEB DL)", t, re.I)
    if rip_match and not md["rip"]:
        md["rip"] = rip_match.group(1)

    # Source inline fallback
    source_match = re.search(r"(Netflix|Amazon|Prime Video|Disney\+|HBO|Hulu|Apple ?TV)", t, re.I)
    if source_match and not md["source"]:
        md["source"] = source_match.group(1)

    # Extension fallback
    if not md["extension"]:
        ext_match = re.search(r"(mkv|mp4|avi|mov|webm|m4v|3gp|ts|m2ts|flv)", t, re.I)
        if ext_match:
            md["extension"] = "." + ext_match.group(1).lower()

    # Resolution inline fallback
    res_match = re.search(r"(\d{3,4}x\d{3,4})", t)
    if res_match and not md["resolution"]:
        md["resolution"] = res_match.group(1)

    # Audio inline fallback
    audio_match = re.search(r"(AAC|DTS-HD|DTS-X|DTS|TrueHD|AC3|EAC3|FLAC|MP3|M4A|Atmos)", t, re.I)
    if audio_match and not md["audio"]:
        md["audio"] = audio_match.group(1)
        
    # Audio channels inline fallback
    ch_match = re.search(r"(\d+(?:\.\d+)?CH)", t, re.I)
    if ch_match and not md["audio_channels"]:
        md["audio_channels"] = ch_match.group(1).upper()
        
    # Video codec inline fallback
    if not md["video_codec"]:
        if re.search(r"x265|H\.?265|HEVC", t, re.I):
            md["video_codec"] = "x265/HEVC"
        elif re.search(r"x264|H\.?264|AVC", t, re.I):
            md["video_codec"] = "x264/AVC"
        elif re.search(r"VP9", t, re.I):
            md["video_codec"] = "VP9"
            
    # Bit depth inline fallback
    depth_match = re.search(r"(8bit|10bit|12bit)", t, re.I)
    if depth_match and not md["bit_depth"]:
        md["bit_depth"] = depth_match.group(1)
        
    # HDR format inline fallback
    if not md["hdr_format"]:
        if re.search(r"Dolby.?Vision|DV", t, re.I):
            md["hdr_format"] = "Dolby Vision"
        elif re.search(r"HDR10\+", t, re.I):
            md["hdr_format"] = "HDR10+"
        elif re.search(r"HDR10", t, re.I):
            md["hdr_format"] = "HDR10"
        elif re.search(r"HDR", t, re.I):
            md["hdr_format"] = "HDR"

    # Season/Episode fallback
    se_match = re.search(r"[sS](\d{1,2})[ ._-]?[eE](\d{1,2})", t)
    if not se_match:
        se_match = re.search(r"(\d{1,2})x(\d{1,2})", t)
    if se_match:
        md["type"] = "Series"
        md["season"] = int(se_match.group(1))
        md["episode"] = int(se_match.group(2))
    else:
        if parsed_media and parsed_media.is_series:
            md["type"] = "Series"
        else:
            if md["season"] is None and md["episode"] is None:
                md["type"] = "Movie"

    # Context-aware multi-year detection algorithm (essential for edge-cases)
    all_years = []
    for match in re.finditer(r'(19\d{2}|20\d{2})', t):
        all_years.append({
            'value': int(match.group(1)),
            'position': match.start()
        })
    
    release_year = None
    split_position = None
    
    if len(all_years) == 0:
        pass
    elif len(all_years) == 1:
        release_year = all_years[0]['value']
        split_position = all_years[0]['position']
    else:
        # Multiple years - find metadata markers
        metadata_pattern = r'(480p|720p|1080p|2160p|4K|WEBRip|BluRay|HDRip|DVDRip|BRRip|CAM|HDTS|WEB-DL)'
        metadata_match = re.search(metadata_pattern, t, re.I)
        
        if metadata_match:
            metadata_pos = metadata_match.start()
            candidates = [y for y in all_years if y['position'] < metadata_pos]
            if candidates:
                release_year_obj = max(candidates, key=lambda y: y['position'])
            else:
                release_year_obj = all_years[-1]
        else:
            release_year_obj = all_years[-1]
        
        release_year = release_year_obj['value']
        split_position = release_year_obj['position']
    
    if release_year:
        md["year"] = release_year

    # Heuristic title extraction (context-aware):
    clean = re.sub(r"(\[.*?\]|\(.*?\)|\{.*?\})", " ", t)  # remove bracket groups
    clean = re.sub(r"(\.|\_)+", " ", clean)
    split_at = re.search(
        r"(tt\d{6,8}|"                           # IMDB ID
        r"[sS]\d{1,2}[eE]\d{1,2}|"              # S##E## or s##e##
        r"[sS]\d{1,2}(?:\s|\.|-|_)|"            # S## followed by separator
        r"\d{1,2}x\d{1,2}|"                      # ##x## format
        r"480p|720p|1080p|2160p|4K|"            # Quality
        r"WEBRip|BluRay|HDRip|DVDRip|CAM)",     # Rip type
        clean, re.I
    )
    
    title_guess = None
    if split_position is not None:
        title_guess = clean[:split_position].strip()
    elif split_at:
        title_guess = clean[:split_at.start()].strip()
    else:
        title_guess = clean.strip()

    if title_guess:
        title_guess = title_guess.split("\n")[0].strip(" -_.")
        md["title"] = title_guess
        
    if not md["title"] and parsed_media and parsed_media.title:
        md["title"] = parsed_media.title

    return md