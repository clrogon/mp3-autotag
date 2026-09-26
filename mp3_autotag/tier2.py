"""Tier 2: filename-search matching and accept logic (spec §6).

"Combined score" is not defined precisely in the spec beyond "score each
candidate with rapidfuzz (token_set_ratio) on both artist and title" and
comparing a single number against `tier2_min_score`. Both inputs are 0-100
token_set_ratio scores and the threshold (88) is on the same scale, so the
combined score here is their arithmetic mean — the natural reading, and the
only simple combination that stays in 0-100 range.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from mp3_autotag.config import ThresholdsConfig
from mp3_autotag.filename_parser import ParsedFilename
from mp3_autotag.musicbrainz_client import MBCandidate, MusicBrainzClient


@dataclass
class Tier2Candidate:
    rank: int
    mbid: str
    artist: str | None
    title: str
    album: str | None
    year: str | None
    duration_s: float | None
    score: float
    source: str = "musicbrainz"
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class Tier2Result:
    candidates: list[Tier2Candidate]
    accepted: Tier2Candidate | None


def combined_score(parsed_artist: str | None, parsed_title: str, candidate: MBCandidate) -> float:
    artist_score = fuzz.token_set_ratio(parsed_artist or "", candidate.artist or "")
    title_score = fuzz.token_set_ratio(parsed_title, candidate.title or "")
    return (artist_score + title_score) / 2


def run_tier2(
    parsed: ParsedFilename,
    file_duration_s: float | None,
    mb_client: MusicBrainzClient,
    thresholds: ThresholdsConfig,
    search_limit: int = 10,
    top_n: int = 3,
) -> Tier2Result:
    raw_candidates = mb_client.search_recordings(parsed.artist, parsed.title, limit=search_limit)

    scored = sorted(
        raw_candidates,
        key=lambda c: combined_score(parsed.artist, parsed.title, c),
        reverse=True,
    )[:top_n]

    candidates = [
        Tier2Candidate(
            rank=i + 1,
            mbid=c.mbid,
            artist=c.artist,
            title=c.title,
            album=c.album,
            year=c.year,
            duration_s=c.duration_s,
            score=combined_score(parsed.artist, parsed.title, c),
            raw=c.raw,
        )
        for i, c in enumerate(scored)
    ]

    accepted = None
    if candidates:
        best = candidates[0]
        second_score = candidates[1].score if len(candidates) > 1 else -math.inf

        duration_ok = True
        if file_duration_s is not None and best.duration_s is not None:
            duration_ok = abs(best.duration_s - file_duration_s) <= thresholds.duration_tolerance_s

        margin_ok = (best.score - second_score) >= thresholds.tier2_min_margin
        score_ok = best.score >= thresholds.tier2_min_score

        if score_ok and duration_ok and margin_ok:
            accepted = best

    return Tier2Result(candidates=candidates, accepted=accepted)
