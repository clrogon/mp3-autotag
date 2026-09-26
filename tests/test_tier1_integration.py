"""Phase 3 acceptance test (spec §10, row 3):

"Fixture file identified; second run makes zero API calls."

Exercises the full local chain — sha256 hash -> cached fpcalc fingerprint ->
cached AcoustID lookup -> Tier 1 accept — twice against the same DB, and
asserts neither fpcalc nor the AcoustID HTTP client is invoked a second time.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from mp3_autotag.acoustid_client import AcoustidClient
from mp3_autotag.config import ThresholdsConfig
from mp3_autotag.fingerprint import get_or_compute_fingerprint
from mp3_autotag.rate_limit import RateLimiter
from mp3_autotag.scan import sha256_file
from mp3_autotag.tier1 import run_tier1


class FakeHttpClient:
    def __init__(self, json_payload):
        self._json_payload = json_payload
        self.calls = 0

    def post(self, url, data):
        self.calls += 1

        class _Resp:
            status_code = 200

            def json(_self):
                return self._json_payload

        return _Resp()


def _acoustid_payload():
    return {
        "status": "ok",
        "results": [
            {
                "id": "acoustid-xyz",
                "score": 0.97,
                "recordings": [
                    {
                        "id": "mbid-xyz",
                        "title": "Test Track",
                        "duration": 2,
                        "artists": [{"id": "a1", "name": "Test Artist"}],
                        "releasegroups": [{"id": "rg1", "type": "Album", "title": "Test Album"}],
                    }
                ],
            }
        ],
    }


def test_fixture_identified_and_second_run_makes_zero_api_calls(
    fixtures_dir, tmp_path, memory_conn, monkeypatch
):
    fixture = tmp_path / "clean_tagged.mp3"
    shutil.copy(fixtures_dir / "clean_tagged.mp3", fixture)

    fpcalc_calls = []

    def fake_subprocess_run(args, **kwargs):
        fpcalc_calls.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps({"duration": 2.085, "fingerprint": "AQ_fake_fp"}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    http = FakeHttpClient(_acoustid_payload())
    limiter = RateLimiter(0.0, clock=lambda: 0.0, sleep=lambda d: None)
    acoustid_client = AcoustidClient(memory_conn, limiter, api_key="testkey", http_client=http)
    thresholds = ThresholdsConfig()

    def identify_once():
        file_hash = sha256_file(fixture)
        fp = get_or_compute_fingerprint(memory_conn, file_hash, str(fixture), "/usr/bin/fpcalc")
        return run_tier1(fp.fingerprint, fp.duration_s, acoustid_client, thresholds)

    # First run: identifies the file, one fpcalc call, one AcoustID call.
    result1 = identify_once()
    assert result1.accepted is not None
    assert result1.accepted.title == "Test Track"
    assert len(fpcalc_calls) == 1
    assert http.calls == 1

    # Second run: both caches hit — zero additional fpcalc or AcoustID calls.
    result2 = identify_once()
    assert result2.accepted is not None
    assert len(fpcalc_calls) == 1
    assert http.calls == 1
