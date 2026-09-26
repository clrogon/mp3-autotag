from __future__ import annotations

from mp3_autotag.filename_parser import ParsedFilename
from mp3_autotag.tags import ExistingTags
from mp3_autotag.tier0 import check_tier0


def test_incomplete_tags_never_skipped():
    existing = ExistingTags(title="T", artist="A", album=None)
    parsed = ParsedFilename(artist="A", title="T", track=None)
    result = check_tier0(existing, parsed)
    assert result.skip is False
    assert result.reason is None


def test_complete_tags_with_musicbrainz_id_skipped():
    existing = ExistingTags(
        title="Kizua", artist="Anselmo Ralph", album="Album",
        musicbrainz_track_id="11111111-1111-1111-1111-111111111111",
    )
    parsed = ParsedFilename(artist="Totally Different", title="Nope", track=None)
    result = check_tier0(existing, parsed)
    assert result.skip is True
    assert result.reason == "has_musicbrainz_id"


def test_complete_tags_matching_filename_skipped():
    existing = ExistingTags(title="Kizua", artist="Anselmo Ralph", album="Album")
    parsed = ParsedFilename(artist="Anselmo Ralph", title="Kizua", track=None)
    result = check_tier0(existing, parsed)
    assert result.skip is True
    assert result.reason == "fuzzy_match_filename"


def test_complete_tags_not_matching_filename_not_skipped():
    existing = ExistingTags(title="Kizua", artist="Anselmo Ralph", album="Album")
    parsed = ParsedFilename(artist="Someone Else", title="Different Song", track=None)
    result = check_tier0(existing, parsed)
    assert result.skip is False


def test_force_disables_tier0_is_caller_responsibility():
    # check_tier0 itself has no --force concept; the pipeline is responsible
    # for simply not calling it when tier 0 is disabled. Documented via the
    # pipeline tests (test_pipeline.py) rather than here.
    existing = ExistingTags(
        title="Kizua", artist="Anselmo Ralph", album="Album",
        musicbrainz_track_id="11111111-1111-1111-1111-111111111111",
    )
    parsed = ParsedFilename(artist="Anselmo Ralph", title="Kizua", track=None)
    assert check_tier0(existing, parsed).skip is True
