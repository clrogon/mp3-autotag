from __future__ import annotations

import musicbrainzngs
import pytest

from mp3_autotag.musicbrainz_client import MusicBrainzClient, MusicBrainzError
from mp3_autotag.rate_limit import RateLimiter


def _recording(mbid="rec-1", title="Kizua", artist_name="Anselmo Ralph", length_ms=180000, releases=None):
    return {
        "id": mbid,
        "title": title,
        "length": str(length_ms) if length_ms is not None else None,
        "artist-credit": [{"artist": {"id": "art-1", "name": artist_name}}],
        "release-list": releases or [],
    }


@pytest.fixture
def no_sleep_limiter():
    return RateLimiter(0.0, clock=lambda: 0.0, sleep=lambda d: None)


def test_search_recordings_normalizes_fields(memory_conn, monkeypatch, no_sleep_limiter):
    recording = _recording(
        releases=[
            {"title": "Álbum Um", "date": "2019-01-01", "release-group": {"primary-type": "Album"}},
        ]
    )

    def fake_search(**kwargs):
        return {"recording-list": [recording]}

    monkeypatch.setattr(musicbrainzngs, "search_recordings", fake_search)

    client = MusicBrainzClient(memory_conn, no_sleep_limiter)
    results = client.search_recordings("Anselmo Ralph", "Kizua")

    assert len(results) == 1
    cand = results[0]
    assert cand.mbid == "rec-1"
    assert cand.artist == "Anselmo Ralph"
    assert cand.title == "Kizua"
    assert cand.album == "Álbum Um"
    assert cand.year == "2019"
    assert cand.duration_s == 180.0


def test_search_recordings_caches_and_skips_second_network_call(memory_conn, monkeypatch, no_sleep_limiter):
    calls = []

    def fake_search(**kwargs):
        calls.append(kwargs)
        return {"recording-list": [_recording()]}

    monkeypatch.setattr(musicbrainzngs, "search_recordings", fake_search)

    client = MusicBrainzClient(memory_conn, no_sleep_limiter)
    client.search_recordings("Anselmo Ralph", "Kizua")
    client.search_recordings("Anselmo Ralph", "Kizua")

    assert len(calls) == 1


def test_prefers_official_album_over_compilation(memory_conn, monkeypatch, no_sleep_limiter):
    recording = _recording(
        releases=[
            {
                "title": "Greatest Hits",
                "date": "2010-01-01",
                "release-group": {"primary-type": "Compilation"},
            },
            {"title": "Studio Album", "date": "2015-01-01", "release-group": {"primary-type": "Album"}},
        ]
    )
    monkeypatch.setattr(musicbrainzngs, "search_recordings", lambda **kw: {"recording-list": [recording]})

    client = MusicBrainzClient(memory_conn, no_sleep_limiter)
    cand = client.search_recordings("Anselmo Ralph", "Kizua")[0]

    assert cand.album == "Studio Album"
    assert cand.year == "2015"


def test_retries_on_503_then_succeeds(memory_conn, monkeypatch, no_sleep_limiter):
    attempts = {"n": 0}
    sleeps = []

    class FakeCause:
        code = 503

    def fake_search(**kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise musicbrainzngs.WebServiceError("service unavailable", cause=FakeCause())
        return {"recording-list": [_recording()]}

    monkeypatch.setattr(musicbrainzngs, "search_recordings", fake_search)

    client = MusicBrainzClient(memory_conn, no_sleep_limiter, sleep=sleeps.append)
    results = client.search_recordings("Anselmo Ralph", "Kizua")

    assert attempts["n"] == 3
    assert len(results) == 1
    assert sleeps == [1, 2]  # exponential backoff: 2**0, 2**1


def test_gives_up_after_max_retries(memory_conn, monkeypatch, no_sleep_limiter):
    class FakeCause:
        code = 429

    def fake_search(**kwargs):
        raise musicbrainzngs.WebServiceError("rate limited", cause=FakeCause())

    monkeypatch.setattr(musicbrainzngs, "search_recordings", fake_search)

    client = MusicBrainzClient(memory_conn, no_sleep_limiter, max_retries=2, sleep=lambda d: None)

    with pytest.raises(MusicBrainzError):
        client.search_recordings("Anselmo Ralph", "Kizua")


def test_non_retryable_error_raises_immediately(memory_conn, monkeypatch, no_sleep_limiter):
    calls = {"n": 0}

    class FakeCause:
        code = 400

    def fake_search(**kwargs):
        calls["n"] += 1
        raise musicbrainzngs.WebServiceError("bad request", cause=FakeCause())

    monkeypatch.setattr(musicbrainzngs, "search_recordings", fake_search)

    client = MusicBrainzClient(memory_conn, no_sleep_limiter, sleep=lambda d: None)

    with pytest.raises(MusicBrainzError):
        client.search_recordings("Anselmo Ralph", "Kizua")

    assert calls["n"] == 1
