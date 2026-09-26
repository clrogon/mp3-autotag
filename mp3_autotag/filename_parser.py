"""Filename parsing for Tier 2 (spec §6).

Handles the four documented patterns:
  - `Artist - Title`
  - `NN - Artist - Title`
  - `NN. Title` (artist taken from the parent folder)
  - `Artist_-_Title`

Plus two sensible fallbacks not spelled out verbatim in the spec but implied
by "site watermarks and trailing IDs" noise and by robustness: a lone
`NN - Title` (no artist segment) and any pattern where no artist could be
parsed both fall back to the parent folder name as artist, exactly as the
`NN. Title` rule already does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_TRACK_PREFIX_RE = re.compile(r"^\s*(\d{1,3})\s*([-.])\s*(.*)$")
_BRACKET_CLEANUP_RE = re.compile(r"[\[\(\{]\s*[\]\)\}]")
_EDGE_SEPARATOR_RE = re.compile(r"^[\s\-_.]+|[\s\-_.]+$")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class ParsedFilename:
    artist: str | None
    title: str
    track: int | None


def strip_noise(text: str, noise_patterns: list[str]) -> str:
    cleaned = text
    for pattern in noise_patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    # Noise removal can leave behind now-empty bracket pairs, e.g. "Song ()".
    cleaned = _BRACKET_CLEANUP_RE.sub(" ", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def _trim_edges(text: str) -> str:
    return _EDGE_SEPARATOR_RE.sub("", text).strip()


def parse_filename(path: Path, noise_patterns: list[str]) -> ParsedFilename:
    stem = path.stem.replace("_", " ")
    cleaned = strip_noise(stem, noise_patterns)

    track: int | None = None
    artist: str | None = None
    title: str

    match = _TRACK_PREFIX_RE.match(cleaned)
    if match:
        track = int(match.group(1))
        rest = match.group(3)
    else:
        rest = cleaned

    if " - " in rest:
        artist_part, title_part = rest.split(" - ", 1)
        artist = _trim_edges(artist_part) or None
        title = _trim_edges(title_part)
    else:
        title = _trim_edges(rest)

    if not artist:
        parent_name = path.parent.name
        artist = parent_name or None

    return ParsedFilename(artist=artist, title=title, track=track)
