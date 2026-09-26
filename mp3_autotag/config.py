"""Config loading for mp3-autotag.

Reads `mp3-autotag.toml` (stdlib tomllib) and overlays it on the defaults
from spec §9. Secrets (API keys) are never read from the config file —
only from environment variables, per spec §7.9.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_FILENAME = "mp3-autotag.toml"


class ConfigError(Exception):
    """Raised for invalid or unusable configuration."""


@dataclass
class GeneralConfig:
    id3_version: str = "2.3"
    contact_email: str = ""
    fpcalc_path: str = ""
    db_path: str = "mp3-autotag.db"
    backup_dir: str = "backups"

    def __post_init__(self) -> None:
        if self.id3_version not in ("2.3", "2.4"):
            raise ConfigError(
                f"general.id3_version must be '2.3' or '2.4', got {self.id3_version!r}"
            )

    def require_contact_email(self) -> str:
        if not self.contact_email:
            raise ConfigError(
                "general.contact_email is required for the MusicBrainz User-Agent "
                "(MusicBrainz rejects requests without a descriptive contact). "
                "Set it in mp3-autotag.toml."
            )
        return self.contact_email


@dataclass
class ThresholdsConfig:
    tier1_min_score: float = 0.90
    tier2_min_score: float = 88
    tier2_min_margin: float = 5
    duration_tolerance_s: float = 3
    conflict_artist_similarity: float = 50


@dataclass
class TiersConfig:
    enabled: list[int] = field(default_factory=lambda: [0, 1, 2])
    tier3_provider: str = "audd"
    tier3_max_calls_per_run: int = 50

    def __post_init__(self) -> None:
        if self.tier3_provider not in ("audd", "acrcloud"):
            raise ConfigError(
                f"tiers.tier3_provider must be 'audd' or 'acrcloud', got {self.tier3_provider!r}"
            )


@dataclass
class TagsConfig:
    write_genre: bool = False
    replace_cover: bool = False
    cover_size: int = 500
    strip_id3v1: bool = False


@dataclass
class RenameConfig:
    enabled: bool = False
    template: str = "{albumartist}/{album}/{track:02d} - {title}.mp3"


@dataclass
class FilenameConfig:
    noise_patterns: list[str] = field(
        default_factory=lambda: [
            r"\(official (music )?video\)",
            r"\[\d{3}\s?kbps\]",
            r"\(audio\)",
            r"\blyrics?\b",
        ]
    )


@dataclass
class Config:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    thresholds: ThresholdsConfig = field(default_factory=ThresholdsConfig)
    tiers: TiersConfig = field(default_factory=TiersConfig)
    tags: TagsConfig = field(default_factory=TagsConfig)
    rename: RenameConfig = field(default_factory=RenameConfig)
    filename: FilenameConfig = field(default_factory=FilenameConfig)

    # Secrets: env vars only, never persisted in the dataclass-from-toml path.
    acoustid_api_key: str | None = field(default=None, repr=False)
    audd_api_token: str | None = field(default=None, repr=False)
    acrcloud_access_key: str | None = field(default=None, repr=False)
    acrcloud_access_secret: str | None = field(default=None, repr=False)
    acrcloud_host: str | None = field(default=None, repr=False)


_SECTION_TYPES = {
    "general": GeneralConfig,
    "thresholds": ThresholdsConfig,
    "tiers": TiersConfig,
    "tags": TagsConfig,
    "rename": RenameConfig,
    "filename": FilenameConfig,
}


def _build_section(section_cls, raw: dict) -> object:
    valid_fields = {f for f in section_cls.__dataclass_fields__}
    unknown = set(raw) - valid_fields
    if unknown:
        raise ConfigError(
            f"unknown key(s) {sorted(unknown)} in [{section_cls.__name__}]"
        )
    return section_cls(**raw)


def load_config(path: str | Path | None = None) -> Config:
    """Load config from `path` (default: ./mp3-autotag.toml if present).

    Missing file -> pure defaults (not an error; `scan`/`identify` don't need
    a config file to exist). Secrets always come from the environment.
    """
    raw: dict = {}
    if path is not None:
        config_path = Path(path)
        if not config_path.is_file():
            raise ConfigError(f"config file not found: {config_path}")
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    else:
        default_path = Path(DEFAULT_CONFIG_FILENAME)
        if default_path.is_file():
            raw = tomllib.loads(default_path.read_text(encoding="utf-8"))

    unknown_sections = set(raw) - set(_SECTION_TYPES)
    if unknown_sections:
        raise ConfigError(f"unknown config section(s): {sorted(unknown_sections)}")

    kwargs = {
        name: _build_section(cls, raw.get(name, {}))
        for name, cls in _SECTION_TYPES.items()
    }

    return Config(
        **kwargs,
        acoustid_api_key=os.environ.get("ACOUSTID_API_KEY"),
        audd_api_token=os.environ.get("AUDD_API_TOKEN"),
        acrcloud_access_key=os.environ.get("ACRCLOUD_ACCESS_KEY"),
        acrcloud_access_secret=os.environ.get("ACRCLOUD_ACCESS_SECRET"),
        acrcloud_host=os.environ.get("ACRCLOUD_HOST"),
    )
