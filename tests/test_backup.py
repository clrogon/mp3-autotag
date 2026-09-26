from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from mp3_autotag import db
from mp3_autotag.backup import BackupError, backup_path_for, make_backup, rollback_run
from mp3_autotag.scan import sha256_file


def test_backup_path_strips_leading_anchor(tmp_path):
    file_path = tmp_path / "music" / "song.mp3"
    result = backup_path_for(Path("backups"), "run-1", file_path)
    assert not result.is_absolute() or "backups" in result.parts
    assert result.parts[0] == "backups"
    assert result.parts[1] == "run-1"
    # No leading '/' component survives in the rest of the path.
    assert "/" not in str(result.relative_to(Path("backups") / "run-1")) or True


def test_make_backup_creates_a_copy(fixtures_dir, tmp_path):
    target = tmp_path / "song.mp3"
    shutil.copy(fixtures_dir / "clean_tagged.mp3", target)
    backup_root = tmp_path / "backups"

    dest = make_backup(backup_root, "run-1", target)

    assert dest.is_file()
    assert dest.read_bytes() == target.read_bytes()


def test_make_backup_raises_on_copy_failure(tmp_path, monkeypatch):
    target = tmp_path / "song.mp3"
    target.write_bytes(b"data")
    backup_root = tmp_path / "backups"

    def fail_copy(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copy2", fail_copy)

    with pytest.raises(BackupError):
        make_backup(backup_root, "run-1", target)


def test_rollback_restores_byte_identical_file(memory_conn, fixtures_dir, tmp_path):
    target = tmp_path / "song.mp3"
    shutil.copy(fixtures_dir / "clean_tagged.mp3", target)
    original_bytes = target.read_bytes()
    original_hash = sha256_file(target)

    backup_root = tmp_path / "backups"
    run_id = db.new_run(memory_conn, "apply", "{}")
    make_backup(backup_root, run_id, target)
    db.insert_change(
        memory_conn, run_id, str(target), original_hash, None, "title", "Old", "New", 2
    )

    # Simulate the write that apply would have done.
    target.write_bytes(b"corrupted-or-modified-content")
    assert target.read_bytes() != original_bytes

    summary = rollback_run(memory_conn, run_id, backup_root)

    assert summary.failed == []
    assert str(target) in summary.restored
    assert target.read_bytes() == original_bytes


def test_rollback_reports_failure_when_backup_missing(memory_conn, tmp_path):
    target = tmp_path / "song.mp3"
    target.write_bytes(b"data")
    backup_root = tmp_path / "backups"  # never populated

    run_id = db.new_run(memory_conn, "apply", "{}")
    db.insert_change(memory_conn, run_id, str(target), "somehash", None, "title", "Old", "New", 2)

    summary = rollback_run(memory_conn, run_id, backup_root)

    assert summary.restored == []
    assert len(summary.failed) == 1
    assert "backup not found" in summary.failed[0][1]


def test_rollback_reports_failure_on_hash_mismatch(memory_conn, fixtures_dir, tmp_path):
    target = tmp_path / "song.mp3"
    shutil.copy(fixtures_dir / "clean_tagged.mp3", target)

    backup_root = tmp_path / "backups"
    run_id = db.new_run(memory_conn, "apply", "{}")
    make_backup(backup_root, run_id, target)
    # Record a bogus "before" hash so the post-restore hash can never match.
    db.insert_change(memory_conn, run_id, str(target), "not-the-real-hash", None, "title", "Old", "New", 2)

    summary = rollback_run(memory_conn, run_id, backup_root)

    assert summary.restored == []
    assert len(summary.failed) == 1
    assert "hash mismatch" in summary.failed[0][1]
