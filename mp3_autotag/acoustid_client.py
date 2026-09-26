"""AcoustID lookup for Tier 1 (spec §6, §7.7).

Calls the documented `/v2/lookup` endpoint directly via httpx rather than
`pyacoustid.lookup()`: pyacoustid wraps every HTTP failure into a bare
`WebServiceError` message string with no preserved status code, which makes
spec §7.7's mandatory "retry with exponential backoff on 503 and 429"
impossible to implement reliably on top of it. This mirrors how
musicbrainz_client.py gets real status codes from musicbrainzngs's
`.cause.code`. Local fingerprinting still goes through fpcalc directly
(fingerprint.py, Phase 1) — pyacoustid isn't used here at all.

Response fields used are only those explicitly documented at
https://acoustid.org/webservice for `meta=recordings+releasegroups`
(status, results[].id/score, results[].recordings[].id/title/duration/
artists[].name, recordings[].releasegroups[].id/title/type) plus the
`artists[].joinphrase` field, which isn't shown in the docs' own example
but is used by pyacoustid's reference `parse_lookup_result` against this
same API — trusted as a verified real field, not a guess. The `releases`
meta option's response shape (in particular any per-release date field) is
*not* documented anywhere we could verify, so it is deliberately not
requested or used: album/year selection here can distinguish "official
album" from "compilation" (via `releasegroups[].type`) but cannot pick an
earliest release or set a year, unlike Tier 2's MusicBrainz-backed
selection. `year` is left `None` rather than inventing a field.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

import httpx

from mp3_autotag import db
from mp3_autotag.rate_limit import RateLimiter

LOOKUP_URL = "https://api.acoustid.org/v2/lookup"
META = "recordings releasegroups"
_RETRYABLE_STATUSES = {429, 503}


class AcoustidError(Exception):
    """Raised when an AcoustID lookup fails after retries, or the response
    is malformed / reports a non-ok status."""


@dataclass
class AcoustidCandidate:
    acoustid_id: str
    recording_mbid: str | None
    artist: str | None
    title: str
    album: str | None
    year: str | None
    duration_s: float | None
    score: float  # AcoustID's native 0.0-1.0 scale, per spec §6 tier1_min_score
    raw: dict = field(default_factory=dict, repr=False)


class _HttpClient(Protocol):
    def post(self, url: str, data: dict) -> httpx.Response: ...


def _select_releasegroup(releasegroups: list[dict]) -> str | None:
    if not releasegroups:
        return None
    best = sorted(releasegroups, key=lambda rg: rg.get("type") == "Compilation")[0]
    return best.get("title")


def _artist_name(artists: list[dict] | None) -> str | None:
    if not artists:
        return None
    name = "".join(a.get("name", "") + a.get("joinphrase", "") for a in artists).strip()
    return name or None


def parse_lookup_response(data: dict) -> list[AcoustidCandidate]:
    if data.get("status") != "ok":
        raise AcoustidError(f"AcoustID response status: {data.get('status')!r}")

    candidates: list[AcoustidCandidate] = []
    for result in data.get("results", []):
        score = float(result.get("score", 0.0))
        acoustid_id = result.get("id", "")
        for recording in result.get("recordings", []) or []:
            candidates.append(
                AcoustidCandidate(
                    acoustid_id=acoustid_id,
                    recording_mbid=recording.get("id"),
                    artist=_artist_name(recording.get("artists")),
                    title=recording.get("title", ""),
                    album=_select_releasegroup(recording.get("releasegroups") or []),
                    year=None,  # release date field is undocumented; not guessed
                    duration_s=recording.get("duration"),
                    score=score,
                    raw=recording,
                )
            )
    return candidates


class AcoustidClient:
    def __init__(
        self,
        conn: sqlite3.Connection,
        rate_limiter: RateLimiter,
        api_key: str,
        http_client: _HttpClient | None = None,
        max_retries: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._conn = conn
        self._rate_limiter = rate_limiter
        self._api_key = api_key
        self._http = http_client if http_client is not None else httpx.Client(timeout=10)
        self._max_retries = max_retries
        self._sleep = sleep

    def lookup(self, fingerprint: str, duration_s: float) -> list[AcoustidCandidate]:
        cache_key = f"acoustid:lookup:{fingerprint}:{int(duration_s)}"
        cached_json = db.get_api_cache(self._conn, cache_key)
        if cached_json is not None:
            data = json.loads(cached_json)
        else:
            data = self._fetch_with_retry(fingerprint, duration_s)
            db.set_api_cache(self._conn, cache_key, "acoustid", json.dumps(data))
        return parse_lookup_response(data)

    def _fetch_with_retry(self, fingerprint: str, duration_s: float) -> dict:
        params = {
            "client": self._api_key,
            "fingerprint": fingerprint,
            "duration": int(duration_s),
            "format": "json",
            "meta": META,
        }
        attempt = 0
        while True:
            self._rate_limiter.acquire()
            response = self._http.post(LOOKUP_URL, data=params)
            if response.status_code in _RETRYABLE_STATUSES and attempt < self._max_retries:
                self._sleep(2**attempt)
                attempt += 1
                continue
            if response.status_code >= 400:
                raise AcoustidError(f"AcoustID request failed: {response.status_code} {response.text}")
            try:
                return response.json()
            except ValueError as exc:
                raise AcoustidError("AcoustID response is not valid JSON") from exc
