from __future__ import annotations

import pytest

from mp3_autotag.config import Config, ConfigError, load_config


def test_defaults_match_spec():
    cfg = Config()
    assert cfg.general.id3_version == "2.3"
    assert cfg.thresholds.tier1_min_score == 0.90
    assert cfg.thresholds.tier2_min_score == 88
    assert cfg.tiers.enabled == [0, 1, 2]
    assert cfg.tags.write_genre is False
    assert cfg.rename.enabled is False
    assert cfg.filename.noise_patterns  # non-empty defaults


def test_load_missing_path_is_defaults(tmp_path):
    missing = tmp_path / "nope.toml"
    with pytest.raises(ConfigError):
        load_config(missing)


def test_load_no_arg_no_file_is_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.general.db_path == "mp3-autotag.db"


def test_load_overrides(tmp_path):
    toml_path = tmp_path / "mp3-autotag.toml"
    toml_path.write_text(
        """
        [general]
        contact_email = "me@example.com"
        db_path = "custom.db"

        [thresholds]
        tier1_min_score = 0.95

        [tiers]
        enabled = [0, 1, 2, 3]
        """
    )
    cfg = load_config(toml_path)
    assert cfg.general.contact_email == "me@example.com"
    assert cfg.general.db_path == "custom.db"
    assert cfg.thresholds.tier1_min_score == 0.95
    assert cfg.tiers.enabled == [0, 1, 2, 3]
    # untouched sections keep defaults
    assert cfg.tags.write_genre is False


def test_unknown_section_rejected(tmp_path):
    toml_path = tmp_path / "mp3-autotag.toml"
    toml_path.write_text("[bogus]\nfoo = 1\n")
    with pytest.raises(ConfigError):
        load_config(toml_path)


def test_unknown_key_rejected(tmp_path):
    toml_path = tmp_path / "mp3-autotag.toml"
    toml_path.write_text("[general]\nfoo = 1\n")
    with pytest.raises(ConfigError):
        load_config(toml_path)


def test_invalid_id3_version_rejected(tmp_path):
    toml_path = tmp_path / "mp3-autotag.toml"
    toml_path.write_text('[general]\nid3_version = "9.9"\n')
    with pytest.raises(ConfigError):
        load_config(toml_path)


def test_secrets_come_from_env_not_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("ACOUSTID_API_KEY", "secret-123")
    toml_path = tmp_path / "mp3-autotag.toml"
    toml_path.write_text("[general]\ncontact_email = \"me@example.com\"\n")
    cfg = load_config(toml_path)
    assert cfg.acoustid_api_key == "secret-123"


def test_require_contact_email_raises_when_blank():
    cfg = Config()
    with pytest.raises(ConfigError):
        cfg.general.require_contact_email()
