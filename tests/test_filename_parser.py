from __future__ import annotations

from pathlib import Path

import pytest

from mp3_autotag.config import FilenameConfig
from mp3_autotag.filename_parser import parse_filename

NOISE = FilenameConfig().noise_patterns

# (filename, parent_folder, expected_artist, expected_title, expected_track)
CASES = [
    # 1. Artist - Title
    ("Artist - Title.mp3", "Music", "Artist", "Title", None),
    ("Anselmo Ralph - Kizua.mp3", "Music", "Anselmo Ralph", "Kizua", None),
    # 2. NN - Artist - Title
    ("05 - Artist - Title.mp3", "Music", "Artist", "Title", 5),
    ("12 - C4 Pedro - Bo Tem Alguem.mp3", "Music", "C4 Pedro", "Bo Tem Alguem", 12),
    ("003 - Fally Ipupa - Chaise Electrique.mp3", "Music", "Fally Ipupa", "Chaise Electrique", 3),
    # 3. NN. Title (artist from parent folder)
    ("03. Kizua.mp3", "Anselmo Ralph", "Anselmo Ralph", "Kizua", 3),
    ("7. Reencontro.mp3", "Yola Semedo", "Yola Semedo", "Reencontro", 7),
    # 4. Artist_-_Title (underscores)
    ("Yola Semedo_-_Reencontro.mp3", "Music", "Yola Semedo", "Reencontro", None),
    ("C4_Pedro_-_Bo_Tem_Alguem.mp3", "Music", "C4 Pedro", "Bo Tem Alguem", None),
    # Noise: official video / music video, mixed case
    ("Anselmo Ralph - Kizua (Official Video).mp3", "Music", "Anselmo Ralph", "Kizua", None),
    ("Anselmo Ralph - Kizua (OFFICIAL MUSIC VIDEO).mp3", "Music", "Anselmo Ralph", "Kizua", None),
    # Noise: bitrate tag
    ("C4 Pedro - Bo Tem Alguem [320kbps].mp3", "Music", "C4 Pedro", "Bo Tem Alguem", None),
    ("C4 Pedro - Bo Tem Alguem [320 kbps].mp3", "Music", "C4 Pedro", "Bo Tem Alguem", None),
    # Noise: (Audio)
    ("Fally Ipupa - Chaise Electrique (Audio).mp3", "Music", "Fally Ipupa", "Chaise Electrique", None),
    # Noise: lyrics / Lyrics
    ("Fally Ipupa - Chaise Electrique (Lyrics).mp3", "Music", "Fally Ipupa", "Chaise Electrique", None),
    ("Fally Ipupa - Chaise Electrique lyrics.mp3", "Music", "Fally Ipupa", "Chaise Electrique", None),
    # Stacked noise tags
    (
        "05 - Anselmo Ralph - Kizua (Official Video) [320kbps].mp3",
        "Music",
        "Anselmo Ralph",
        "Kizua",
        5,
    ),
    # Lusophone diacritics preserved through noise stripping
    ("05 - Cef - Já Não És Menina (Official Music Video).mp3", "Music", "Cef", "Já Não És Menina", 5),
    ("Yola Semedo - Canção Para Ti (Audio).mp3", "Music", "Yola Semedo", "Canção Para Ti", None),
    ("Anselmo Ralph - Não Vou Resistir [320kbps].mp3", "Music", "Anselmo Ralph", "Não Vou Resistir", None),
    # Extra whitespace around separators
    ("Artist   -   Title.mp3", "Music", "Artist", "Title", None),
    # NN - Title with no artist segment: falls back to parent folder
    ("04 - Reencontro.mp3", "Yola Semedo", "Yola Semedo", "Reencontro", 4),
    # Title itself containing a dash: split happens at the first " - "
    ("Artist - Title - Remix.mp3", "Music", "Artist", "Title - Remix", None),
    # Case-insensitive noise pattern matching
    ("Artist - Title (official video).mp3", "Music", "Artist", "Title", None),
]


@pytest.mark.parametrize("filename,parent,exp_artist,exp_title,exp_track", CASES)
def test_parse_filename(tmp_path, filename, parent, exp_artist, exp_title, exp_track):
    folder = tmp_path / parent
    folder.mkdir(parents=True, exist_ok=True)
    file_path = folder / filename

    result = parse_filename(file_path, NOISE)

    assert result.artist == exp_artist
    assert result.title == exp_title
    assert result.track == exp_track


def test_at_least_20_cases_declared():
    assert len(CASES) >= 20
