"""Phase 5 acceptance test (spec §10, row 5):

"Write -> rollback returns a byte-identical file; audio-stream hash
unchanged."

Seeds a fake `identify` run directly in the DB (identify's own pipeline is
already covered end to end in test_pipeline.py / test_cli_identify.py) so
this test can focus purely on apply/backup/journal/rollback.
"""

from __future__ import annotations

import shutil

from typer.testing import CliRunner

from mp3_autotag import db
from mp3_autotag.cli import app
from mp3_autotag.pipeline import StoredCandidate
from mp3_autotag.tagger import audio_stream_hash
from mp3_autotag.tags import read_existing_tags

runner = CliRunner()


def _seed_identify_run(db_path, file_path, **candidate_overrides):
    conn = db.connect(db_path)
    db.init_schema(conn)
    # `candidates.file_path` has a FK on `files`, so the file must be scanned first.
    from mp3_autotag.config import Config
    from mp3_autotag.scan import scan_path

    scan_path(file_path.parent, Config(), conn)
    run_id = db.new_run(conn, "identify", "{}")
    defaults = dict(
        tier=2,
        rank=1,
        artist="New Artist",
        title="New Title",
        album="New Album",
        year="2021",
        source="musicbrainz",
        score=95.0,
        mbid="mb-xyz",
        acoustid_id=None,
        duration_s=2.085,
        accepted=True,
        raw={},
    )
    defaults.update(candidate_overrides)
    stored = [StoredCandidate(**defaults)]
    db.insert_candidates(conn, run_id, str(file_path), stored)
    db.record_identify_result(conn, run_id, str(file_path), "MATCHED_TIER2", 2)
    conn.close()
    return run_id


def test_apply_dry_run_writes_nothing(fixtures_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    target = music_dir / "clean_tagged.mp3"
    shutil.copy(fixtures_dir / "clean_tagged.mp3", target)
    original_bytes = target.read_bytes()
    original_mtime = target.stat().st_mtime

    run_id = _seed_identify_run("mp3-autotag.db", target)

    result = runner.invoke(app, ["apply", str(music_dir), "--run-id", run_id])

    assert result.exit_code == 0, result.output
    assert "New Title" in result.output  # diff table shown
    assert "changed=0" in result.output
    assert target.read_bytes() == original_bytes
    assert target.stat().st_mtime == original_mtime


def test_apply_write_then_rollback_is_byte_identical(fixtures_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    target = music_dir / "clean_tagged.mp3"
    shutil.copy(fixtures_dir / "clean_tagged.mp3", target)

    original_bytes = target.read_bytes()
    original_audio_hash = audio_stream_hash(target)
    original_tags = read_existing_tags(str(target))

    run_id = _seed_identify_run("mp3-autotag.db", target)

    write_result = runner.invoke(app, ["apply", str(music_dir), "--write", "--run-id", run_id])
    assert write_result.exit_code == 0, write_result.output
    assert "changed=1" in write_result.output

    # The file actually changed...
    assert target.read_bytes() != original_bytes
    # ...but the audio stream itself didn't...
    assert audio_stream_hash(target) == original_audio_hash
    # ...and untouched fields (never blanked) survived, while matched ones updated.
    new_tags = read_existing_tags(str(target))
    assert new_tags.title == "New Title"
    assert new_tags.artist == "New Artist"
    assert new_tags.album == "New Album"
    assert new_tags.genre == original_tags.genre  # not provided by candidate -> untouched
    assert new_tags.track == original_tags.track

    conn = db.connect("mp3-autotag.db")
    apply_run_id = db.latest_run_id(conn, "apply")
    conn.close()
    assert apply_run_id is not None

    rollback_result = runner.invoke(app, ["rollback", apply_run_id])
    assert rollback_result.exit_code == 0, rollback_result.output
    assert "restored" in rollback_result.output

    # The core Phase 5 acceptance criterion: byte-identical restore.
    assert target.read_bytes() == original_bytes
    assert audio_stream_hash(target) == original_audio_hash


def test_apply_skips_files_with_no_accepted_candidate(fixtures_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    shutil.copy(fixtures_dir / "untagged.mp3", music_dir / "untagged.mp3")

    conn = db.connect("mp3-autotag.db")
    db.init_schema(conn)
    run_id = db.new_run(conn, "identify", "{}")
    conn.close()

    result = runner.invoke(app, ["apply", str(music_dir), "--write", "--run-id", run_id])

    assert result.exit_code == 0, result.output
    assert "no_accepted_match=1" in result.output
    assert "changed=0" in result.output


def test_apply_with_no_identify_run_errors(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    (music_dir / "x.mp3").write_bytes(b"data")

    result = runner.invoke(app, ["apply", str(music_dir)])
    assert result.exit_code != 0


def test_rollback_with_unknown_run_id_reports_no_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    conn = db.connect("mp3-autotag.db")
    db.init_schema(conn)
    conn.close()

    result = runner.invoke(app, ["rollback", "nonexistent-run-id"])
    assert result.exit_code == 0  # nothing to restore, nothing failed either
