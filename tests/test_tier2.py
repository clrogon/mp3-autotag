from __future__ import annotations

from mp3_autotag.config import ThresholdsConfig
from mp3_autotag.filename_parser import ParsedFilename
from mp3_autotag.musicbrainz_client import MBCandidate
from mp3_autotag.tier2 import combined_score, run_tier2


class FakeMBClient:
    def __init__(self, candidates: list[MBCandidate]) -> None:
        self._candidates = candidates
        self.calls = []

    def search_recordings(self, artist, title, limit=10):
        self.calls.append((artist, title, limit))
        return self._candidates


def _cand(mbid, artist, title, duration_s=180.0):
    return MBCandidate(mbid=mbid, artist=artist, title=title, album="Album", year="2020", duration_s=duration_s)


def test_combined_score_is_mean_of_artist_and_title():
    cand = _cand("1", "Anselmo Ralph", "Kizua")
    score = combined_score("Anselmo Ralph", "Kizua", cand)
    assert score == 100.0


def test_exact_match_within_duration_is_accepted():
    thresholds = ThresholdsConfig()
    parsed = ParsedFilename(artist="Anselmo Ralph", title="Kizua", track=None)
    client = FakeMBClient([_cand("1", "Anselmo Ralph", "Kizua", duration_s=181.0)])

    result = run_tier2(parsed, file_duration_s=180.0, mb_client=client, thresholds=thresholds)

    assert result.accepted is not None
    assert result.accepted.mbid == "1"
    assert result.candidates[0].mbid == "1"


def test_low_score_is_not_accepted():
    thresholds = ThresholdsConfig()
    parsed = ParsedFilename(artist="Totally Different Artist", title="Totally Different Title", track=None)
    client = FakeMBClient([_cand("1", "Anselmo Ralph", "Kizua")])

    result = run_tier2(parsed, file_duration_s=180.0, mb_client=client, thresholds=thresholds)

    assert result.accepted is None
    assert len(result.candidates) == 1


def test_duration_outside_tolerance_is_not_accepted():
    thresholds = ThresholdsConfig()
    parsed = ParsedFilename(artist="Anselmo Ralph", title="Kizua", track=None)
    client = FakeMBClient([_cand("1", "Anselmo Ralph", "Kizua", duration_s=250.0)])  # way off

    result = run_tier2(parsed, file_duration_s=180.0, mb_client=client, thresholds=thresholds)

    assert result.accepted is None


def test_missing_candidate_duration_does_not_block_acceptance():
    thresholds = ThresholdsConfig()
    parsed = ParsedFilename(artist="Anselmo Ralph", title="Kizua", track=None)
    client = FakeMBClient([_cand("1", "Anselmo Ralph", "Kizua", duration_s=None)])

    result = run_tier2(parsed, file_duration_s=180.0, mb_client=client, thresholds=thresholds)

    assert result.accepted is not None


def test_insufficient_margin_over_second_best_is_not_accepted():
    thresholds = ThresholdsConfig()
    parsed = ParsedFilename(artist="Anselmo Ralph", title="Kizua", track=None)
    # Both candidates score very close to each other (margin < 5), even though
    # the top one clears tier2_min_score on its own.
    client = FakeMBClient(
        [
            _cand("1", "Anselmo Ralph", "Kizua", duration_s=180.0),
            _cand("2", "Anselmo Ralph", "Kizuaa", duration_s=180.0),
        ]
    )

    result = run_tier2(parsed, file_duration_s=180.0, mb_client=client, thresholds=thresholds)

    assert result.accepted is None
    assert len(result.candidates) == 2


def test_no_candidates_returns_empty_result():
    thresholds = ThresholdsConfig()
    parsed = ParsedFilename(artist="Anselmo Ralph", title="Kizua", track=None)
    client = FakeMBClient([])

    result = run_tier2(parsed, file_duration_s=180.0, mb_client=client, thresholds=thresholds)

    assert result.accepted is None
    assert result.candidates == []


def test_top_n_limits_stored_candidates():
    thresholds = ThresholdsConfig()
    parsed = ParsedFilename(artist="Anselmo Ralph", title="Kizua", track=None)
    client = FakeMBClient(
        [_cand(str(i), "Anselmo Ralph", "Kizua", duration_s=180.0) for i in range(5)]
    )

    result = run_tier2(parsed, file_duration_s=180.0, mb_client=client, thresholds=thresholds, top_n=3)

    assert len(result.candidates) == 3
