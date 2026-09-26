"""`scan`: inventory MP3 files, read existing tags, compute fingerprints (cached).

Never writes to the audio files themselves — only to the SQLite DB.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from mp3_autotag.config import Config
from mp3_autotag.fingerprint import FingerprintError, get_or_compute_fingerprint, resolve_fpcalc_path
from mp3_autotag.tags import read_existing_tags

logger = logging.getLogger("mp3_autotag.scan")

_CHUNK_SIZE = 1 << 20  # 1 MiB


@dataclass
class ScanSummary:
    total_files: int = 0
    tags_complete: int = 0
    fingerprinted: int = 0
    fingerprint_skipped_no_fpcalc: int = 0
    fingerprint_failed: int = 0


def iter_mp3_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() == ".mp3" else []
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".mp3")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_duration_s(path: Path) -> float | None:
    from mutagen.mp3 import MP3, HeaderNotFoundError

    try:
        return MP3(path).info.length
    except HeaderNotFoundError:
        return None


def scan_path(
    root: Path,
    config: Config,
    conn: sqlite3.Connection,
    limit: int | None = None,
) -> ScanSummary:
    files = iter_mp3_files(root)
    if limit is not None:
        files = files[:limit]

    fpcalc_path = resolve_fpcalc_path(config)
    if fpcalc_path is None:
        logger.warning("fpcalc not found on PATH or in config; fingerprints will be skipped")

    summary = ScanSummary()
    now = datetime.now(timezone.utc).isoformat()

    for file_path in files:
        summary.total_files += 1
        file_hash = sha256_file(file_path)
        stat = file_path.stat()
        duration_s = _read_duration_s(file_path)
        existing = read_existing_tags(str(file_path))
        if existing.is_minimally_complete():
            summary.tags_complete += 1

        fingerprint = None
        if fpcalc_path is not None:
            try:
                fingerprint = get_or_compute_fingerprint(conn, file_hash, str(file_path), fpcalc_path)
            except FingerprintError as exc:
                summary.fingerprint_failed += 1
                logger.warning("%s", exc)
        else:
            summary.fingerprint_skipped_no_fpcalc += 1

        if fingerprint is not None:
            summary.fingerprinted += 1

        conn.execute(
            """
            INSERT INTO files (
                file_path, file_hash, size_bytes, mtime, duration_s,
                tag_title, tag_artist, tag_album, tag_albumartist,
                tag_track, tag_disc, tag_year, tag_genre,
                tag_musicbrainz_track_id, status, last_scanned_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                file_hash=excluded.file_hash,
                size_bytes=excluded.size_bytes,
                mtime=excluded.mtime,
                duration_s=excluded.duration_s,
                tag_title=excluded.tag_title,
                tag_artist=excluded.tag_artist,
                tag_album=excluded.tag_album,
                tag_albumartist=excluded.tag_albumartist,
                tag_track=excluded.tag_track,
                tag_disc=excluded.tag_disc,
                tag_year=excluded.tag_year,
                tag_genre=excluded.tag_genre,
                tag_musicbrainz_track_id=excluded.tag_musicbrainz_track_id,
                last_scanned_at=excluded.last_scanned_at
            """,
            (
                str(file_path),
                file_hash,
                stat.st_size,
                stat.st_mtime,
                duration_s,
                existing.title,
                existing.artist,
                existing.album,
                existing.albumartist,
                existing.track,
                existing.disc,
                existing.year,
                existing.genre,
                existing.musicbrainz_track_id,
                "SCANNED",
                now,
            ),
        )

    conn.commit()
    return summary
