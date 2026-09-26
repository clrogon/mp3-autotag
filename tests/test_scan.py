from __future__ import annotations

import json
import shutil
import subprocess

from mp3_autotag import db
from mp3_autotag.scan import iter_mp3_files, scan_path, sha256_file


def _copy_fixtures(fixtures_dir, tmp_path, names):
    for name in names:
        shutil.copy(fixtures_dir / name, tmp_path / name)


def test_iter_mp3_files_recursive_and_case_insensitive(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.mp3").write_bytes(b"x")
    (tmp_path / "sub" / "B.MP3").write_bytes(b"x")
    (tmp_path / "not-audio.txt").write_bytes(b"x")

    found = iter_mp3_files(tmp_path)
    assert [p.name for p in found] == ["a.mp3", "B.MP3"]


def test_sha256_file_is_stable(tmp_path):
    f = tmp_path / "x.mp3"
    f.write_bytes(b"hello world")
    assert sha256_file(f) == sha256_file(f)
    assert len(sha256_file(f)) == 64


def test_scan_path_inventories_and_reads_tags(fixtures_dir, tmp_path, memory_conn, default_config):
    names = ["clean_tagged.mp3", "unicode_tagged.mp3", "untagged.mp3", "partial_tagged.mp3"]
    _copy_fixtures(fixtures_dir, tmp_path, names)

    summary = scan_path(tmp_path, default_config, memory_conn)

    assert summary.total_files == 4
    assert summary.tags_complete == 2  # clean_tagged and unicode_tagged both have title+artist+album
    # No fpcalc binary in this environment -> fingerprinting is skipped, not a crash.
    assert summary.fingerprint_skipped_no_fpcalc == 4
    assert summary.fingerprinted == 0

    rows = {
        row["file_path"].split("/")[-1]: row
        for row in memory_conn.execute("SELECT * FROM files").fetchall()
    }
    assert set(rows) == set(names)
    assert rows["clean_tagged.mp3"]["tag_title"] == "Test Track"
    assert rows["unicode_tagged.mp3"]["tag_artist"] == "Cão Ção"
    assert rows["untagged.mp3"]["tag_title"] is None
    assert rows["clean_tagged.mp3"]["duration_s"] is not None


def test_scan_path_respects_limit(fixtures_dir, tmp_path, memory_conn, default_config):
    _copy_fixtures(
        fixtures_dir, tmp_path, ["clean_tagged.mp3", "unicode_tagged.mp3", "untagged.mp3"]
    )
    summary = scan_path(tmp_path, default_config, memory_conn, limit=2)
    assert summary.total_files == 2


def test_rescan_upserts_instead_of_duplicating(fixtures_dir, tmp_path, memory_conn, default_config):
    _copy_fixtures(fixtures_dir, tmp_path, ["clean_tagged.mp3"])
    scan_path(tmp_path, default_config, memory_conn)
    scan_path(tmp_path, default_config, memory_conn)
    count = memory_conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
    assert count == 1


def test_second_scan_makes_zero_fpcalc_calls_when_fingerprinting(
    fixtures_dir, tmp_path, memory_conn, default_config, monkeypatch
):
    _copy_fixtures(fixtures_dir, tmp_path, ["clean_tagged.mp3"])

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps({"duration": 2.09, "fingerprint": "AQfake"}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr("mp3_autotag.scan.resolve_fpcalc_path", lambda config: "/usr/bin/fpcalc")

    summary1 = scan_path(tmp_path, default_config, memory_conn)
    assert summary1.fingerprinted == 1
    assert len(calls) == 1

    summary2 = scan_path(tmp_path, default_config, memory_conn)
    assert summary2.fingerprinted == 1
    assert len(calls) == 1  # cached: zero additional fpcalc invocations
