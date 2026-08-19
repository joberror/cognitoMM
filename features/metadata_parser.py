"""
Metadata Parser Module

Single canonical home for all metadata parsing (previously split across
metadata_parser.py and filename_parser.py).

- ParsedMedia / MovieFilenameParser: the complete low-level engine for parsing
  movie/series filenames. It owns ALL fields: titles, years (incl. context-aware
  multi-year selection), seasons/episodes, quality, resolution, rip, source,
  publisher, codecs, bit depth, audio channels, HDR, languages, editions,
  subtitles, IMDB IDs, x-dimension resolutions, container, flags, tags.
- parse_metadata: pure mapper from ParsedMedia to the legacy dict shape.
  Zero fallback parsing logic lives here - the engine does everything.
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List, Tuple


@dataclass
class ParsedMedia:
    """Structured result from parsing a media filename."""
    title: str = ""
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_end: Optional[int] = None
    episode_title: Optional[str] = None
    is_series: bool = False
    resolution: Optional[str] = None
    quality: Optional[str] = None
    source: Optional[str] = None
    video_codec: Optional[str] = None
    bit_depth: Optional[str] = None
    audio_codec: Optional[str] = None
    audio_channels: Optional[str] = None
    hdr: Optional[str] = None
    release_group: Optional[str] = None
    edition: Optional[str] = None
    language: Optional[str] = None
    subtitles: Optional[str] = None
    publisher: Optional[str] = None
    imdb_id: Optional[str] = None
    is_proper: bool = False
    is_repack: bool = False
    is_remux: bool = False
    is_extended: bool = False
    is_directors_cut: bool = False
    is_unrated: bool = False
    is_3d: bool = False
    is_hardcoded_subs: bool = False
    is_complete_series: bool = False
    season_pack: bool = False
    container: Optional[str] = None
    original_filename: str = ""
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return a dict of only non-empty / non-default fields."""
        out = {}
        for k, v in self.__dict__.items():
            if v and v != [] and v is not False:
                out[k] = v
        return out

    def __str__(self):
        parts = [f"Title: {self.title}"]
        if self.year:
            parts.append(f"Year: {self.year}")
        if self.is_series:
            parts.append("Type: TV Series")
            if self.season is not None:
                parts.append(f"Season: {self.season}")
            if self.episode is not None:
                ep_str = f"Episode: {self.episode}"
                if self.episode_end:
                    ep_str += f"-{self.episode_end}"
                parts.append(ep_str)
            if self.episode_title:
                parts.append(f"Episode Title: {self.episode_title}")
        else:
            parts.append("Type: Movie")
        for attr in ['resolution', 'quality', 'source', 'video_codec',
                      'bit_depth', 'audio_codec', 'audio_channels', 'hdr',
                      'release_group', 'edition', 'language', 'subtitles',
                      'publisher', 'imdb_id', 'container']:
            val = getattr(self, attr)
            if val:
                label = attr.replace('_', ' ').title()
                parts.append(f"{label}: {val}")
        flags = []
        for flag_attr in ['is_proper', 'is_repack', 'is_remux', 'is_extended',
                          'is_directors_cut', 'is_unrated', 'is_3d',
                          'is_hardcoded_subs', 'is_complete_series', 'season_pack']:
            if getattr(self, flag_attr):
                flags.append(flag_attr.replace('is_', '').replace('_', ' ').title())
        if flags:
            parts.append(f"Flags: {', '.join(flags)}")
        if self.tags:
            parts.append(f"Tags: {', '.join(self.tags)}")
        return " | ".join(parts)


class MovieFilenameParser:
    """
    Comprehensive parser for movie/series filenames from torrents
    and file-sharing sources.
    """

    # Known container extensions (real file extensions only)
    CONTAINERS = r'\.(mkv|avi|mp4|m4v|mov|wmv|flv|webm|mpg|mpeg|ts|m2ts|vob|divx|ogm|rmvb|3gp|srt|sub|idx|ass|ssa)$'

    # Fake extensions embedded in filename (e.g., "webrip_avi.mkv")
    FAKE_EXTENSIONS = r'[\.\s_\-](mkv|avi|mp4|m4v|mov|wmv|flv|webm|mpg|mpeg|divx|rmvb)(?=[\.\s_\-]|$)'

    RESOLUTIONS = {
        r'\b4320p\b': '4320p',
        r'\b2160p\b': '2160p',
        r'\b1080p\b': '1080p',
        r'\b1080i\b': '1080i',
        r'\b720p\b': '720p',
        r'\b576p\b': '576p',
        r'\b576i\b': '576i',
        r'\b480p\b': '480p',
        r'\b480i\b': '480i',
        r'\b360p\b': '360p',
        r'\b4K\b': '2160p',
        r'\b8K\b': '4320p',
        r'\bUHD\b': '2160p',
        r'\bFHD\b': '1080p',
        r'\bHD\b(?![\-\s\.]?(?:Rip|TV|CAM|TC|TS|R))': '720p',
        r'\bSD\b': '480p',
    }

    SOURCES = {
        r'\bBlu[\s\.\-_]?Ray\b': 'BluRay',
        r'\bBDRip\b': 'BDRip',
        r'\bBRRip\b': 'BRRip',
        r'\bBDR\b': 'BDR',
        r'\bWEB[\s\.\-_]?DL\b': 'WEB-DL',
        r'\bWEBDL\b': 'WEB-DL',
        r'\bWEB[\s\.\-_]?Rip\b': 'WEBRip',
        r'\bWEBRip\b': 'WEBRip',
        # *** KEY FIX: also match "webrip" with underscores like "webrip_avi" ***
        r'\bwebrip\b': 'WEBRip',
        r'\bWEB\b(?![\s\.\-_]?(?:DL|Rip))': 'WEB',
        r'\bHDRip\b': 'HDRip',
        r'\bHDTV\b': 'HDTV',
        r'\bPDTV\b': 'PDTV',
        r'\bDSR(?:ip)?\b': 'DSRip',
        r'\bDVDRip\b': 'DVDRip',
        r'\bDVDR\b': 'DVDR',
        r'\bDVDScr\b': 'DVDScr',
        r'\bDVD(?:5|9)?\b': 'DVD',
        r'\bSCR(?:eener)?\b': 'Screener',
        r'\bR5\b': 'R5',
        r'\bCAM(?:Rip)?\b': 'CAMRip',
        r'\b(?:HD[\s\.\-_]?)?TS(?:Rip)?\b': 'TSRip',
        r'\b(?:HD[\s\.\-_]?)?TC(?:Rip)?\b': 'TCRip',
        r'\bHD[\s\.\-_]?CAM\b': 'HDCAM',
        r'\bTELESYNC\b': 'TSRip',
        r'\bTELECINE\b': 'TCRip',
        r'\bPPV(?:Rip)?\b': 'PPV',
        r'\bVOD(?:Rip)?\b': 'VODRip',
        r'\bSAT(?:Rip)?\b': 'SATRip',
        r'\bDTH(?:Rip)?\b': 'DTHRip',
        r'\bAMZN\b': 'AMZN',
        r'\bNF\b': 'NF',
        r'\bNETFLIX\b': 'NF',
        r'\bDSNP?\b': 'DSNP',
        r'\bHMAX\b': 'HMAX',
        r'\bHBO\b(?![\s\.\-_]?Max)': 'HBO',
        r'\bHBO[\s\.\-_]?Max\b': 'HBOMax',
        r'\bHULU\b': 'HULU',
        r'\bAPTV\b': 'ATVP',
        r'\bATVP\b': 'ATVP',
        r'\bPCOK\b': 'PCOK',
        r'\bPMTP\b': 'PMTP',
        r'\biT(?:unes)?\b': 'iTunes',
        r'\bCRAV\b': 'CRAV',
        r'\bSTAN\b': 'STAN',
    }

    # Spelled-out publisher names (Netflix/Amazon/Prime Video/Disney+/...).
    # These are distinct from rip-type SOURCES: a filename can carry BOTH
    # ("Hulu.WEBRip"), and the single `source` field only holds the first
    # match (rip types win by dict order), so publishers are tracked
    # separately and surfaced by parse_metadata when no source was set.
    PUBLISHERS = {
        r'\bNetflix\b': 'Netflix',
        r'\bAmazon\b': 'Amazon',
        r'\bPrime[\.\s\-_]?Video\b': 'Prime Video',
        r'\bDisney\+': 'Disney+',
        r'\bHBO\b(?![\s\.\-_]?Max)': 'HBO',
        r'\bHulu\b': 'Hulu',
        r'\bApple[\.\s\-_]?TV\b': 'Apple TV',
    }

    VIDEO_CODECS = {
        r'\b[xh][\.\s\-_]?264\b': 'x264',
        r'\bAVC\b': 'x264',
        r'\b[xh][\.\s\-_]?265\b': 'x265',
        r'\bHEVC\b': 'x265',
        r'\bXviD\b': 'XviD',
        r'\bDivX\b': 'DivX',
        r'\bVP9\b': 'VP9',
        r'\bAV1\b': 'AV1',
        r'\bMPEG[\s\.\-_]?2\b': 'MPEG2',
        r'\bVC[\s\.\-_]?1\b': 'VC-1',
    }

    # Bit depth is NOT a video codec - keep it separate so "10bit" no longer
    # competes with x264/x265 when a codec is present first.
    BIT_DEPTHS = {
        r'\b12[\s\.\-_]?bit\b': '12bit',
        r'\b10[\s\.\-_]?bit\b': '10bit',
        r'\b8[\s\.\-_]?bit\b': '8bit',
        r'\bHi10P?\b': '10bit',
    }

    AUDIO_CODECS = {
        r'\bDTS[\s\.\-_]?HD[\s\.\-_]?MA\b': 'DTS-HD MA',
        r'\bDTS[\s\.\-_]?HD[\s\.\-_]?HR\b': 'DTS-HD HR',
        r'\bDTS[\s\.\-_]?HD\b': 'DTS-HD',
        r'\bDTS[\s\.\-_]?X\b': 'DTS:X',
        r'\bDTS\b': 'DTS',
        r'\bTrueHD\b': 'TrueHD',
        r'\bAtmos\b': 'Atmos',
        r'\bDD[\s\.\-_]?EX\b': 'DD-EX',
        r'\bDDP?\s?\d?\.\d\b': 'DD+',
        r'\bDolby[\s\.\-_]?Digital[\s\.\-_]?Plus\b': 'DD+',
        r'\bDolby[\s\.\-_]?Digital\b': 'DD',
        r'\bAC[\s\.\-_]?3\b': 'AC3',
        r'\bE[\s\.\-_]?AC[\s\.\-_]?3\b': 'EAC3',
        r'\bFLAC\b': 'FLAC',
        r'\bAAC(?:[\s\.\-_]?2[\.\s]?0)?\b': 'AAC',
        r'\bM4A\b': 'M4A',
        r'\bMP3\b': 'MP3',
        r'\bOGG\b': 'OGG',
        r'\bOPUS\b': 'OPUS',
        r'\bPCM\b': 'PCM',
        r'\bLPCM\b': 'LPCM',
    }

    AUDIO_CHANNELS = {
        # CH-suffixed first: `\b` cannot cross the "C" of "5.1CH", so these
        # need explicit patterns. Values are bare channel counts; the
        # parse_metadata API appends "CH".
        r'\b7[\.\s]1CH\b': '7.1',
        r'\b5[\.\s]1CH\b': '5.1',
        r'\b2[\.\s]0CH\b': '2.0',
        r'\b1[\.\s]0CH\b': '1.0',
        r'\b6CH\b': '6',
        r'\b8CH\b': '8',
        # Plain channel counts (no suffix)
        r'\b7[\.\s]1\b': '7.1',
        r'\b5[\.\s]1\b': '5.1',
        r'\b2[\.\s]0\b': '2.0',
        r'\b1[\.\s]0\b': '1.0',
        r'\bMono\b': '1.0',
        r'\bStereo\b': '2.0',
    }

    HDR_FORMATS = {
        r'\bDolby[\s\.\-_]?Vision\b': 'Dolby Vision',
        r'\bDoVi\b': 'Dolby Vision',
        r'\b(?<![A-Za-z])DV(?![A-Za-z])\b': 'Dolby Vision',
        r'\bHDR10\+': 'HDR10+',
        r'\bHDR10\b': 'HDR10',
        r'\bHDR\b': 'HDR',
        r'\bHLG\b': 'HLG',
        r'\bSDR\b': 'SDR',
    }

    LANGUAGES = {
        r'\bMULTi\b': 'Multi',
        r'\bDUAL[\s\.\-_]?(?:Audio|Aud)?\b': 'Dual Audio',
        r'\bTRUEFRENCH\b': 'French',
        r'\bFRENCH\b': 'French',
        r'\bVOSTFR\b': 'French Subs',
        r'\bGERMAN\b': 'German',
        r'\bSPANISH\b': 'Spanish',
        r'\bLATINO\b': 'Spanish (Latin)',
        r'\bITALIAN\b': 'Italian',
        r'\bRUSSIAN\b': 'Russian',
        r'\bHINDI\b': 'Hindi',
        r'\bTAMIL\b': 'Tamil',
        r'\bTELUGU\b': 'Telugu',
        r'\bKOREAN\b': 'Korean',
        r'\bJAPANESE\b': 'Japanese',
        r'\bCHINESE\b': 'Chinese',
        r'\bPORTUGUESE\b': 'Portuguese',
        r'\bARABIC\b': 'Arabic',
        r'\bTURKISH\b': 'Turkish',
        r'\bPOLISH\b': 'Polish',
        r'\bDUTCH\b': 'Dutch',
        r'\bSWEDISH\b': 'Swedish',
        r'\bNORWEGIAN\b': 'Norwegian',
        r'\bDANISH\b': 'Danish',
        r'\bFINNISH\b': 'Finnish',
        r'\bENGLISH\b': 'English',
    }

    SUBTITLES = {
        r'\bHC\b': 'Hardcoded',
        r'\bHARDCODED\b': 'Hardcoded',
        r'\bHARDSUB(?:S|BED)?\b': 'Hardcoded',
        r'\bSOFTSUB(?:S|BED)?\b': 'Softsubs',
        r'\bSUB(?:S|BED|TITLED)?\b': 'Subtitled',
        r'\bESUB(?:S)?\b': 'English Subs',
    }

    EDITIONS = {
        r'\bExtended[\s\.\-_]?Cut\b': 'Extended Cut',
        r'\bExtended[\s\.\-_]?Edition\b': 'Extended Edition',
        r'\bExtended\b': 'Extended',
        r"Director'?s?[\s\.\-_]?Cut": "Director's Cut",
        r'\bDC\b': "Director's Cut",
        r'\bTheatrical[\s\.\-_]?Cut\b': 'Theatrical Cut',
        r'\bTheatrical\b': 'Theatrical',
        r'\bUnrated\b': 'Unrated',
        r'\bUncut\b': 'Uncut',
        r'\bIMAX\b': 'IMAX',
        r'\bSpecial[\s\.\-_]?Edition\b': 'Special Edition',
        r"Collector'?s?[\s\.\-_]?Edition": "Collector's Edition",
        r'\bAnniversary[\s\.\-_]?Edition\b': 'Anniversary Edition',
        r'\bDeluxe[\s\.\-_]?Edition\b': 'Deluxe Edition',
        r'\bLimited[\s\.\-_]?Edition\b': 'Limited Edition',
        r'\bRemastered\b': 'Remastered',
        r'\bRestored\b': 'Restored',
        r'\bCriterion\b': 'Criterion',
        r'\bOpen[\s\.\-_]?Matte\b': 'Open Matte',
        r'\b2in1\b': '2-in-1',
        r'\bFinal[\s\.\-_]?Cut\b': 'Final Cut',
    }

    # Context-aware multi-year markers: when a filename holds multiple
    # year-like tokens (e.g. "2012.2009" where 2012 is part of the title),
    # the release year is the last year that appears before the first of
    # these quality/rip markers (or the last year overall if none is found).
    # Kept as the exact marker set the old parse_metadata fallback used so
    # multi-year selection is provably identical to the previous behavior.
    MULTI_YEAR_MARKERS = re.compile(
        r'(480p|720p|1080p|2160p|4K|WEBRip|BluRay|HDRip|DVDRip|BRRip|CAM|HDTS|WEB-DL)',
        re.IGNORECASE
    )

    # ------------------------------------------------------------------ #
    #  Bracket / prefix / website patterns to strip                        #
    # ------------------------------------------------------------------ #

    # Patterns for leading brackets: [Group], (Group), {Group}
    BRACKET_PREFIX = re.compile(
        r'^(?:'
        r'\[.*?\]'       # [anything]
        r'|\(.*?\)'      # (anything)
        r'|\{.*?\}'      # {anything}
        r')[\s\.\-_]*'
    )

    # Website prefixes commonly prepended to filenames
    WEBSITE_PREFIX = re.compile(
        r'^(?:'
        r'(?:www\.)?[\w\-]+\.(?:com|org|net|to|me|info|cc|ch|ru|io|tv|xyz|site|eu|se|ws|ag|li)'
        r')[\s\.\-_]+',
        re.IGNORECASE
    )

    # Trailing bracketed info: [720p], [YTS.MX], etc.
    BRACKET_SUFFIX = re.compile(
        r'[\s\.\-_]*(?:'
        r'\[.*?\]'
        r'|\(.*?\)'
        r'|\{.*?\}'
        r')\s*$'
    )

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile all regex patterns for performance."""
        self._re_container = re.compile(self.CONTAINERS, re.IGNORECASE)
        self._re_fake_ext = re.compile(self.FAKE_EXTENSIONS, re.IGNORECASE)
        self._re_resolutions = [(re.compile(p, re.IGNORECASE), v) for p, v in self.RESOLUTIONS.items()]
        self._re_sources = [(re.compile(p, re.IGNORECASE), v) for p, v in self.SOURCES.items()]
        self._re_video_codecs = [(re.compile(p, re.IGNORECASE), v) for p, v in self.VIDEO_CODECS.items()]
        self._re_bit_depths = [(re.compile(p, re.IGNORECASE), v) for p, v in self.BIT_DEPTHS.items()]
        self._re_audio_codecs = [(re.compile(p, re.IGNORECASE), v) for p, v in self.AUDIO_CODECS.items()]
        self._re_audio_channels = [(re.compile(p, re.IGNORECASE), v) for p, v in self.AUDIO_CHANNELS.items()]
        self._re_hdr = [(re.compile(p, re.IGNORECASE), v) for p, v in self.HDR_FORMATS.items()]
        self._re_languages = [(re.compile(p, re.IGNORECASE), v) for p, v in self.LANGUAGES.items()]
        self._re_subtitles = [(re.compile(p, re.IGNORECASE), v) for p, v in self.SUBTITLES.items()]
        self._re_editions = [(re.compile(p, re.IGNORECASE), v) for p, v in self.EDITIONS.items()]
        self._re_publishers = [(re.compile(p, re.IGNORECASE), v) for p, v in self.PUBLISHERS.items()]

    # ------------------------------------------------------------------ #
    #  Pre-processing: normalise the raw filename                          #
    # ------------------------------------------------------------------ #

    def _preprocess(self, filename: str) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Clean the raw filename:
          1. Strip path
          2. Extract real container extension
          3. Strip leading [Group] / website prefixes  -> save as release_group candidate
          4. Remove fake embedded extensions (e.g. _avi)
        Returns (cleaned_name, container, bracket_group)
        """
        name = filename.strip()

        # Strip path
        for sep in ('/', '\\'):
            if sep in name:
                name = name.rsplit(sep, 1)[-1]

        # Real container
        container = None
        cm = self._re_container.search(name)
        if cm:
            container = cm.group(1).lower()
            name = name[:cm.start()]

        # Leading bracket group  [Dex]  (Dex)  {Dex}
        bracket_group = None
        bm = self.BRACKET_PREFIX.match(name)
        if bm:
            raw = bm.group(0).strip()
            # extract content inside brackets
            inner = re.search(r'[\[\(\{](.*?)[\]\)\}]', raw)
            if inner:
                bracket_group = inner.group(1).strip()
            name = name[bm.end():]

        # Leading website prefix
        wm = self.WEBSITE_PREFIX.match(name)
        if wm:
            name = name[wm.end():]

        # Strip trailing bracket noise — but only if the content looks like
        # metadata (resolution, codec, source, bitrate, etc.).  Brackets
        # containing a release-year, season/episode marker, or other
        # identifying data must survive so _extract_series_info can see them.
        #
        # Example that broke before this guard:
        #   "Fauda (2015) S02E11 (1080p ...) [UTR].mkv"
        #   The \(.*?\) regex matched (2015) S02E11 (1080p ...) as one giant
        #   group (expanding until \) hit the final ')') and stripped the
        #   series info along with the metadata.
        _META_KEYWORDS = re.compile(
            r'(?:\d{3,4}p|\d{3,4}x\d{3,4}'   # resolution
            r'|x26[45]|h26[45]|hevc|avc|av1|vp9|xvid|divx'  # codecs
            r'|bluray|bdrip|brrip|webrip|web-dl|webdl|hdtv|dvdrip|hdrip'  # source
            r'|aac|ac3|dts|dd[p+]?(?:\s|\d|$)|eac3|opus|flac'  # audio
            r'|10bit|8bit|hdr|hdr10|hdr10\+|dv|dolby'  # bit-depth/HDR
            r'|h\.?264|h\.?265|avc|hev'  # alternate codec spellings
            r')',
            re.IGNORECASE
        )
        _SERIES_RE = re.compile(
            r'\bS\d{1,3}[Ee]\d|\bS\d{1,3}\b|\bE\d{1,4}\b'
            r'|\b\d{1,2}[xX]\d{2,3}\b|\b[12][09]\d{2}\b',
            re.IGNORECASE
        )
        while True:
            sm = self.BRACKET_SUFFIX.search(name)
            if not sm:
                break
            # Extract just the bracketed content
            inner_m = re.search(r'[\[\(\{](.*?)[\]\)\}]', sm.group(0))
            inner = inner_m.group(1) if inner_m else sm.group(0)
            # Keep if it contains a series marker or year — it's not metadata
            if _SERIES_RE.search(inner):
                break
            # Keep if it doesn't look like metadata at all (e.g. just a
            # release group tag like "[YTS.MX]" is fine, but "(2015)" alone
            # should not be stripped here — years are extracted elsewhere)
            if not _META_KEYWORDS.search(inner):
                # Allow very short tags (release groups like [UTR], [TAoE])
                # but stop stripping if it's a bare year
                if re.match(r'^\s*\(?\d{4}\)?\s*$', inner):
                    break
                # Short alphanumeric tags (≤8 chars) are likely group tags
                if len(inner.strip()) <= 8:
                    name = name[:sm.start()]
                    continue
                # Longer non-metadata content — stop stripping
                break
            name = name[:sm.start()]

        # Remove fake embedded extensions: "webrip_avi" -> "webrip"
        # Only remove if the fake ext is NOT preceded by a title-like word pattern
        # i.e. it is after a known tag
        name = self._re_fake_ext.sub('', name)

        return name.strip(' ._-'), container, bracket_group

    # ------------------------------------------------------------------ #
    #  Main parse method                                                   #
    # ------------------------------------------------------------------ #

    def parse(self, filename: str) -> ParsedMedia:
        """Parse a movie/series filename and return structured info."""
        result = ParsedMedia(original_filename=filename)

        # --- Pre-process ---
        name, container, bracket_group = self._preprocess(filename)
        result.container = container

        # --- Release group: trailing -GROUP or bracket prefix ---
        group_match = re.search(r'-([A-Za-z0-9]+)$', name)
        if group_match:
            potential_group = group_match.group(1)
            if not re.match(
                r'^(?:x264|x265|h264|h265|HEVC|AVC|XviD|DivX|VP9|AV1|'
                r'DL|Rip|HD|SD|MA|HR|EX|E\d+|S\d+|\d{3,4}p)$',
                potential_group, re.IGNORECASE
            ):
                result.release_group = potential_group
                name = name[:group_match.start()]
        elif bracket_group:
            result.release_group = bracket_group

        # Normalise separators for matching (keep original for title extraction)
        # Replace _ with . for uniform matching, but remember positions
        working = name

        # --- Series info ---
        self._extract_series_info(working, result)

        # --- Metadata ---
        result.resolution = self._find_first(self._re_resolutions, working)
        result.source = self._find_first(self._re_sources, working)
        result.video_codec = self._find_first(self._re_video_codecs, working)
        result.audio_codec = self._find_first(self._re_audio_codecs, working)
        result.audio_channels = self._find_first(self._re_audio_channels, working)
        result.bit_depth = self._find_first(self._re_bit_depths, working)
        result.hdr = self._find_first(self._re_hdr, working)

        # --- Supplement: full-text scan for fields the pre-processor hides ---
        # The pre-processor strips trailing bracket groups, and underscores
        # are word-chars, so the \b-anchored patterns above miss metadata in
        # brackets or underscore-separated names (e.g. "1080p" in
        # "Top_Gun_Maverick_2022_1080p_WEBRip..." or "[2160p]" in
        # "The Batman (2022) [2160p]"). Re-scan a separator-normalised copy of
        # the raw input so the engine - not parse_metadata fallbacks - owns
        # quality, bit depth, audio channels, source (rip types), audio
        # codecs, video codecs and HDR.
        raw_scan = re.sub(r"[_\\.]+", " ", filename)
        if result.resolution is None:
            result.resolution = self._find_first(self._re_resolutions, raw_scan)
        result.quality = result.resolution
        # x-dimension resolution (e.g. 1920x1080): not p-suffixed, so the
        # resolution patterns above cannot see it. quality deliberately does
        # NOT follow this (mirrors the old parse_metadata behavior).
        if result.resolution is None:
            xdim = re.search(r'(\d{3,4}x\d{3,4})', raw_scan)
            if xdim:
                result.resolution = xdim.group(1)
        # IMDB ID (tt1234567) - engine-owned field, scanned on the raw text.
        imdb_m = re.search(r'(tt\d{6,8})', raw_scan, re.I)
        if imdb_m:
            result.imdb_id = imdb_m.group(1)
        if result.bit_depth is None:
            result.bit_depth = self._find_first(self._re_bit_depths, raw_scan)
        if result.audio_channels is None:
            result.audio_channels = self._find_first(self._re_audio_channels, raw_scan)
        if result.source is None:
            result.source = self._find_first(self._re_sources, raw_scan)
        if result.audio_codec is None:
            result.audio_codec = self._find_first(self._re_audio_codecs, raw_scan)
        if result.video_codec is None:
            result.video_codec = self._find_first(self._re_video_codecs, raw_scan)
        if result.hdr is None:
            result.hdr = self._find_first(self._re_hdr, raw_scan)
        # Spelled-out publishers can coexist with a rip-type source (e.g.
        # "Hulu.WEBRip") - the single `source` field holds the first match
        # only, so track publishers separately for parse_metadata to surface.
        result.publisher = self._find_first(self._re_publishers, raw_scan)
        result.language = self._find_first(self._re_languages, working)
        result.subtitles = self._find_first(self._re_subtitles, working)
        result.edition = self._find_first(self._re_editions, working)

        # --- Flags ---
        result.is_proper = bool(re.search(r'\bPROPER\b', working, re.IGNORECASE))
        result.is_repack = bool(re.search(r'\bREPACK\b', working, re.IGNORECASE))
        result.is_remux = bool(re.search(r'\bREMUX\b', working, re.IGNORECASE))
        result.is_3d = bool(re.search(r'\b3D\b', working, re.IGNORECASE))
        result.is_hardcoded_subs = bool(
            re.search(r'\b(?:HC|HARDCODED|HARDSUB)\b', working, re.IGNORECASE)
        )

        if result.edition:
            result.is_extended = 'Extended' in result.edition
            result.is_directors_cut = 'Director' in result.edition
            result.is_unrated = 'Unrated' in result.edition

        if re.search(r'Complete[\s\.\-_]?Series', working, re.IGNORECASE):
            result.is_complete_series = True
            result.is_series = True
        if re.search(
            r'(?:Complete[\s\.\-_]?Season|Season[\s\.\-_]?\d+[\s\.\-_]?Complete|'
            r'S\d+[\s\.\-_]?Complete)',
            working, re.IGNORECASE
        ):
            result.season_pack = True
            result.is_series = True

        # --- Extra tags ---
        extra_tags_patterns = [
            (r'\bINTERNAL\b', 'INTERNAL'),
            (r'\bLiMiTED\b', 'LIMITED'),
            (r'\bRARBG\b', 'RARBG'),
            (r'\bYTS\b', 'YTS'),
            (r'\bYIFY\b', 'YIFY'),
            (r'\bGALAXY[\s\.\-_]?RG\b', 'GalaxyRG'),
            (r'\bPSA\b', 'PSA'),
            (r'\bREADNFO\b', 'READNFO'),
            (r'\bRETAIL\b', 'RETAIL'),
            (r'\bNUKED\b', 'NUKED'),
            (r'\bFIX\b', 'FIX'),
            (r'\bSAMPLE\b', 'SAMPLE'),
            (r'\bDUBBED\b', 'DUBBED'),
            (r'\bSUBBED\b', 'SUBBED'),
            (r'\bCOMPLETE\b', 'COMPLETE'),
            (r'\bMINI[\s\.\-_]?SERIES\b', 'MINISERIES'),
        ]
        for pattern, tag in extra_tags_patterns:
            if re.search(pattern, working, re.IGNORECASE):
                result.tags.append(tag)

        # --- Year ---
        year_match = self._extract_year(working, result)
        if result.year is None:
            # The pre-processor strips trailing bracket groups (e.g. "(1994)"
            # in "The Shawshank Redemption (1994) [...]"), which can hide the
            # release year from the preprocessed name. Fall back to the raw
            # full-text scan for the year value; the title needs no cut here
            # because the stripped groups are trailing title-noise.
            self._extract_year(raw_scan, result)
        # --- Title ---
        result.title = self._extract_title(working, result, year_match)

        return result

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _find_first(self, compiled_patterns: list, text: str) -> Optional[str]:
        for regex, value in compiled_patterns:
            if regex.search(text):
                return value
        return None

    def _extract_series_info(self, name: str, result: ParsedMedia):
        """Detect and extract TV series season/episode information."""
        # S01E01, S01E01E02, S01E01-E03
        m = re.search(r'[Ss](\d{1,3})[Ee](\d{1,4})(?:[\-]?[Ee](\d{1,4}))?', name)
        if m:
            result.is_series = True
            result.season = int(m.group(1))
            result.episode = int(m.group(2))
            if m.group(3):
                result.episode_end = int(m.group(3))
            return

        # 1x01 format  — also handles underscore/dot separators
        m = re.search(r'(?<!\d)(\d{1,2})[xX](\d{2,3})(?:[\-](\d{2,3}))?', name)
        if m:
            result.is_series = True
            result.season = int(m.group(1))
            result.episode = int(m.group(2))
            if m.group(3):
                result.episode_end = int(m.group(3))
            return

        # Season XX Episode YY
        m = re.search(
            r'Season[\s\.\-_]?(\d{1,3})[\s\.\-_]*(?:Episode[\s\.\-_]?(\d{1,4}))?',
            name, re.IGNORECASE
        )
        if m:
            result.is_series = True
            result.season = int(m.group(1))
            if m.group(2):
                result.episode = int(m.group(2))
            return

        # S01 only (season pack)
        m = re.search(r'(?<![A-Za-z])S(\d{1,3})(?![Ee\d])', name)
        if m:
            result.is_series = True
            result.season = int(m.group(1))
            result.season_pack = True
            return

        # Standalone E01 (no season)
        m = re.search(r'(?<![A-Za-z])[Ee](\d{2,4})(?![A-Za-z\d])', name)
        if m:
            result.is_series = True
            result.episode = int(m.group(1))
            return

        # " - 01" anime style  (hyphen then episode number)
        m = re.search(r'[\s\.\-_]-[\s\.\-_](\d{2,4})(?:[\s\.\-_]|$)', name)
        if m:
            result.is_series = True
            result.episode = int(m.group(1))
            return

    def _extract_year(self, name: str, result: ParsedMedia) -> Optional[re.Match]:
        """Find and extract the RELEASE year from the filename.

        When a filename contains several year-like tokens (e.g.
        "2012.2009.1080p" where 2012 is part of the title), a context-aware
        heuristic picks the release year: the LAST year that appears before
        the first quality/rip metadata marker, or the last year overall when
        no marker is present. Returning the selected match lets _extract_title
        cut the title at exactly that position.
        """
        year_pattern = re.compile(
            r'(?<![xXhH\d])[\.\s\(\[\-_]?((?:19|20)\d{2})(?:[\.\s\)\]\-_]|$)'
        )
        matches = []
        for m in year_pattern.finditer(name):
            year_val = int(m.group(1))
            if not (1920 <= year_val <= 2029):
                continue
            # Skip if the year is directly followed by a resolution suffix
            # (e.g. the "p" in "2160p"). The match already consumed a
            # trailing separator, so inspect the char after the digits -
            # checking past the separator would misfire on e.g. "2021.IMAX".
            digits_end = m.start(1) + 4
            nxt = name[digits_end:digits_end+1] if digits_end < len(name) else ''
            if nxt and nxt.lower() in ('p', 'i'):
                continue
            matches.append(m)

        if not matches:
            return None

        if len(matches) == 1:
            result.year = int(matches[0].group(1))
            return matches[0]

        # Multiple year tokens - context-aware selection: the release year is
        # the last year before the first metadata marker, else the last year.
        marker = self.MULTI_YEAR_MARKERS.search(name)
        if marker:
            before = [m for m in matches if m.start() < marker.start()]
            chosen = max(before, key=lambda m: m.start(), default=matches[-1])
        else:
            chosen = matches[-1]
        result.year = int(chosen.group(1))
        return chosen

    def _extract_title(self, name: str, result: ParsedMedia,
                       year_match) -> str:
        """Extract the clean title from the working filename string."""
        cut_points: List[int] = []

        if year_match:
            cut_points.append(year_match.start())

        # Series markers
        for pattern in [
            r'[Ss]\d{1,3}[Ee]\d',
            r'[Ss]\d{1,3}(?![A-Za-z])',
            r'(?<!\d)\d{1,2}[xX]\d{2,3}',
            r'Season[\s\.\-_]?\d',
            r'Episode[\s\.\-_]?\d',
            r'[\s\.\-_]-[\s\.\-_]\d{2,4}(?:[\s\.\-_]|$)',   # anime " - 01"
        ]:
            m = re.search(pattern, name, re.IGNORECASE)
            if m:
                cut_points.append(m.start())

        # All metadata patterns as cut points
        all_meta = []
        for dict_patterns in [self.RESOLUTIONS, self.SOURCES, self.VIDEO_CODECS,
                               self.AUDIO_CODECS, self.BIT_DEPTHS, self.EDITIONS,
                               self.PUBLISHERS]:
            all_meta.extend(dict_patterns.keys())
        all_meta.extend([
            r'\bPROPER\b', r'\bREPACK\b', r'\bREMUX\b',
            r'\bINTERNAL\b', r'\bLiMiTED\b', r'\b3D\b',
            r'\bDUAL[\s\.\-_]?Audio\b', r'\bMULTi\b',
        ])

        for pattern in all_meta:
            try:
                m = re.search(pattern, name, re.IGNORECASE)
                if m:
                    cut_points.append(m.start())
            except re.error:
                continue

        # Also cut at fake extension remnants
        for ext in ('avi', 'mkv', 'mp4', 'divx', 'wmv'):
            m = re.search(r'[\.\s_\-]' + ext + r'(?:[\.\s_\-]|$)', name, re.IGNORECASE)
            if m:
                cut_points.append(m.start())

        if cut_points:
            title_end = min(p for p in cut_points if p > 0) if any(p > 0 for p in cut_points) else len(name)
            title = name[:title_end]
        else:
            title = name

        # Clean
        title = title.strip(' ._-[](){}')
        title = re.sub(r'[\._]', ' ', title)
        title = re.sub(r'[\s\-]+$', '', title)
        title = re.sub(r'\s+', ' ', title)
        # Remove any remaining leading/trailing bracket content
        title = re.sub(r'^\[.*?\]\s*', '', title)
        title = re.sub(r'\(.*?\)\s*$', '', title)
        title = title.strip()

        return title

    def parse_batch(self, filenames: list) -> List[ParsedMedia]:
        """Parse a list of filenames."""
        return [self.parse(fn) for fn in filenames]


BRACKET_TAG_RE = re.compile(r"\[([^\]]+)\]|\(([^\)]+)\)|\{([^\}]+)\}")

# Initialize parser instance once
_filename_parser = MovieFilenameParser()

def parse_metadata(caption: str = None, filename: str = None) -> dict:
    """
    Robust parsing: delegates entirely to MovieFilenameParser (which owns all
    fields including the context-aware multi-year release-year/title selection,
    IMDB IDs and x-dimension resolutions) and maps the result to the legacy
    dict shape. No fallback parsing logic lives here.
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
            if re.search(r"webrip|web-dl|web dl|bluray|bdrip|bd5|brrip|hdtv|pdtv|dsrip|dvdrip|dvdr|dvdscr|screener|r5|camrip|cam|tsrip|tcrip|hdcam|hdts|ppv|vodrip|satrip|dthrip", parsed_media.source, re.I):
                md["rip"] = parsed_media.source
            else:
                md["source"] = parsed_media.source
        # Spelled-out publisher (Netflix/Amazon/...): the engine's single
        # `source` field can only hold one token and rip types win first-match,
        # so a coexisting publisher (e.g. "Hulu.WEBRip") is surfaced here when
        # no source was already set.
        if md["source"] is None and parsed_media.publisher:
            md["source"] = parsed_media.publisher
                
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

        # Map bit depth (engine-provided)
        md["bit_depth"] = parsed_media.bit_depth

        # Map IMDB ID (engine-provided)
        md["imdb"] = parsed_media.imdb_id
        
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

    # 3. Zero fallback logic.
    #
    # The engine (MovieFilenameParser) now owns ALL parsing: quality/rip/
    # source/audio/video/HDR/bit-depth/channels/publisher, the context-aware
    # multi-year release-year + title selection, IMDB IDs (tt1234567) and
    # x-dimension resolutions (1920x1080). parse_metadata is a pure mapper
    # from ParsedMedia to the legacy dict shape.


    return md

                                                                    #
# ====================================================================== #

def demo():
    test_filenames = [
        # THE ORIGINAL PROBLEM CASE
        "[Dex]_Avenging_Death_1x09_webrip_avi.mkv",

        # More edge cases like it
        "[SubGroup] Naruto Shippuden - 001 [720p] [BDRip].mkv",
        "[HorribleSubs] Attack on Titan - 25 [1080p].mkv",
        "[Judas] One Piece - 1085 (1080p) [E7A9F654].mkv",
        "(Hi10) Steins Gate - 01 (BD 1080p) (Dual Audio) [FLAC].mkv",
        "[YTS.MX] The Batman (2022) [2160p] [4K] [WEB] [5.1].mp4",
        "www.Torrenting.com - Dune Part Two 2024 2160p WEB-DL.mkv",
        "[TorrentCouch.com].Dune.2021.1080p.WEB-DL.DD5.1.x264.mkv",

        # Standard movies
        "The.Matrix.1999.1080p.BluRay.x264-GROUP.mkv",
        "Inception.2010.2160p.UHD.BluRay.HDR.DTS-HD.MA.5.1.x265-TERMiNAL.mkv",
        "The Shawshank Redemption (1994) [1080p] [BluRay] [5.1] [YTS.MX].mp4",
        "Oppenheimer.2023.IMAX.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1-FGT.mkv",

        # Editions
        "Kingdom.of.Heaven.2005.Directors.Cut.1080p.BluRay.x264-SPARKS.mkv",
        "Blade.Runner.1982.The.Final.Cut.2160p.UHD.BluRay.HDR10.x265-TERMiNAL.mkv",

        # TV Series
        "Breaking.Bad.S05E16.Felina.720p.BluRay.x264-DEMAND.mkv",
        "Game.of.Thrones.S08E06.The.Iron.Throne.1080p.AMZN.WEB-DL.DDP5.1.H.264-GoT.mkv",
        "Stranger.Things.S04E01-E02.1080p.NF.WEB-DL.DDP5.1.Atmos.x264-TEPES.mkv",
        "Friends.1x01.The.One.Where.Monica.Gets.a.Roommate.DVDRip.XviD-SAiNTS.avi",
        "The.Office.US.S01.COMPLETE.720p.BluRay.x264-DEMAND.mkv",
        "The 100 S03E01 720p.mkv",

        # Underscore heavy
        "Top_Gun_Maverick_2022_1080p_WEBRip_x264_AAC-[YTS.MX].mp4",
        "The_Dark_Knight_2008_BluRay_1080p_x264_DTS-HD_MA_5.1.mkv",
        "[Dex]_Some_Movie_2019_BDRip_x264_avi.mp4",

        # International
        "Parasite.2019.KOREAN.1080p.BluRay.x264.DTS-HD.MA.5.1-FGT.mkv",
        "RRR.2022.HINDI.2160p.AMZN.WEB-DL.DDP5.1.H265-FLAVOR.mkv",

        # Year in title
        "Blade.Runner.2049.2017.1080p.BluRay.x264-SPARKS.mkv",
        "2001.A.Space.Odyssey.1968.2160p.UHD.BluRay.x265-SURCODE.mkv",

        # Minimal info
        "movie.mkv",
        "12 Angry Men 1957 1080p BluRay x265 HEVC AAC-SARTRE.mkv",
        "Se7en.1995.REMASTERED.1080p.BluRay.x264-SWTYBLZ.mkv",

        # Season packs
        "Chernobyl.S01.Complete.1080p.BluRay.x264-DEMAND.mkv",
        "Band.of.Brothers.Complete.Series.1080p.BluRay.x264-DEMAND.mkv",
    ]

    parser = MovieFilenameParser()

    print("=" * 110)
    print("  MOVIE/SERIES FILENAME PARSER v2 — DEMO")
    print("=" * 110)

    for fn in test_filenames:
        result = parser.parse(fn)
        print(f"\n{'─' * 110}")
        print(f"  INPUT:  {fn}")
        print(f"  PARSED: {result}")

    print(f"\n{'═' * 110}")
    print(f"  Parsed {len(test_filenames)} filenames successfully.")
    print(f"{'═' * 110}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        parser = MovieFilenameParser()
        for arg in sys.argv[1:]:
            result = parser.parse(arg)
            print(f"\nInput:  {arg}")
            print(f"Parsed: {result}")
    else:
        demo()