"""Backup-before-write and rollback (spec §7.2, §7.4).

Backups live at `backups/<run-id>/<path-with-leading-anchor-stripped>` —
e.g. `/home/user/music/song.mp3` backs up to
`backups/<run-id>/home/user/music/song.mp3`. This is deliberately
reconstructible from the run-id and a file's absolute path alone (both
already stored in the `changes` journal), since `rollback <run-id>` takes
no path argument and so cannot be told the original scan root again.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path


class BackupError(Exception):
    """Raised when a file cannot be backed up before a write is attempted."""


def _anchor_stripped_subpath(file_path: Path) -> Path:
    resolved = file_path.resolve()
    parts = resolved.parts
    if resolved.anchor and parts:
        return Path(*parts[1:]) if len(parts) > 1 else Path(resolved.name)
    return resolved


def backup_path_for(backup_root: Path, run_id: str, file_path: Path) -> Path:
    return backup_root / run_id / _anchor_stripped_subpath(file_path)


def make_backup(backup_root: Path, run_id: str, file_path: Path) -> Path:
    dest = backup_path_for(backup_root, run_id, file_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(file_path, dest)
    except OSError as exc:
        raise BackupError(f"could not back up {file_path}: {exc}") from exc
    return dest


@dataclass
class RollbackSummary:
    restored: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (file_path, reason)


def rollback_run(conn, run_id: str, backup_root: Path) -> RollbackSummary:
    from mp3_autotag import db
    from mp3_autotag.scan import sha256_file

    summary = RollbackSummary()
    for row in db.get_changed_files_for_run(conn, run_id):
        file_path = Path(row["file_path"])
        expected_hash = row["file_hash_before"]
        backup_file = backup_path_for(backup_root, run_id, file_path)

        if not backup_file.is_file():
            summary.failed.append((str(file_path), f"backup not found: {backup_file}"))
            continue

        shutil.copy2(backup_file, file_path)

        restored_hash = sha256_file(file_path)
        if restored_hash != expected_hash:
            summary.failed.append(
                (str(file_path), f"hash mismatch after restore: expected {expected_hash}, got {restored_hash}")
            )
            continue

        summary.restored.append(str(file_path))

    return summary
