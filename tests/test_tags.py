from __future__ import annotations

from mp3_autotag.tags import read_existing_tags


def test_clean_tagged(fixtures_dir):
    tags = read_existing_tags(str(fixtures_dir / "clean_tagged.mp3"))
    assert tags.title == "Test Track"
    assert tags.artist == "Test Artist"
    assert tags.album == "Test Album"
    assert tags.albumartist == "Test Artist"
    assert tags.track == "1/10"
    assert tags.disc == "1/1"
    assert tags.year == "2020"
    assert tags.genre == "Rock"
    assert tags.musicbrainz_track_id == "11111111-1111-1111-1111-111111111111"
    assert tags.is_minimally_complete() is True


def test_unicode_diacritics_round_trip(fixtures_dir):
    tags = read_existing_tags(str(fixtures_dir / "unicode_tagged.mp3"))
    assert tags.title == "Configuração é Assim"
    assert tags.artist == "Cão Ção"
    assert tags.album == "Canção Nações"
    for ch in "Ç ã õ é".split():
        assert ch in tags.title + tags.artist + tags.album


def test_untagged(fixtures_dir):
    tags = read_existing_tags(str(fixtures_dir / "untagged.mp3"))
    assert tags.title is None
    assert tags.is_minimally_complete() is False


def test_partial_tagged_not_minimally_complete(fixtures_dir):
    tags = read_existing_tags(str(fixtures_dir / "partial_tagged.mp3"))
    assert tags.title == "Partial Track"
    assert tags.artist == "Partial Artist"
    assert tags.album is None
    assert tags.is_minimally_complete() is False
