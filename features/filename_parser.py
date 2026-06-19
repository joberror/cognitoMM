"""
Movie/Series Filename Parser v2
Enhanced to handle edge-case filenames like:
  [Dex]_Avenging_Death_1x09_webrip_avi.mkv
  [SubGroup] Show Name - 01 [720p].mkv
  Show.Name.2024.E05.WEBRip.mkv
  (Release) Movie_Name_2020_HDRip.mp4
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
    audio_codec: Optional[str] = None
    audio_channels: Optional[str] = None
    hdr: Optional[str] = None
    release_group: Optional[str] = None
    edition: Optional[str] = None
    language: Optional[str] = None
    subtitles: Optional[str] = None
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
                      'audio_codec', 'audio_channels', 'hdr', 'release_group',
                      'edition', 'language', 'subtitles', 'container']:
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
        r'\b10[\s\.\-_]?bit\b': '10bit',
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
        r'\bMP3\b': 'MP3',
        r'\bOGG\b': 'OGG',
        r'\bOPUS\b': 'OPUS',
        r'\bPCM\b': 'PCM',
        r'\bLPCM\b': 'LPCM',
    }

    AUDIO_CHANNELS = {
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
        self._re_audio_codecs = [(re.compile(p, re.IGNORECASE), v) for p, v in self.AUDIO_CODECS.items()]
        self._re_audio_channels = [(re.compile(p, re.IGNORECASE), v) for p, v in self.AUDIO_CHANNELS.items()]
        self._re_hdr = [(re.compile(p, re.IGNORECASE), v) for p, v in self.HDR_FORMATS.items()]
        self._re_languages = [(re.compile(p, re.IGNORECASE), v) for p, v in self.LANGUAGES.items()]
        self._re_subtitles = [(re.compile(p, re.IGNORECASE), v) for p, v in self.SUBTITLES.items()]
        self._re_editions = [(re.compile(p, re.IGNORECASE), v) for p, v in self.EDITIONS.items()]

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

        # Strip trailing bracket noise  [YTS.MX]  (1080p)  etc.
        while True:
            sm = self.BRACKET_SUFFIX.search(name)
            if sm:
                name = name[:sm.start()]
            else:
                break

        # Remove fake embedded extensions: "webrip_avi" -> "webrip"
        # Only remove if the fake ext is NOT preceded by a title-like word pattern
        # i.e. it is after a known tag
        name = self._re_fake_ext.sub('', name)

        return name.strip(' .\-_'), container, bracket_group

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
        result.hdr = self._find_first(self._re_hdr, working)
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
        """Find and extract the year from the filename."""
        year_pattern = re.compile(
            r'(?<![xXhH\d])[\.\s\(\[\-_]?((?:19|20)\d{2})(?:[\.\s\)\]\-_]|$)'
        )
        matches = list(year_pattern.finditer(name))
        for m in matches:
            year_val = int(m.group(1))
            if 1920 <= year_val <= 2029:
                # Skip if it looks like a resolution (e.g. 2160p, 1080p)
                after = name[m.end():m.end()+2] if m.end() < len(name) else ''
                if after and after[0].lower() in ('p', 'i'):
                    continue
                result.year = year_val
                return m
        return None

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
                               self.AUDIO_CODECS, self.EDITIONS]:
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
        title = title.strip(' .\-_[](){}')
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


# ====================================================================== #
#  Demo                                                                    #
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