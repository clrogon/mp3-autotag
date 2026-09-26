"""Local Chromaprint (fpcalc) fingerprinting, cached by file hash.

This module only runs the local `fpcalc` binary — no network calls. The
AcoustID *lookup* (network, rate-limited) is added in Phase 3 as part of
Tier 1 identification, on top of this cache.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

from mp3_autotag.config import Config


class FingerprintError(Exception):
    """Raised when fpcalc is missing or fails on a given file."""


@dataclass
class Fingerprint:
    duration_s: float
    fingerprint: str


def resolve_fpcalc_path(config: Config) -> str | None:
    if config.general.fpcalc_path:
        return config.general.fpcalc_path
    return shutil.which("fpcalc")


def _run_fpcalc(fpcalc_path: str, file_path: str) -> Fingerprint:
    try:
        result = subprocess.run(
            [fpcalc_path, "-json", file_path],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise FingerprintError(
            f"fpcalc failed on {file_path!r} (exit {exc.returncode}): {exc.stderr.strip()}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FingerprintError(f"fpcalc timed out on {file_path!r}") from exc

    try:
        payload = json.loads(result.stdout)
        return Fingerprint(
            duration_s=float(payload["duration"]),
            fingerprint=str(payload["fingerprint"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise FingerprintError(
            f"could not parse fpcalc output for {file_path!r}: {result.stdout!r}"
        ) from exc


def get_cached_fingerprint(conn: sqlite3.Connection, file_hash: str) -> Fingerprint | None:
    row = conn.execute(
        "SELECT duration_s, fingerprint FROM fingerprints WHERE file_hash = ?",
        (file_hash,),
    ).fetchone()
    if row is None:
        return None
    return Fingerprint(duration_s=row["duration_s"], fingerprint=row["fingerprint"])


def store_fingerprint(conn: sqlite3.Connection, file_hash: str, fp: Fingerprint) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO fingerprints (file_hash, fingerprint, duration_s, computed_at) "
        "VALUES (?, ?, ?, ?)",
        (file_hash, fp.fingerprint, fp.duration_s, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def get_or_compute_fingerprint(
    conn: sqlite3.Connection,
    file_hash: str,
    file_path: str,
    fpcalc_path: str | None,
) -> Fingerprint | None:
    """Cache-first fingerprint lookup. Returns None if fpcalc isn't available."""
    cached = get_cached_fingerprint(conn, file_hash)
    if cached is not None:
        return cached
    if fpcalc_path is None:
        return None
    fp = _run_fpcalc(fpcalc_path, file_path)
    store_fingerprint(conn, file_hash, fp)
    return fp
