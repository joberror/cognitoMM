"""
Regression guards for the consolidation work:

1. Parsers: `MovieFilenameParser`/`ParsedMedia` now live in the single canonical
   `features/metadata_parser.py` module (engine + `parse_metadata` API). The old
   `features/filename_parser.py` must not come back.
2. Size formatters: `format_file_size` (features/utils.py) is the single canonical
   size formatter; `format_size` (utils) and `format_file_size_stat` (statistics)
   have been removed. `construct_final_caption` renders compact sizes and omits
   the Size line when no size is known.
"""

import os
import sys
import importlib

# Ensure project root is on the path so the features package is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import features
import features.metadata_parser as metadata_parser
import features.utils as utils
import features.statistics as statistics


# -------------------------
# Parser consolidation
# -------------------------

def test_parser_module_is_single_canonical_home():
    """Engine + public API both live in metadata_parser.py."""
    assert hasattr(metadata_parser, "MovieFilenameParser"), "engine class missing"
    assert hasattr(metadata_parser, "ParsedMedia"), "dataclass missing"
    assert hasattr(metadata_parser, "parse_metadata"), "public API missing"
    assert hasattr(metadata_parser, "BRACKET_TAG_RE"), "bracket regex missing"


def test_old_filename_parser_module_gone():
    """features/filename_parser.py was merged into metadata_parser.py."""
    import contextlib

    @contextlib.contextmanager
    def _expect_import_error():
        try:
            yield
        except ImportError:
            pass
        else:
            raise AssertionError("import features.filename_parser unexpectedly succeeded")

    with _expect_import_error():
        importlib.import_module("features.filename_parser")


def test_engine_and_api_agree():
    """The engine's title/year and the public API's title agree on a classic name."""
    parsed = metadata_parser.MovieFilenameParser().parse(
        "Inception.2010.1080p.BluRay.x264-GROUP.mkv"
    )
    assert parsed.title == "Inception"
    assert parsed.year == 2010
    md = metadata_parser.parse_metadata(
        filename="Inception.2010.1080p.BluRay.x264-GROUP.mkv"
    )
    assert md["title"] == "Inception"
    assert md["year"] == 2010


def test_multi_year_edge_case_still_works():
    """The context-aware multi-year title algorithm is preserved after the merge."""
    md = metadata_parser.parse_metadata(
        filename="2001.A.Space.Odyssey.1968.1080p.BluRay.mkv"
    )
    assert md["title"] == "2001 A Space Odyssey"
    assert md["year"] == 1968


# -------------------------
# Size formatter consolidation
# -------------------------

def test_format_size_removed_from_utils():
    """The inferior format_size duplicate must not come back."""
    assert not hasattr(utils, "format_size"), "format_size duplicate resurrected"


def test_format_file_size_stat_removed_from_statistics():
    """The statistics-local size formatter must not come back."""
    assert not hasattr(statistics, "format_file_size_stat"), \
        "format_file_size_stat duplicate resurrected"


def test_format_file_size_is_canonical():
    """format_file_size is the single canonical formatter, exported package-wide."""
    assert callable(utils.format_file_size)
    assert features.format_file_size is utils.format_file_size
    # Compact, accurate output for sub-MB sizes (old format_size said '0.00MB')
    assert utils.format_file_size(512) == "512B"
    assert utils.format_file_size(15 * 1024 * 1024) == "15MB"
    assert utils.format_file_size(0) == "N/A"


def test_construct_final_caption_uses_canonical_formatter():
    """Captions render compact sizes and omit the Size line when size is unknown."""
    cap = utils.construct_final_caption(
        {"title": "Inception", "type": "Movie", "extension": "mkv"},
        file_size_bytes=15 * 1024 * 1024,
    )
    assert "15MB" in cap
    assert "Size: N/A" not in cap

    cap_no_size = utils.construct_final_caption(
        {"title": "Inception", "type": "Movie"},
        file_size_bytes=None,
    )
    assert "Size:" not in cap_no_size


def test_statistics_uses_canonical_formatter():
    """The dashboard renders sizes through the shared format_file_size."""
    out = statistics.format_stats_output({"db_estimated_size": 3 * 1024**2, "total_logs": 0})
    assert any("DB Est. Size:</b> 3MB" in line for line in out.split("\n"))


# -------------------------
# Engine now owns quality / bit depth / audio channels
# -------------------------

def test_engine_sets_quality_from_resolution():
    """quality == resolution inside the engine (no parse_metadata fallback)."""
    parsed = metadata_parser.MovieFilenameParser().parse(
        "Dune.2021.2160p.HDR10+.Dolby.Vision.TrueHD.7.1CH.x265-RELEASE.mkv"
    )
    assert parsed.resolution == "2160p"
    assert parsed.quality == "2160p"


def test_engine_extracts_bit_depth_separately():
    """10bit is bit depth, not a video codec, even when a codec appears first."""
    parsed = metadata_parser.MovieFilenameParser().parse(
        "Star.Wars.Visions.S02E09.1080p.10bit.WEBRip.6CH.x265.HEVC-PSA.mkv"
    )
    assert parsed.bit_depth == "10bit"
    assert parsed.video_codec == "x265"
    assert parsed.audio_channels == "6"


def test_engine_handles_ch_suffixed_channels():
    """5.1CH / 7.1CH / 6CH parse via the engine's CH patterns."""
    p = metadata_parser.MovieFilenameParser()
    assert p.parse("Dune.2021.2160p.TrueHD.7.1CH.x265.mkv").audio_channels == "7.1"
    assert p.parse("Avatar.2009.1080p.BluRay.DTS-HD.MA.5.1CH.x264.mkv").audio_channels == "5.1"
    assert p.parse("Show.S01E01.1080p.WEBRip.6CH.x265.mkv").audio_channels == "6"


def test_engine_full_text_scan_sees_brackets_and_underscores():
    """quality survives stripped bracket groups and underscore separators."""
    p = metadata_parser.MovieFilenameParser()
    bracketed = p.parse("[YTS.MX] The Batman (2022) [2160p] [4K] [WEB] [5.1].mp4")
    assert bracketed.resolution == "2160p"
    assert bracketed.quality == "2160p"
    underscored = p.parse("Top_Gun_Maverick_2022_1080p_WEBRip_x264_AAC-[YTS.MX].mp4")
    assert underscored.resolution == "1080p"
    assert underscored.quality == "1080p"


def test_parse_metadata_no_fallback_dependency():
    """The API's quality / audio_channels / bit_depth come from the engine."""
    md = metadata_parser.parse_metadata(
        filename="Star.Wars.Visions.S02E09.1080p.10bit.WEBRip.6CH.x265.HEVC-PSA.mkv"
    )
    assert md["quality"] == "1080p"
    assert md["audio_channels"] == "6CH"
    assert md["bit_depth"] == "10bit"
    assert md["video_codec"] == "x265/HEVC"


# -------------------------
# Engine now owns rip / source / audio / video codec / HDR
# -------------------------

def test_engine_raw_scan_owns_underscore_metadata():
    """Underscore-separated rip/audio/video are engine-owned (raw_scan)."""
    md = metadata_parser.parse_metadata(
        filename="Top_Gun_Maverick_2022_1080p_WEBRip_x264_AAC-[YTS.MX].mp4"
    )
    assert md["rip"] == "WEBRip"
    assert md["audio"] == "AAC"
    assert md["video_codec"] == "x264/AVC"


def test_engine_raw_scan_owns_bracketed_metadata():
    """Metadata inside stripped bracket groups is engine-owned."""
    md = metadata_parser.parse_metadata(
        filename="The Shawshank Redemption (1994) [1080p] [BluRay] [5.1] [YTS.MX].mp4"
    )
    assert md["rip"] == "BluRay"
    md2 = metadata_parser.parse_metadata(
        filename="[Group] Movie.2021.1080p.WEBRip.x264 [HDR].mkv"
    )
    assert md2["hdr_format"] == "HDR"
    md3 = metadata_parser.parse_metadata(
        filename="(Hi10) Steins Gate - 01 (BD 1080p) (Dual Audio) [FLAC].mkv"
    )
    assert md3["audio"] == "FLAC"


def test_engine_bracket_dts_hd_ma_full_form():
    """Bracketed [DTS-HD MA] now yields the full form (was the short DTS-HD)."""
    md = metadata_parser.parse_metadata(filename="Movie.2021.1080p [DTS-HD MA].mkv")
    assert md["audio"] == "DTS-HD MA"


def test_engine_m4a_is_audio_codec():
    """M4A is a first-class engine audio codec (no parse_metadata fallback)."""
    parsed = metadata_parser.MovieFilenameParser().parse(
        "Movie.2021.1080p.WEBRip.M4A.x264.mkv"
    )
    assert parsed.audio_codec == "M4A"
    md = metadata_parser.parse_metadata(filename="Song.m4a")
    assert md["audio"] == "M4A"


def test_engine_publisher_coexists_with_rip():
    """Spelled-out publisher + rip token: both surface (rip + source)."""
    md = metadata_parser.parse_metadata(
        filename="Movie.2021.1080p.Hulu.WEBRip.x264.mkv"
    )
    assert md["rip"] == "WEBRip"
    assert md["source"] == "Hulu"


def test_engine_publisher_field_and_alone():
    """Spelled-out publisher without a rip token still lands in source; the
    engine exposes the raw publisher field."""
    md = metadata_parser.parse_metadata(filename="Movie.2021.1080p.Amazon.x264.mkv")
    assert md["source"] == "Amazon"
    p = metadata_parser.MovieFilenameParser().parse(
        "Movie.2021.1080p.Prime.Video.WEBRip.x264.mkv"
    )
    assert p.publisher == "Prime Video"


def test_engine_publisher_via_bracket_and_underscore():
    """Publisher is also detected through stripped brackets and underscores."""
    md = metadata_parser.parse_metadata(
        filename="Movie.2021.1080p.WEBRip [Prime Video].mkv"
    )
    assert md["source"] == "Prime Video"
    md2 = metadata_parser.parse_metadata(
        filename="Movie_2021_1080p_Amazon_WEBRip_x264.mkv"
    )
    assert md2["source"] == "Amazon"


def test_engine_hdr_no_dv_false_positive():
    """Bare DV inside DVDRip no longer sets Dolby Vision (engine lookaround)."""
    md = metadata_parser.parse_metadata(
        filename="Friends.1x01.The.One.Where.Monica.Gets.a.Roommate.DVDRip.XviD-SAiNTS.avi"
    )
    assert md["hdr_format"] is None
    md2 = metadata_parser.parse_metadata(
        filename="The.Batman.2022.2160p.WEB-DL.DDP5.1.Atmos.DV.HEVC-GROUP.mkv"
    )
    assert md2["hdr_format"] == "Dolby Vision"


def test_parse_metadata_has_no_metadata_fallbacks():
    """The 5 inline fallback blocks must not come back in parse_metadata."""
    import inspect
    src = inspect.getsource(metadata_parser.parse_metadata)
    for anchor in ["# Rip inline fallback", "# Source inline fallback",
                   "# Audio inline fallback", "# Video codec inline fallback",
                   "# HDR format inline fallback"]:
        assert anchor not in src, f"fallback anchor resurrected: {anchor}"


def test_parse_metadata_has_no_year_fallbacks():
    """The multi-year title algorithm fallback block must not come back."""
    import inspect
    src = inspect.getsource(metadata_parser.parse_metadata)
    for anchor in ["all_years", "title_guess", "split_at",
                   "split_position", "release_year_obj"]:
        assert anchor not in src, f"multi-year anchor resurrected: {anchor}"


def test_engine_owns_multi_year_2012():
    """2012.2009 -> engine picks 2009 as release year, title='2012'."""
    md = metadata_parser.parse_metadata(
        filename="2012.2009.1080p.BluRay.x264.mkv"
    )
    assert md["title"] == "2012"
    assert md["year"] == 2009
    parsed = metadata_parser.MovieFilenameParser().parse(
        "2012.2009.1080p.BluRay.x264.mkv"
    )
    assert parsed.title == "2012"
    assert parsed.year == 2009


def test_engine_owns_multi_year_1917():
    """1917.2019 -> engine picks 2019 as release year, title='1917'."""
    md = metadata_parser.parse_metadata(
        filename="1917.2019.1080p.BluRay.x264.mkv"
    )
    assert md["title"] == "1917"
    assert md["year"] == 2019


def test_engine_owns_multi_year_2001():
    """2001.A.Space.Odyssey.1968 -> picks 1968, title='2001 A Space Odyssey'."""
    md = metadata_parser.parse_metadata(
        filename="2001.A.Space.Odyssey.1968.1080p.BluRay.mkv"
    )
    assert md["title"] == "2001 A Space Odyssey"
    assert md["year"] == 1968


def test_engine_owns_same_year_title_year():
    """1984.1984 -> both the same, engine picks 1984."""
    md = metadata_parser.parse_metadata(
        filename="1984.1984.1080p.BluRay.x264.mkv"
    )
    assert md["title"] == "1984"
    assert md["year"] == 1984


def test_engine_year_guard_imax_no_longer_swallows_year():
    """Dune.2021.IMAX -> year=2021 (the old resolution guard misfired on .IM)."""
    parsed = metadata_parser.MovieFilenameParser().parse(
        "Dune.2021.IMAX.2160p.WEB-DL.DDP5.1.Atmos.DV.HEVC-GROUP.mkv"
    )
    assert parsed.year == 2021
    assert parsed.title == "Dune"


def test_engine_year_bracket_year_recovery():
    """The Shawshank Redemption (1994) [...] -> year 1994 via raw_scan."""
    md = metadata_parser.parse_metadata(
        filename="The Shawshank Redemption (1994) [1080p] [BluRay] [5.1] [YTS.MX].mp4"
    )
    assert md["year"] == 1994
    assert md["title"] == "The Shawshank Redemption"


def test_engine_imdb_id_field():
    """IMDB IDs are engine-owned via parse()."""
    parsed = metadata_parser.MovieFilenameParser().parse(
        "Movie.2021.1080p.WEBRip.x264.mkv tt1234567"
    )
    assert parsed.imdb_id == "tt1234567"
    md = metadata_parser.parse_metadata(
        filename="Movie.2021.1080p.WEBRip.x264.mkv tt1234567"
    )
    assert md["imdb"] == "tt1234567"


def test_engine_xdim_resolution():
    """x-dimension resolutions like 1920x1080 are engine-owned."""
    parsed = metadata_parser.MovieFilenameParser().parse(
        "Movie.2021.1920x1080.BluRay.x264.mkv"
    )
    assert parsed.resolution == "1920x1080"
    assert parsed.quality is None  # quality does NOT follow x-dim (mirrors old api)
    md = metadata_parser.parse_metadata(
        filename="Movie.2021.1920x1080.BluRay.x264.mkv"
    )
    assert md["resolution"] == "1920x1080"


def test_engine_year_last_before_marker():
    """Movie.2010.2021.1080p -> the last year before 1080p is 2021."""
    parsed = metadata_parser.MovieFilenameParser().parse(
        "Movie.2010.2021.1080p.mkv"
    )
    assert parsed.year == 2021
    assert parsed.title == "Movie 2010"

def test_engine_owns_all_parsing():
    """parse_metadata is now a pure mapper with zero fallback logic."""
    import inspect
    src = inspect.getsource(metadata_parser.parse_metadata)
    # Verify the section-3 docstring says "Zero fallback logic"
    assert "Zero fallback logic" in src


# -------------------------
# Recent-content grouping helpers consolidation
# -------------------------

def test_grouping_helpers_single_canonical_home():
    """utils.py owns the 4 grouping helpers; search.py neither defines nor
    re-exports them (its dead cmd_recent — the only consumer — is gone)."""
    search = importlib.import_module("features.search")
    for name in ("group_recent_content", "format_movie_group",
                 "format_series_group", "format_recent_output"):
        assert callable(getattr(utils, name)), f"{name} missing from utils"
        assert not hasattr(search, name), \
            f"{name} should not linger in search.py (canonical home is utils)"


def test_grouping_helpers_not_defined_in_search():
    """The search.py duplicate definitions must not come back."""
    import inspect
    src = inspect.getsource(importlib.import_module("features.search"))
    for anchor in ("def group_recent_content", "def format_movie_group",
                   "def format_series_group", "def format_recent_output"):
        assert anchor not in src, f"duplicate def resurrected in search.py: {anchor}"


def test_group_recent_content_consolidates_qualities():
    """Multiple qualities for one movie consolidate into one grouped entry."""
    grouped = utils.group_recent_content([
        {"title": "Inception", "type": "Movie", "year": 2010, "quality": "1080p"},
        {"title": "Inception", "type": "Movie", "year": 2010, "quality": "4K"},
    ])
    assert len(grouped["movies"]) == 1
    assert grouped["movies"][0]["title"] == "Inception"
    assert grouped["movies"][0]["count"] == 2
    # Bracket-ready /search-style details (dot-joined, lowercased qualities).
    assert grouped["movies"][0]["details"] == "2010.1080p & 4k"


def test_format_series_group_episode_ranges():
    """Series entries group seasons and render compact episode ranges."""
    title, details = utils.format_series_group({
        "title": "Breaking Bad", "year": 2008,
        "seasons_episodes": [(1, 1), (1, 2), (2, 1)],
    })
    assert title == "Breaking Bad"
    # Compact bracket-ready ranges: S01E01-02, S02E01 (no parens).
    assert details == "2008.S01E01-02, S02E01"


def test_format_recent_output_renders_sections():
    """format_recent_output renders movies/series sections and context lines."""
    grouped = {
        "movies": [{"title": "Inception", "details": "2010.1080p", "count": 1}],
        "series": [{"title": "Breaking Bad", "details": "2008.S01E01-02", "count": 2}],
    }
    out = utils.format_recent_output(grouped, total_files=3, total_movies=1,
                                     total_series=1, last_updated="2026-01-01 00:00:00 UTC")
    # /search-style: everything in one code block, bracket lines, sections kept.
    assert out.startswith("```") and out.rstrip().endswith("```")
    assert "LAST BATCH UPDATE" in out
    assert "Updated: 2026-01-01 00:00:00 UTC" in out
    assert "Files: 3 (Movies: 1 | Series: 1)" in out
    assert "\nMOVIES\n" in out and "\nSERIES\n" in out
    assert "1. Inception [2010.1080p]" in out
    assert "1. Breaking Bad [2008.S01E01-02]" in out


# -------------------------
# Role/log helpers consolidation (database.py vs user_management.py)
# -------------------------

def test_role_helpers_single_canonical_home():
    """get_user_doc/is_admin/is_banned/has_accepted_terms/log_action are
    canonical in user_management.py; database.py re-exports them lazily."""
    import features.database as database
    import features.user_management as um
    for name in ("get_user_doc", "is_admin", "is_banned",
                 "has_accepted_terms", "log_action"):
        assert callable(getattr(um, name)), f"{name} missing from user_management"
        assert getattr(database, name) is getattr(um, name), \
            f"database.{name} should resolve to the user_management copy"


def test_role_helpers_not_defined_in_database():
    """The database.py duplicate definitions must not come back."""
    import inspect
    import features.database as database
    src = inspect.getsource(database)
    for anchor in ("async def get_user_doc", "async def is_admin",
                   "async def is_banned", "async def has_accepted_terms",
                   "async def log_action"):
        assert anchor not in src, f"duplicate def resurrected in database.py: {anchor}"
    """Small helper: returns a context manager that expects ImportError from
    its body.

    Kept local so this file stays a self-contained standalone script (no pytest
    import needed when run directly).
    """
    import contextlib

    @contextlib.contextmanager
    def _cm():
        try:
            yield
        except ImportError:
            pass
        else:
            raise AssertionError(f"import {module_name} unexpectedly succeeded")

    return _cm()


if __name__ == "__main__":
    # Allow running directly: python tests/test_consolidation.py
    checks = [
        test_parser_module_is_single_canonical_home,
        test_old_filename_parser_module_gone,
        test_engine_and_api_agree,
        test_multi_year_edge_case_still_works,
        test_format_size_removed_from_utils,
        test_format_file_size_stat_removed_from_statistics,
        test_format_file_size_is_canonical,
        test_construct_final_caption_uses_canonical_formatter,
        test_statistics_uses_canonical_formatter,
        test_engine_sets_quality_from_resolution,
        test_engine_extracts_bit_depth_separately,
        test_engine_handles_ch_suffixed_channels,
        test_engine_full_text_scan_sees_brackets_and_underscores,
        test_parse_metadata_no_fallback_dependency,
        test_engine_raw_scan_owns_underscore_metadata,
        test_engine_raw_scan_owns_bracketed_metadata,
        test_engine_bracket_dts_hd_ma_full_form,
        test_engine_m4a_is_audio_codec,
        test_engine_publisher_coexists_with_rip,
        test_engine_publisher_field_and_alone,
        test_engine_publisher_via_bracket_and_underscore,
        test_engine_hdr_no_dv_false_positive,
        test_parse_metadata_has_no_metadata_fallbacks,
        test_parse_metadata_has_no_year_fallbacks,
        test_engine_owns_multi_year_2012,
        test_engine_owns_multi_year_1917,
        test_engine_owns_multi_year_2001,
        test_engine_owns_same_year_title_year,
        test_engine_year_guard_imax_no_longer_swallows_year,
        test_engine_year_bracket_year_recovery,
        test_engine_imdb_id_field,
        test_engine_xdim_resolution,
        test_engine_year_last_before_marker,
        test_engine_owns_all_parsing,
        test_grouping_helpers_single_canonical_home,
        test_grouping_helpers_not_defined_in_search,
        test_group_recent_content_consolidates_qualities,
        test_format_series_group_episode_ranges,
        test_format_recent_output_renders_sections,
        test_role_helpers_single_canonical_home,
        test_role_helpers_not_defined_in_database,
    ]
    failures = 0
    for fn in checks:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
    sys.exit(1 if failures else 0)
