from __future__ import annotations

import shutil

import pytest

from mp3_autotag.config import Config
from mp3_autotag.tagger import (
    TagWriteError,
    audio_stream_hash,
    compute_changes,
    write_tags_atomic,
)
from mp3_autotag.tags import ExistingTags, read_existing_tags


def _copy(fixtures_dir, tmp_path, name="untagged.mp3"):
    dest = tmp_path / name
    shutil.copy(fixtures_dir / name, dest)
    return dest


def test_compute_changes_only_includes_provided_fields():
    existing = ExistingTags(title="Old Title", artist="Old Artist", album="Old Album")
    changes = compute_changes(existing, {"title": "New Title", "artist": None, "album": None})
    assert len(changes) == 1
    assert changes[0].field == "title"
    assert changes[0].old_value == "Old Title"
    assert changes[0].new_value == "New Title"


def test_compute_changes_skips_identical_values():
    existing = ExistingTags(title="Same", artist="Artist")
    changes = compute_changes(existing, {"title": "Same", "artist": "Artist"})
    assert changes == []


def test_compute_changes_empty_when_nothing_provided():
    existing = ExistingTags(title="T")
    assert compute_changes(existing, {}) == []


def test_write_tags_atomic_unicode_round_trip(fixtures_dir, tmp_path):
    target = _copy(fixtures_dir, tmp_path)
    existing = read_existing_tags(str(target))
    changes = compute_changes(
        existing,
        {"title": "Configuração é Assim", "artist": "Cão Ção", "album": "Canção Nações"},
    )
    write_tags_atomic(target, changes, Config())

    result = read_existing_tags(str(target))
    assert result.title == "Configuração é Assim"
    assert result.artist == "Cão Ção"
    assert result.album == "Canção Nações"


def test_write_tags_atomic_uses_id3v23_by_default(fixtures_dir, tmp_path):
    target = _copy(fixtures_dir, tmp_path)
    existing = read_existing_tags(str(target))
    changes = compute_changes(existing, {"title": "T", "year": "2020"})
    write_tags_atomic(target, changes, Config())

    header = target.read_bytes()[:10]
    assert header[:3] == b"ID3"
    assert header[3] == 3  # ID3v2.3


def test_write_tags_atomic_v24_uses_tdrc_for_year(fixtures_dir, tmp_path):
    target = _copy(fixtures_dir, tmp_path)
    cfg = Config()
    cfg.general.id3_version = "2.4"
    existing = read_existing_tags(str(target))
    changes = compute_changes(existing, {"year": "2020"})
    write_tags_atomic(target, changes, cfg)

    header = target.read_bytes()[:10]
    assert header[3] == 4  # ID3v2.4

    from mutagen.id3 import ID3

    id3 = ID3(target)
    assert "TDRC" in id3
    assert "TYER" not in id3


def test_write_tags_atomic_never_blanks_untouched_fields(fixtures_dir, tmp_path):
    target = _copy(fixtures_dir, tmp_path, "clean_tagged.mp3")
    existing = read_existing_tags(str(target))
    changes = compute_changes(existing, {"title": "Only Title Changes"})
    write_tags_atomic(target, changes, Config())

    result = read_existing_tags(str(target))
    assert result.title == "Only Title Changes"
    assert result.artist == existing.artist
    assert result.album == existing.album
    assert result.albumartist == existing.albumartist
    assert result.track == existing.track
    assert result.disc == existing.disc
    assert result.genre == existing.genre
    assert result.musicbrainz_track_id == existing.musicbrainz_track_id


def test_write_tags_atomic_audio_stream_hash_unchanged(fixtures_dir, tmp_path):
    target = _copy(fixtures_dir, tmp_path, "clean_tagged.mp3")
    before_hash = audio_stream_hash(target)

    existing = read_existing_tags(str(target))
    changes = compute_changes(
        existing, {"title": "New Title", "artist": "New Artist", "album": "New Album"}
    )
    write_tags_atomic(target, changes, Config())

    after_hash = audio_stream_hash(target)
    assert after_hash == before_hash


def test_write_tags_atomic_no_changes_is_noop(fixtures_dir, tmp_path):
    target = _copy(fixtures_dir, tmp_path, "clean_tagged.mp3")
    before_bytes = target.read_bytes()
    write_tags_atomic(target, [], Config())
    assert target.read_bytes() == before_bytes


def test_write_tags_atomic_leaves_original_untouched_on_audio_hash_mismatch(
    fixtures_dir, tmp_path, monkeypatch
):
    target = _copy(fixtures_dir, tmp_path, "clean_tagged.mp3")
    original_bytes = target.read_bytes()

    import mp3_autotag.tagger as tagger_mod

    calls = {"n": 0}
    real_hash = tagger_mod.audio_stream_hash

    def fake_hash(path):
        calls["n"] += 1
        if calls["n"] == 1:
            return "before-hash"
        return "different-hash"  # simulates corruption on the second (post-write) check

    monkeypatch.setattr(tagger_mod, "audio_stream_hash", fake_hash)

    existing = read_existing_tags(str(target))
    changes = compute_changes(existing, {"title": "New Title"})

    with pytest.raises(TagWriteError):
        write_tags_atomic(target, changes, Config())

    assert target.read_bytes() == original_bytes  # original completely untouched
    assert not (tmp_path / "clean_tagged.mp3.mp3-autotag-tmp").exists()  # temp file cleaned up

    monkeypatch.setattr(tagger_mod, "audio_stream_hash", real_hash)
