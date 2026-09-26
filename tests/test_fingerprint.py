from __future__ import annotations

import json
import subprocess

import pytest

from mp3_autotag.config import Config
from mp3_autotag.fingerprint import (
    FingerprintError,
    get_cached_fingerprint,
    get_or_compute_fingerprint,
    resolve_fpcalc_path,
)


def test_resolve_fpcalc_path_prefers_config(monkeypatch):
    cfg = Config()
    cfg.general.fpcalc_path = "/opt/custom/fpcalc"
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/fpcalc")
    assert resolve_fpcalc_path(cfg) == "/opt/custom/fpcalc"


def test_resolve_fpcalc_path_falls_back_to_path(monkeypatch):
    cfg = Config()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/fpcalc")
    assert resolve_fpcalc_path(cfg) == "/usr/bin/fpcalc"


def test_resolve_fpcalc_path_none_when_missing(monkeypatch):
    cfg = Config()
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert resolve_fpcalc_path(cfg) is None


def _fake_completed_process(stdout: dict) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(stdout), stderr="")


def test_get_or_compute_fingerprint_caches_and_skips_second_fpcalc_call(memory_conn, monkeypatch, tmp_path):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _fake_completed_process({"duration": 2.09, "fingerprint": "AQAAdEmyaEk"})

    monkeypatch.setattr(subprocess, "run", fake_run)

    fake_file = tmp_path / "a.mp3"
    fake_file.write_bytes(b"not real audio")

    fp1 = get_or_compute_fingerprint(memory_conn, "hash-a", str(fake_file), "/usr/bin/fpcalc")
    assert fp1.fingerprint == "AQAAdEmyaEk"
    assert len(calls) == 1

    # Second call for the same file hash must hit the cache, not fpcalc again.
    fp2 = get_or_compute_fingerprint(memory_conn, "hash-a", str(fake_file), "/usr/bin/fpcalc")
    assert fp2.fingerprint == fp1.fingerprint
    assert len(calls) == 1

    cached = get_cached_fingerprint(memory_conn, "hash-a")
    assert cached is not None


def test_get_or_compute_fingerprint_returns_none_without_fpcalc(memory_conn, tmp_path):
    fake_file = tmp_path / "a.mp3"
    fake_file.write_bytes(b"x")
    assert get_or_compute_fingerprint(memory_conn, "hash-b", str(fake_file), None) is None


def test_fpcalc_failure_raises_fingerprint_error(memory_conn, monkeypatch, tmp_path):
    def fake_run(args, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=args, stderr="bad file")

    monkeypatch.setattr(subprocess, "run", fake_run)
    fake_file = tmp_path / "a.mp3"
    fake_file.write_bytes(b"x")

    with pytest.raises(FingerprintError):
        get_or_compute_fingerprint(memory_conn, "hash-c", str(fake_file), "/usr/bin/fpcalc")
