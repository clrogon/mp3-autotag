"""Ties Tier 0-2 together (spec §6): stop at the first tier that accepts,
apply the conflict rule, store every candidate seen along the way.

Tier 3 (commercial recognition) is optional and off by default (Phase 7,
not yet implemented) — if `3` ends up in `enabled_tiers` it is silently
ignored for now rather than erroring, since spec's own default
`tiers.enabled = [0, 1, 2]` doesn't include it.

Statuses: SKIPPED_COMPLETE, MATCHED_TIER1, MATCHED_TIER2, REVIEW_CONFLICT,
REVIEW_UNMATCHED, FAILED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

from mp3_autotag.acoustid_client import AcoustidClient, AcoustidError
from mp3_autotag.config import Config
from mp3_autotag.filename_parser import ParsedFilename, parse_filename
from mp3_autotag.fingerprint import FingerprintError, get_or_compute_fingerprint
from mp3_autotag.musicbrainz_client import MusicBrainzClient, MusicBrainzError
from mp3_autotag.tags import ExistingTags
from mp3_autotag.tier0 import check_tier0
from mp3_autotag.tier1 import Tier1Candidate, run_tier1
from mp3_autotag.tier2 import Tier2Candidate, run_tier2


@dataclass
class StoredCandidate:
    tier: int
    rank: int
    artist: str | None
    title: str
    album: str | None
    year: str | None
    source: str
    score: float
    mbid: str | None
    acoustid_id: str | None
    duration_s: float | None
    accepted: bool
    raw: dict = field(default_factory=dict)


@dataclass
class IdentifyOutcome:
    status: str
    accepted_tier: int | None
    accepted: Tier1Candidate | Tier2Candidate | None
    stored: list[StoredCandidate]
    error: str | None = None


def _tier1_to_stored(candidates: list[Tier1Candidate], accepted: Tier1Candidate | None) -> list[StoredCandidate]:
    return [
        StoredCandidate(
            tier=1,
            rank=c.rank,
            artist=c.artist,
            title=c.title,
            album=c.album,
            year=c.year,
            source=c.source,
            score=c.score,
            mbid=c.recording_mbid,
            acoustid_id=c.acoustid_id,
            duration_s=c.duration_s,
            accepted=(c is accepted),
            raw=c.raw,
        )
        for c in candidates
    ]


def _tier2_to_stored(
    candidates: list[Tier2Candidate], accepted: Tier2Candidate | None, force_reject: bool = False
) -> list[StoredCandidate]:
    return [
        StoredCandidate(
            tier=2,
            rank=c.rank,
            artist=c.artist,
            title=c.title,
            album=c.album,
            year=c.year,
            source=c.source,
            score=c.score,
            mbid=c.mbid,
            acoustid_id=None,
            duration_s=c.duration_s,
            accepted=(not force_reject and c is accepted),
            raw=c.raw,
        )
        for c in candidates
    ]


def identify_file(
    file_path: Path,
    existing: ExistingTags,
    file_duration_s: float | None,
    file_hash: str,
    config: Config,
    conn,
    enabled_tiers: set[int],
    mb_client: MusicBrainzClient | None,
    acoustid_client: AcoustidClient | None,
    fpcalc_path: str | None,
) -> IdentifyOutcome:
    parsed: ParsedFilename = parse_filename(file_path, config.filename.noise_patterns)
    stored: list[StoredCandidate] = []

    if 0 in enabled_tiers:
        tier0 = check_tier0(existing, parsed)
        if tier0.skip:
            return IdentifyOutcome(status="SKIPPED_COMPLETE", accepted_tier=None, accepted=None, stored=[])

    tier1_result = None
    if 1 in enabled_tiers and acoustid_client is not None and fpcalc_path is not None:
        try:
            fp = get_or_compute_fingerprint(conn, file_hash, str(file_path), fpcalc_path)
        except FingerprintError as exc:
            return IdentifyOutcome(status="FAILED", accepted_tier=None, accepted=None, stored=[], error=str(exc))

        if fp is not None:
            try:
                tier1_result = run_tier1(fp.fingerprint, fp.duration_s, acoustid_client, config.thresholds)
            except AcoustidError as exc:
                return IdentifyOutcome(status="FAILED", accepted_tier=None, accepted=None, stored=[], error=str(exc))
            stored += _tier1_to_stored(tier1_result.candidates, tier1_result.accepted)

    if tier1_result is not None and tier1_result.accepted is not None:
        artist_similarity = fuzz.token_set_ratio(tier1_result.accepted.artist or "", parsed.artist or "")
        if artist_similarity < config.thresholds.conflict_artist_similarity:
            # Conflict: fingerprint and filename disagree strongly on artist.
            # Un-accept the Tier 1 match, pull in a Tier 2 candidate for
            # comparison if possible, and force this file to manual review.
            for c in stored:
                c.accepted = False
            if 2 in enabled_tiers and mb_client is not None:
                tier2_result = run_tier2(parsed, file_duration_s, mb_client, config.thresholds)
                stored += _tier2_to_stored(tier2_result.candidates, tier2_result.accepted, force_reject=True)
            return IdentifyOutcome(status="REVIEW_CONFLICT", accepted_tier=None, accepted=None, stored=stored)

        return IdentifyOutcome(
            status="MATCHED_TIER1", accepted_tier=1, accepted=tier1_result.accepted, stored=stored
        )

    if 2 in enabled_tiers and mb_client is not None:
        try:
            tier2_result = run_tier2(parsed, file_duration_s, mb_client, config.thresholds)
        except MusicBrainzError as exc:
            return IdentifyOutcome(status="FAILED", accepted_tier=None, accepted=None, stored=stored, error=str(exc))
        stored += _tier2_to_stored(tier2_result.candidates, tier2_result.accepted)
        if tier2_result.accepted is not None:
            return IdentifyOutcome(
                status="MATCHED_TIER2", accepted_tier=2, accepted=tier2_result.accepted, stored=stored
            )

    return IdentifyOutcome(status="REVIEW_UNMATCHED", accepted_tier=None, accepted=None, stored=stored)
