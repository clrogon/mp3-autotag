"""Tier 0: skip check (spec §6).

The 90-point fuzzy threshold is hardcoded per spec text ("fuzzy-match the
parsed filename at >= 90") — unlike Tier 1/2's thresholds, spec §9's config
schema has no `tier0_*` key for it, so it isn't pulled from ThresholdsConfig.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from mp3_autotag.filename_parser import ParsedFilename
from mp3_autotag.tags import ExistingTags

DEFAULT_FUZZY_THRESHOLD = 90.0


@dataclass
class Tier0Result:
    skip: bool
    reason: str | None


def check_tier0(
    existing: ExistingTags,
    parsed: ParsedFilename,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> Tier0Result:
    if not existing.is_minimally_complete():
        return Tier0Result(skip=False, reason=None)

    if existing.musicbrainz_track_id:
        return Tier0Result(skip=True, reason="has_musicbrainz_id")

    artist_score = fuzz.token_set_ratio(existing.artist or "", parsed.artist or "")
    title_score = fuzz.token_set_ratio(existing.title or "", parsed.title or "")
    combined = (artist_score + title_score) / 2
    if combined >= fuzzy_threshold:
        return Tier0Result(skip=True, reason="fuzzy_match_filename")

    return Tier0Result(skip=False, reason=None)
