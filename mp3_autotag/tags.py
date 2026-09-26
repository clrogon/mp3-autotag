"""Read existing ID3 tags. Frame mapping matches spec §8 (Picard-compatible)."""

from __future__ import annotations

from dataclasses import dataclass

from mutagen.id3 import ID3, ID3NoHeaderError

MUSICBRAINZ_TRACK_ID_DESC = "MusicBrainz Track Id"


@dataclass
class ExistingTags:
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    albumartist: str | None = None
    track: str | None = None
    disc: str | None = None
    year: str | None = None
    genre: str | None = None
    musicbrainz_track_id: str | None = None

    def is_minimally_complete(self) -> bool:
        """True when title, artist and album are all present (spec §6, Tier 0)."""
        return bool(self.title and self.artist and self.album)


def _first_text(id3: ID3, frame_id: str) -> str | None:
    frame = id3.get(frame_id)
    if frame is None or not getattr(frame, "text", None):
        return None
    value = str(frame.text[0]).strip()
    return value or None


def _txxx(id3: ID3, desc: str) -> str | None:
    frame = id3.get(f"TXXX:{desc}")
    if frame is None or not getattr(frame, "text", None):
        return None
    value = str(frame.text[0]).strip()
    return value or None


def read_existing_tags(file_path: str) -> ExistingTags:
    try:
        id3 = ID3(file_path)
    except ID3NoHeaderError:
        return ExistingTags()

    # TYER (v2.3) or TDRC (v2.4); prefer whichever is present.
    year = _first_text(id3, "TYER") or _first_text(id3, "TDRC")

    return ExistingTags(
        title=_first_text(id3, "TIT2"),
        artist=_first_text(id3, "TPE1"),
        album=_first_text(id3, "TALB"),
        albumartist=_first_text(id3, "TPE2"),
        track=_first_text(id3, "TRCK"),
        disc=_first_text(id3, "TPOS"),
        year=year,
        genre=_first_text(id3, "TCON"),
        musicbrainz_track_id=_txxx(id3, MUSICBRAINZ_TRACK_ID_DESC),
    )
