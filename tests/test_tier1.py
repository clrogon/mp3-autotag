from __future__ import annotations

from mp3_autotag.acoustid_client import AcoustidCandidate
from mp3_autotag.config import ThresholdsConfig
from mp3_autotag.tier1 import run_tier1


class FakeAcoustidClient:
    def __init__(self, candidates):
        self._candidates = candidates
        self.calls = []

    def lookup(self, fingerprint, duration_s):
        self.calls.append((fingerprint, duration_s))
        return self._candidates


def _cand(acoustid_id, score, duration_s=181.0, mbid="mbid-1"):
    return AcoustidCandidate(
        acoustid_id=acoustid_id,
        recording_mbid=mbid,
        artist="Anselmo Ralph",
        title="Kizua",
        album="Studio Album",
        year=None,
        duration_s=duration_s,
        score=score,
    )


def test_high_score_within_duration_is_accepted():
    thresholds = ThresholdsConfig()
    client = FakeAcoustidClient([_cand("a1", 0.95, duration_s=181.0)])

    result = run_tier1("AQfp", 180.0, client, thresholds)

    assert result.accepted is not None
    assert result.accepted.acoustid_id == "a1"


def test_score_below_threshold_is_not_accepted():
    thresholds = ThresholdsConfig()
    client = FakeAcoustidClient([_cand("a1", 0.5, duration_s=181.0)])

    result = run_tier1("AQfp", 180.0, client, thresholds)

    assert result.accepted is None
    assert len(result.candidates) == 1


def test_duration_outside_tolerance_is_not_accepted():
    thresholds = ThresholdsConfig()
    client = FakeAcoustidClient([_cand("a1", 0.95, duration_s=220.0)])  # way off from 180

    result = run_tier1("AQfp", 180.0, client, thresholds)

    assert result.accepted is None


def test_missing_candidate_duration_does_not_block_acceptance():
    thresholds = ThresholdsConfig()
    client = FakeAcoustidClient([_cand("a1", 0.95, duration_s=None)])

    result = run_tier1("AQfp", 180.0, client, thresholds)

    assert result.accepted is not None


def test_no_margin_check_for_tier1_two_high_scores_both_accepted_candidate():
    # Unlike Tier 2, spec §6 Tier 1 has no "lead over second best" rule.
    thresholds = ThresholdsConfig()
    client = FakeAcoustidClient(
        [_cand("a1", 0.95, duration_s=181.0), _cand("a2", 0.94, duration_s=181.0)]
    )

    result = run_tier1("AQfp", 180.0, client, thresholds)

    assert result.accepted is not None
    assert result.accepted.acoustid_id == "a1"
    assert len(result.candidates) == 2


def test_no_candidates_returns_empty_result():
    thresholds = ThresholdsConfig()
    client = FakeAcoustidClient([])

    result = run_tier1("AQfp", 180.0, client, thresholds)

    assert result.accepted is None
    assert result.candidates == []


def test_top_n_limits_stored_candidates():
    thresholds = ThresholdsConfig()
    client = FakeAcoustidClient([_cand(f"a{i}", 0.9 - i * 0.01) for i in range(5)])

    result = run_tier1("AQfp", 180.0, client, thresholds, top_n=3)

    assert len(result.candidates) == 3

    result_low = run_tier1("AQfp", 180.0, client, thresholds, top_n=3)
    assert result_low is not None  # sanity: repeated calls fine, client is a stub
