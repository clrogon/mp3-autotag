"""SQLite schema and connection helper.

One database file (`general.db_path`) holds everything: file inventory,
fingerprint cache, API response cache, candidates, the change journal, and
run bookkeeping. Table shapes follow spec §7 (journal columns) and §9.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    command     TEXT NOT NULL,
    args_json   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'running',
    started_at  TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS files (
    file_path               TEXT PRIMARY KEY,
    file_hash               TEXT NOT NULL,
    size_bytes              INTEGER NOT NULL,
    mtime                   REAL NOT NULL,
    duration_s              REAL,
    tag_title               TEXT,
    tag_artist              TEXT,
    tag_album               TEXT,
    tag_albumartist         TEXT,
    tag_track               TEXT,
    tag_disc                TEXT,
    tag_year                TEXT,
    tag_genre               TEXT,
    tag_musicbrainz_track_id TEXT,
    status                  TEXT,
    last_scanned_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fingerprints (
    file_hash    TEXT PRIMARY KEY,
    fingerprint  TEXT NOT NULL,
    duration_s   REAL NOT NULL,
    computed_at  TEXT NOT NULL
);

-- Cached API responses (AcoustID / MusicBrainz / Tier 3), keyed by a
-- caller-chosen cache key so re-runs cost zero calls (spec §7.8).
CREATE TABLE IF NOT EXISTS api_cache (
    cache_key    TEXT PRIMARY KEY,
    provider     TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL REFERENCES runs(run_id),
    file_path   TEXT NOT NULL REFERENCES files(file_path),
    tier        INTEGER NOT NULL,
    rank        INTEGER NOT NULL,
    artist      TEXT,
    title       TEXT,
    album       TEXT,
    year        TEXT,
    source      TEXT,
    score       REAL,
    mbid        TEXT,
    duration_s  REAL,
    accepted    INTEGER NOT NULL DEFAULT 0,
    raw_json    TEXT
);

CREATE TABLE IF NOT EXISTS changes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT NOT NULL REFERENCES runs(run_id),
    file_path        TEXT NOT NULL,
    file_hash_before TEXT NOT NULL,
    file_hash_after  TEXT,
    field            TEXT NOT NULL,
    old_value        TEXT,
    new_value        TEXT,
    source_tier      INTEGER,
    timestamp        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_decisions (
    file_path  TEXT PRIMARY KEY REFERENCES files(file_path),
    decision   TEXT NOT NULL,
    manual_json TEXT,
    imported_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_candidates_run_file ON candidates(run_id, file_path);
CREATE INDEX IF NOT EXISTS idx_changes_run ON changes(run_id);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    with closing(conn.cursor()) as cur:
        cur.executescript(SCHEMA)
    conn.commit()


def new_run(conn: sqlite3.Connection, command: str, args_json: str) -> str:
    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO runs (run_id, command, args_json, status, started_at) "
        "VALUES (?, ?, ?, 'running', ?)",
        (run_id, command, args_json, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return run_id


def finish_run(conn: sqlite3.Connection, run_id: str, status: str) -> None:
    conn.execute(
        "UPDATE runs SET status = ?, finished_at = ? WHERE run_id = ?",
        (status, datetime.now(timezone.utc).isoformat(), run_id),
    )
    conn.commit()


def get_api_cache(conn: sqlite3.Connection, cache_key: str) -> str | None:
    row = conn.execute(
        "SELECT response_json FROM api_cache WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    return row["response_json"] if row is not None else None


def set_api_cache(conn: sqlite3.Connection, cache_key: str, provider: str, response_json: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO api_cache (cache_key, provider, response_json, created_at) "
        "VALUES (?, ?, ?, ?)",
        (cache_key, provider, response_json, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
