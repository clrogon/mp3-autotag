from __future__ import annotations

import shutil

from typer.testing import CliRunner

from mp3_autotag.cli import app

runner = CliRunner()


def test_identify_tier0_only_and_report(fixtures_dir, tmp_path, monkeypatch):
    """--tiers "" disables Tiers 1-3 (only Tier 0's skip-check runs), so this
    exercises the CLI wiring end to end with no network and no fpcalc."""
    monkeypatch.chdir(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    shutil.copy(fixtures_dir / "clean_tagged.mp3", music_dir / "clean_tagged.mp3")
    shutil.copy(fixtures_dir / "untagged.mp3", music_dir / "untagged.mp3")

    result = runner.invoke(app, ["identify", str(music_dir), "--tiers", ""])
    assert result.exit_code == 0, result.output
    assert "SKIPPED_COMPLETE" in result.output
    assert "REVIEW_UNMATCHED" in result.output

    report_result = runner.invoke(app, ["report"])
    assert report_result.exit_code == 0, report_result.output
    assert "SKIPPED_COMPLETE" in report_result.output
    assert "REVIEW_UNMATCHED" in report_result.output


def test_report_with_no_runs_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["report"])
    assert result.exit_code != 0


def test_identify_force_disables_tier0(fixtures_dir, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    shutil.copy(fixtures_dir / "clean_tagged.mp3", music_dir / "clean_tagged.mp3")

    result = runner.invoke(app, ["identify", str(music_dir), "--tiers", "", "--force"])
    assert result.exit_code == 0, result.output
    # With Tier 0 disabled and no Tier 1/2 clients configured, nothing can
    # accept -> everything lands in review, even an already-complete file.
    assert "REVIEW_UNMATCHED" in result.output
    assert "SKIPPED_COMPLETE" not in result.output
