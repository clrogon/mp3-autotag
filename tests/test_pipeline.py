from __future__ import annotations

from pathlib import Path

import pytest

from mp3_autotag.acoustid_client import AcoustidCandidate, AcoustidError
from mp3_autotag.config import Config
from mp3_autotag.fingerprint import Fingerprint
from mp3_autotag.musicbrainz_client import MBCandidate, MusicBrainzError
from mp3_autotag.tags import ExistingTags
import mp3_autotag.pipeline as pipeline_mod
from mp3_autotag.pipeline import identify_file


class FakeAcoustidClient:
    def __init__(self, candidates=None, raise_error=None):
        self._candidates = candidates or []
        self._raise_error = raise_error
        self.calls = 0

    def lookup(self, fingerprint, duration_s):
        self.calls += 1
        if self._raise_error:
            raise self._raise_error
        return self._candidates


class FakeMBClient:
    def __init__(self, candidates=None, raise_error=None):
        self._candidates = candidates or []
        self._raise_error = raise_error
        self.calls = 0

    def search_recordings(self, artist, title, limit=10):
        self.calls += 1
        if self._raise_error:
            raise self._raise_error
        return self._candidates


def _acoustid_cand(score=0.95, artist="Anselmo Ralph", title="Kizua", duration_s=180.0, mbid="mb-1"):
    return AcoustidCandidate(
        acoustid_id="ac-1", recording_mbid=mbid, artist=artist, title=title,
        album="Album", year=None, duration_s=duration_s, score=score,
    )


def _mb_cand(score_artist="Anselmo Ralph", title="Kizua", duration_s=180.0, mbid="mb-2"):
    return MBCandidate(
        mbid=mbid, artist=score_artist, title=title, album="Album", year="2020", duration_s=duration_s,
    )


@pytest.fixture
def default_config():
    return Config()


@pytest.fixture
def incomplete_tags():
    return ExistingTags(title=None, artist=None, album=None)


def test_tier0_skips_before_any_network_call(default_config, tmp_path, monkeypatch):
    file_path = tmp_path / "Music" / "Anselmo Ralph - Kizua.mp3"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    existing = ExistingTags(
        title="Kizua", artist="Anselmo Ralph", album="Album",
        musicbrainz_track_id="11111111-1111-1111-1111-111111111111",
    )
    acoustid = FakeAcoustidClient()
    mb = FakeMBClient()

    outcome = identify_file(
        file_path, existing, 180.0, "hash1", default_config, conn=None,
        enabled_tiers={0, 1, 2}, mb_client=mb, acoustid_client=acoustid, fpcalc_path="/usr/bin/fpcalc",
    )

    assert outcome.status == "SKIPPED_COMPLETE"
    assert outcome.stored == []
    assert acoustid.calls == 0
    assert mb.calls == 0


def test_tier0_disabled_falls_through_to_tier1(default_config, tmp_path, monkeypatch):
    file_path = tmp_path / "Music" / "Anselmo Ralph - Kizua.mp3"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    existing = ExistingTags(
        title="Kizua", artist="Anselmo Ralph", album="Album",
        musicbrainz_track_id="11111111-1111-1111-1111-111111111111",
    )
    monkeypatch.setattr(
        pipeline_mod, "get_or_compute_fingerprint", lambda *a, **k: Fingerprint(180.0, "AQfake")
    )
    acoustid = FakeAcoustidClient([_acoustid_cand()])

    outcome = identify_file(
        file_path, existing, 180.0, "hash1", default_config, conn=None,
        enabled_tiers={1, 2}, mb_client=FakeMBClient(), acoustid_client=acoustid, fpcalc_path="/usr/bin/fpcalc",
    )

    assert outcome.status == "MATCHED_TIER1"
    assert acoustid.calls == 1


def test_tier1_match_with_agreeing_artist_accepted(default_config, tmp_path, monkeypatch, incomplete_tags):
    file_path = tmp_path / "Music" / "Anselmo Ralph - Kizua.mp3"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    monkeypatch.setattr(
        pipeline_mod, "get_or_compute_fingerprint", lambda *a, **k: Fingerprint(180.0, "AQfake")
    )
    acoustid = FakeAcoustidClient([_acoustid_cand(artist="Anselmo Ralph", title="Kizua")])
    mb = FakeMBClient()

    outcome = identify_file(
        file_path, incomplete_tags, 180.0, "hash1", default_config, conn=None,
        enabled_tiers={0, 1, 2}, mb_client=mb, acoustid_client=acoustid, fpcalc_path="/usr/bin/fpcalc",
    )

    assert outcome.status == "MATCHED_TIER1"
    assert outcome.accepted_tier == 1
    assert outcome.accepted.title == "Kizua"
    assert mb.calls == 0  # Tier 1 accepted, no need to touch Tier 2
    assert any(c.tier == 1 and c.accepted for c in outcome.stored)


def test_conflict_rule_routes_to_review_and_pulls_tier2(default_config, tmp_path, monkeypatch, incomplete_tags):
    # Filename says one artist, fingerprint match says a completely different one.
    file_path = tmp_path / "Music" / "Some Random Artist - Some Random Song.mp3"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    monkeypatch.setattr(
        pipeline_mod, "get_or_compute_fingerprint", lambda *a, **k: Fingerprint(180.0, "AQfake")
    )
    acoustid = FakeAcoustidClient([_acoustid_cand(artist="Anselmo Ralph", title="Kizua")])
    mb = FakeMBClient([_mb_cand()])

    outcome = identify_file(
        file_path, incomplete_tags, 180.0, "hash1", default_config, conn=None,
        enabled_tiers={0, 1, 2}, mb_client=mb, acoustid_client=acoustid, fpcalc_path="/usr/bin/fpcalc",
    )

    assert outcome.status == "REVIEW_CONFLICT"
    assert outcome.accepted is None
    assert mb.calls == 1  # conflict pulls in a Tier 2 candidate for comparison
    assert all(not c.accepted for c in outcome.stored)  # never auto-accept in conflict
    tiers_present = {c.tier for c in outcome.stored}
    assert tiers_present == {1, 2}


def test_tier1_low_score_falls_through_to_tier2(default_config, tmp_path, monkeypatch, incomplete_tags):
    file_path = tmp_path / "Music" / "Anselmo Ralph - Kizua.mp3"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    monkeypatch.setattr(
        pipeline_mod, "get_or_compute_fingerprint", lambda *a, **k: Fingerprint(180.0, "AQfake")
    )
    acoustid = FakeAcoustidClient([_acoustid_cand(score=0.1)])  # too low to accept
    mb = FakeMBClient([_mb_cand(score_artist="Anselmo Ralph", title="Kizua")])

    outcome = identify_file(
        file_path, incomplete_tags, 180.0, "hash1", default_config, conn=None,
        enabled_tiers={0, 1, 2}, mb_client=mb, acoustid_client=acoustid, fpcalc_path="/usr/bin/fpcalc",
    )

    assert outcome.status == "MATCHED_TIER2"
    assert outcome.accepted_tier == 2
    assert mb.calls == 1
    tiers_present = {c.tier for c in outcome.stored}
    assert 1 in tiers_present and 2 in tiers_present


def test_no_tier_accepts_goes_to_review_unmatched(default_config, tmp_path, monkeypatch, incomplete_tags):
    file_path = tmp_path / "Music" / "Unknown - Mystery.mp3"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    monkeypatch.setattr(
        pipeline_mod, "get_or_compute_fingerprint", lambda *a, **k: Fingerprint(180.0, "AQfake")
    )
    acoustid = FakeAcoustidClient([_acoustid_cand(score=0.1)])
    mb = FakeMBClient([_mb_cand(score_artist="Nope", title="Not It")])

    outcome = identify_file(
        file_path, incomplete_tags, 180.0, "hash1", default_config, conn=None,
        enabled_tiers={0, 1, 2}, mb_client=mb, acoustid_client=acoustid, fpcalc_path="/usr/bin/fpcalc",
    )

    assert outcome.status == "REVIEW_UNMATCHED"
    assert outcome.accepted is None


def test_acoustid_error_marks_failed(default_config, tmp_path, monkeypatch, incomplete_tags):
    file_path = tmp_path / "Music" / "Anselmo Ralph - Kizua.mp3"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    monkeypatch.setattr(
        pipeline_mod, "get_or_compute_fingerprint", lambda *a, **k: Fingerprint(180.0, "AQfake")
    )
    acoustid = FakeAcoustidClient(raise_error=AcoustidError("boom"))

    outcome = identify_file(
        file_path, incomplete_tags, 180.0, "hash1", default_config, conn=None,
        enabled_tiers={0, 1, 2}, mb_client=FakeMBClient(), acoustid_client=acoustid, fpcalc_path="/usr/bin/fpcalc",
    )

    assert outcome.status == "FAILED"
    assert "boom" in outcome.error


def test_musicbrainz_error_marks_failed(default_config, tmp_path, monkeypatch, incomplete_tags):
    file_path = tmp_path / "Music" / "Unknown - Mystery.mp3"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    outcome = identify_file(
        file_path, incomplete_tags, 180.0, "hash1", default_config, conn=None,
        enabled_tiers={2}, mb_client=FakeMBClient(raise_error=MusicBrainzError("down")),
        acoustid_client=None, fpcalc_path=None,
    )

    assert outcome.status == "FAILED"
    assert "down" in outcome.error


def test_no_fpcalc_path_skips_tier1_entirely(default_config, tmp_path, incomplete_tags):
    file_path = tmp_path / "Music" / "Anselmo Ralph - Kizua.mp3"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    mb = FakeMBClient([_mb_cand(score_artist="Anselmo Ralph", title="Kizua")])

    outcome = identify_file(
        file_path, incomplete_tags, 180.0, "hash1", default_config, conn=None,
        enabled_tiers={0, 1, 2}, mb_client=mb, acoustid_client=FakeAcoustidClient(), fpcalc_path=None,
    )

    assert outcome.status == "MATCHED_TIER2"
    assert all(c.tier != 1 for c in outcome.stored)
