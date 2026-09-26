"""Atomic ID3 tag writing (spec §7.5, §7.6, §8).

Only fields the accepted candidate actually provides get written; nothing
lifted from the candidate (track/disc/genre/albumartist/cover art) that
Tier 1/2 don't currently source is written here — per spec §8, "keep
existing fields that the match does not provide; never blank a field",
the correct behavior for an unsupplied field is to leave it alone, not
invent a value. Cover art (Cover Art Archive) and release-based track/disc
numbers need data this pipeline doesn't fetch yet (a release id, and a
recording's position within a release's medium) — out of scope for this
phase, not silently dropped.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from mutagen.id3 import ID3, ID3NoHeaderError, TALB, TDRC, TIT2, TPE1, TXXX, TYER
from mutagen.mp3 import MP3, HeaderNotFoundError

from mp3_autotag.config import Config
from mp3_autotag.tags import ACOUSTID_ID_DESC, MUSICBRAINZ_TRACK_ID_DESC, ExistingTags


class TagWriteError(Exception):
    """Raised when a tag write cannot be safely completed. The original
    file is left completely untouched whenever this is raised."""


@dataclass
class TagChange:
    field: str
    old_value: str | None
    new_value: str


_FIELD_ORDER = ["title", "artist", "album", "year", "musicbrainz_track_id", "acoustid_id"]
_YEAR_FRAME_ID_FOR_VERSION = {"2.3": "TYER", "2.4": "TDRC"}


def compute_changes(existing: ExistingTags, new_values: dict[str, str | None]) -> list[TagChange]:
    changes = []
    for field_name in _FIELD_ORDER:
        new_value = new_values.get(field_name)
        if new_value is None:
            continue
        old_value = getattr(existing, field_name)
        if (old_value or None) != (str(new_value) or None):
            changes.append(TagChange(field=field_name, old_value=old_value, new_value=str(new_value)))
    return changes


def _is_ascii(text: str) -> bool:
    try:
        text.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _encoding_for(text: str) -> int:
    # 0 = Latin-1, 1 = UTF-16 — both valid for ID3v2.3 (UTF-8 is 2.4-only).
    # Diacritics (spec: Ç, ã, õ, é) need UTF-16; plain ASCII stays Latin-1.
    return 0 if _is_ascii(text) else 1


def audio_stream_offset(path: Path) -> int:
    try:
        return MP3(path).info.frame_offset
    except HeaderNotFoundError:
        return 0


def audio_stream_hash(path: Path) -> str:
    offset = audio_stream_offset(path)
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        fh.seek(offset)
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _apply_changes_to_id3(id3: ID3, changes: list[TagChange], id3_version: str) -> None:
    for change in changes:
        value = change.new_value
        enc = _encoding_for(value)

        if change.field == "title":
            id3.setall("TIT2", [TIT2(encoding=enc, text=[value])])
        elif change.field == "artist":
            id3.setall("TPE1", [TPE1(encoding=enc, text=[value])])
        elif change.field == "album":
            id3.setall("TALB", [TALB(encoding=enc, text=[value])])
        elif change.field == "year":
            frame_id = _YEAR_FRAME_ID_FOR_VERSION[id3_version]
            id3.delall("TYER")
            id3.delall("TDRC")
            frame_cls = TYER if frame_id == "TYER" else TDRC
            id3.setall(frame_id, [frame_cls(encoding=enc, text=[value])])
        elif change.field == "musicbrainz_track_id":
            id3.delall(f"TXXX:{MUSICBRAINZ_TRACK_ID_DESC}")
            id3.setall(
                f"TXXX:{MUSICBRAINZ_TRACK_ID_DESC}",
                [TXXX(encoding=enc, desc=MUSICBRAINZ_TRACK_ID_DESC, text=[value])],
            )
        elif change.field == "acoustid_id":
            id3.delall(f"TXXX:{ACOUSTID_ID_DESC}")
            id3.setall(
                f"TXXX:{ACOUSTID_ID_DESC}", [TXXX(encoding=enc, desc=ACOUSTID_ID_DESC, text=[value])]
            )
        else:
            raise TagWriteError(f"unhandled field: {change.field}")


def write_tags_atomic(file_path: Path, changes: list[TagChange], config: Config) -> None:
    """Write `changes` to `file_path` (spec §7.5): stage on a temp copy,
    verify it re-reads cleanly *and* the audio stream is byte-identical
    (spec §7.6), only then replace the original. Raises TagWriteError and
    leaves the original completely untouched on any failure — the caller
    is responsible for having made a separate run-level backup first
    (spec §7.2); this function's own temp-file staging is what keeps a
    failed write from ever touching the real file at all.
    """
    if not changes:
        return

    before_audio_hash = audio_stream_hash(file_path)
    tmp_path = file_path.with_name(file_path.name + ".mp3-autotag-tmp")

    try:
        shutil.copy2(file_path, tmp_path)

        try:
            id3 = ID3(tmp_path)
        except ID3NoHeaderError:
            id3 = ID3()

        _apply_changes_to_id3(id3, changes, config.general.id3_version)

        v2_version = 3 if config.general.id3_version == "2.3" else 4
        v1_option = 0 if config.tags.strip_id3v1 else 1
        id3.save(tmp_path, v1=v1_option, v2_version=v2_version)

        try:
            MP3(tmp_path)
        except HeaderNotFoundError as exc:
            raise TagWriteError(f"written file does not re-read cleanly: {exc}") from exc

        after_audio_hash = audio_stream_hash(tmp_path)
        if after_audio_hash != before_audio_hash:
            raise TagWriteError("audio stream hash changed after tag write — original left untouched")

        tmp_path.replace(file_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
