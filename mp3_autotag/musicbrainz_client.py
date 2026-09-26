"""MusicBrainz recording search for Tier 2 (spec §6, §7.7).

Rate-limited to 1 req/s, retries with exponential backoff on 429/503,
caches raw responses in `api_cache` keyed by query so re-runs cost zero
calls (spec §7.8), and uses a descriptive User-Agent as MusicBrainz
requires (spec §7.7): `mp3-autotag/<version> ( <contact-email> )`.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Callable

import musicbrainzngs

from mp3_autotag import db
from mp3_autotag.rate_limit import RateLimiter

_RETRYABLE_STATUSES = {429, 503}


class MusicBrainzError(Exception):
    """Raised when a MusicBrainz lookup fails after retries."""


@dataclass
class MBCandidate:
    mbid: str
    artist: str | None
    title: str
    album: str | None
    year: str | None
    duration_s: float | None
    raw: dict = field(default_factory=dict, repr=False)


def configure_user_agent(app_name: str, app_version: str, contact_email: str) -> None:
    musicbrainzngs.set_useragent(app_name, app_version, contact=contact_email)


def _select_release(release_list: list[dict]) -> tuple[str | None, str | None]:
    """Prefer an official studio release over a compilation, else earliest.

    Tier 2 candidates have no existing album/filename to match against (that
    preference rule in spec §6 is scoped to Tier 1), so this reuses Tier 1's
    fallback ordering: official studio album over compilation, then earliest.
    """
    if not release_list:
        return None, None

    def sort_key(release: dict) -> tuple[bool, str]:
        release_group = release.get("release-group") or {}
        secondary_types = release_group.get("secondary-type-list") or []
        is_compilation = release_group.get("primary-type") == "Compilation" or "Compilation" in secondary_types
        date = release.get("date") or "9999"
        return (is_compilation, date)

    best = sorted(release_list, key=sort_key)[0]
    date = best.get("date") or ""
    return best.get("title"), (date[:4] or None)


def _normalize(recording: dict) -> MBCandidate:
    artist = recording.get("artist-credit-phrase")
    if not artist:
        credits = recording.get("artist-credit") or []
        names = [
            c.get("artist", {}).get("name", "")
            for c in credits
            if isinstance(c, dict) and c.get("artist")
        ]
        artist = " ".join(n for n in names if n).strip() or None

    length = recording.get("length")
    duration_s = float(length) / 1000 if length else None

    album, year = _select_release(recording.get("release-list") or [])

    return MBCandidate(
        mbid=recording["id"],
        artist=artist,
        title=recording.get("title", ""),
        album=album,
        year=year,
        duration_s=duration_s,
        raw=recording,
    )


class MusicBrainzClient:
    def __init__(
        self,
        conn: sqlite3.Connection,
        rate_limiter: RateLimiter,
        max_retries: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._conn = conn
        self._rate_limiter = rate_limiter
        self._max_retries = max_retries
        self._sleep = sleep

    def search_recordings(self, artist: str | None, title: str, limit: int = 10) -> list[MBCandidate]:
        cache_key = f"musicbrainz:recording:{(artist or '').strip().lower()}|{title.strip().lower()}|{limit}"
        cached_json = db.get_api_cache(self._conn, cache_key)
        if cached_json is not None:
            recordings = json.loads(cached_json)
        else:
            recordings = self._fetch_with_retry(artist, title, limit)
            db.set_api_cache(self._conn, cache_key, "musicbrainz", json.dumps(recordings))
        return [_normalize(r) for r in recordings]

    def _fetch_with_retry(self, artist: str | None, title: str, limit: int) -> list[dict]:
        attempt = 0
        while True:
            self._rate_limiter.acquire()
            try:
                result = musicbrainzngs.search_recordings(
                    artist=artist or "", recording=title, limit=limit
                )
                return result.get("recording-list", [])
            except musicbrainzngs.WebServiceError as exc:
                status = getattr(exc.cause, "code", None)
                if status in _RETRYABLE_STATUSES and attempt < self._max_retries:
                    self._sleep(2**attempt)
                    attempt += 1
                    continue
                raise MusicBrainzError(str(exc)) from exc
