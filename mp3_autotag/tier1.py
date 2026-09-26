"""Tier 1: AcoustID fingerprint matching and accept logic (spec §6)."""

from __future__ import annotations

from dataclasses import dataclass, field

from mp3_autotag.acoustid_client import AcoustidClient
from mp3_autotag.config import ThresholdsConfig


@dataclass
class Tier1Candidate:
    rank: int
    acoustid_id: str
    recording_mbid: str | None
    artist: str | None
    title: str
    album: str | None
    year: str | None
    duration_s: float | None
    score: float  # native AcoustID 0.0-1.0 scale
    source: str = "acoustid"
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class Tier1Result:
    candidates: list[Tier1Candidate]
    accepted: Tier1Candidate | None


def run_tier1(
    fingerprint: str,
    file_duration_s: float,
    acoustid_client: AcoustidClient,
    thresholds: ThresholdsConfig,
    top_n: int = 3,
) -> Tier1Result:
    raw_candidates = sorted(
        acoustid_client.lookup(fingerprint, file_duration_s),
        key=lambda c: c.score,
        reverse=True,
    )[:top_n]

    candidates = [
        Tier1Candidate(
            rank=i + 1,
            acoustid_id=c.acoustid_id,
            recording_mbid=c.recording_mbid,
            artist=c.artist,
            title=c.title,
            album=c.album,
            year=c.year,
            duration_s=c.duration_s,
            score=c.score,
            raw=c.raw,
        )
        for i, c in enumerate(raw_candidates)
    ]

    accepted = None
    if candidates:
        best = candidates[0]
        score_ok = best.score >= thresholds.tier1_min_score
        duration_ok = True
        if best.duration_s is not None:
            duration_ok = abs(best.duration_s - file_duration_s) <= thresholds.duration_tolerance_s
        if score_ok and duration_ok:
            accepted = best

    return Tier1Result(candidates=candidates, accepted=accepted)
