from __future__ import annotations

import pytest

from mp3_autotag.acoustid_client import AcoustidClient, AcoustidError, parse_lookup_response
from mp3_autotag.rate_limit import RateLimiter


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


class FakeHttpClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, data):
        self.calls.append((url, data))
        return self._responses.pop(0)


def _ok_payload(recordings=None):
    return {
        "status": "ok",
        "results": [
            {
                "id": "acoustid-1",
                "score": 0.95,
                "recordings": recordings
                if recordings is not None
                else [
                    {
                        "id": "mbid-1",
                        "title": "Kizua",
                        "duration": 181,
                        "artists": [{"id": "a1", "name": "Anselmo Ralph"}],
                        "releasegroups": [
                            {"id": "rg1", "type": "Compilation", "title": "Hits"},
                            {"id": "rg2", "type": "Album", "title": "Studio Album"},
                        ],
                    }
                ],
            }
        ],
    }


@pytest.fixture
def no_sleep_limiter():
    return RateLimiter(0.0, clock=lambda: 0.0, sleep=lambda d: None)


def test_parse_lookup_response_normalizes_and_prefers_official_album():
    candidates = parse_lookup_response(_ok_payload())
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.acoustid_id == "acoustid-1"
    assert cand.recording_mbid == "mbid-1"
    assert cand.artist == "Anselmo Ralph"
    assert cand.title == "Kizua"
    assert cand.album == "Studio Album"
    assert cand.year is None
    assert cand.duration_s == 181
    assert cand.score == 0.95


def test_parse_lookup_response_raises_on_non_ok_status():
    with pytest.raises(AcoustidError):
        parse_lookup_response({"status": "error"})


def test_parse_lookup_response_handles_joinphrase():
    payload = _ok_payload(
        recordings=[
            {
                "id": "mbid-2",
                "title": "Duet",
                "duration": 200,
                "artists": [
                    {"id": "a1", "name": "Artist One", "joinphrase": " feat. "},
                    {"id": "a2", "name": "Artist Two"},
                ],
                "releasegroups": [],
            }
        ]
    )
    candidates = parse_lookup_response(payload)
    assert candidates[0].artist == "Artist One feat. Artist Two"
    assert candidates[0].album is None


def test_lookup_caches_and_skips_second_network_call(memory_conn, no_sleep_limiter):
    http = FakeHttpClient([FakeResponse(200, _ok_payload())])
    client = AcoustidClient(memory_conn, no_sleep_limiter, api_key="key123", http_client=http)

    client.lookup("AQfakefingerprint", 181.0)
    client.lookup("AQfakefingerprint", 181.0)

    assert len(http.calls) == 1


def test_lookup_sends_documented_params(memory_conn, no_sleep_limiter):
    http = FakeHttpClient([FakeResponse(200, _ok_payload())])
    client = AcoustidClient(memory_conn, no_sleep_limiter, api_key="key123", http_client=http)

    client.lookup("AQfakefingerprint", 181.0)

    url, data = http.calls[0]
    assert url == "https://api.acoustid.org/v2/lookup"
    assert data["client"] == "key123"
    assert data["fingerprint"] == "AQfakefingerprint"
    assert data["duration"] == 181
    assert data["format"] == "json"
    assert "recordings" in data["meta"]


def test_retries_on_503_then_succeeds(memory_conn):
    sleeps = []
    http = FakeHttpClient(
        [
            FakeResponse(503, text="service unavailable"),
            FakeResponse(429, text="rate limited"),
            FakeResponse(200, _ok_payload()),
        ]
    )
    limiter = RateLimiter(0.0, clock=lambda: 0.0, sleep=lambda d: None)
    client = AcoustidClient(memory_conn, limiter, api_key="key123", http_client=http, sleep=sleeps.append)

    candidates = client.lookup("AQfakefingerprint", 181.0)

    assert len(http.calls) == 3
    assert sleeps == [1, 2]
    assert len(candidates) == 1


def test_gives_up_after_max_retries(memory_conn, no_sleep_limiter):
    http = FakeHttpClient([FakeResponse(503, text="down")] * 10)
    client = AcoustidClient(
        memory_conn, no_sleep_limiter, api_key="key123", http_client=http,
        max_retries=2, sleep=lambda d: None,
    )

    with pytest.raises(AcoustidError):
        client.lookup("AQfakefingerprint", 181.0)

    assert len(http.calls) == 3  # initial + 2 retries


def test_non_retryable_error_raises_immediately(memory_conn, no_sleep_limiter):
    http = FakeHttpClient([FakeResponse(401, text="bad api key")])
    client = AcoustidClient(memory_conn, no_sleep_limiter, api_key="bad", http_client=http, sleep=lambda d: None)

    with pytest.raises(AcoustidError):
        client.lookup("AQfakefingerprint", 181.0)

    assert len(http.calls) == 1
