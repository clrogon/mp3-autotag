from __future__ import annotations

from mp3_autotag import db


def test_init_schema_creates_expected_tables(memory_conn):
    tables = {
        row["name"]
        for row in memory_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {
        "runs",
        "files",
        "fingerprints",
        "api_cache",
        "candidates",
        "changes",
        "review_decisions",
    } <= tables


def test_init_schema_is_idempotent(memory_conn):
    db.init_schema(memory_conn)  # second call must not raise
    db.init_schema(memory_conn)


def test_new_run_and_finish_run(memory_conn):
    run_id = db.new_run(memory_conn, "scan", '{"path": "x"}')
    row = memory_conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row["command"] == "scan"
    assert row["status"] == "running"
    assert row["finished_at"] is None

    db.finish_run(memory_conn, run_id, "completed")
    row = memory_conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert row["status"] == "completed"
    assert row["finished_at"] is not None
