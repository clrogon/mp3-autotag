"""Generates the synthetic MP3 fixtures committed under tests/fixtures/.

Not a test itself — a reproducible build tool. Run with:
    python tests/fixtures/generate_fixtures.py

Fixtures are self-generated silent MPEG-1 Layer III streams (mono, 44.1kHz,
128kbps CBR, zero-filled payload) with ID3v2.3 tags applied via mutagen.
No copyrighted audio is used or required; mutagen only needs valid frame
headers to compute duration, not real encoded audio.
"""

from __future__ import annotations

from pathlib import Path

from mutagen.id3 import ID3, TALB, TCON, TIT2, TPE1, TPE2, TPOS, TRCK, TXXX, TYER

FIXTURES_DIR = Path(__file__).parent

SAMPLE_RATE = 44100
BITRATE_KBPS = 128
FRAME_SIZE = (144 * BITRATE_KBPS * 1000) // SAMPLE_RATE  # 417, no padding
HEADER = bytes((0xFF, 0xFB, 0x90, 0xC0))  # MPEG1 Layer III, 128kbps, 44100Hz, mono, no CRC
FRAME = HEADER + bytes(FRAME_SIZE - len(HEADER))


def write_silent_mp3(path: Path, num_frames: int = 80) -> None:
    path.write_bytes(FRAME * num_frames)


def tag(path: Path, **frames) -> None:
    try:
        id3 = ID3(path)
    except Exception:
        id3 = ID3()
    for frame in frames.values():
        id3.add(frame)
    id3.save(path, v2_version=3)


def main() -> None:
    FIXTURES_DIR.mkdir(exist_ok=True)

    # 1. Fully tagged, ASCII only — Tier 0 should skip this one.
    write_silent_mp3(FIXTURES_DIR / "clean_tagged.mp3")
    tag(
        FIXTURES_DIR / "clean_tagged.mp3",
        title=TIT2(encoding=0, text=["Test Track"]),
        artist=TPE1(encoding=0, text=["Test Artist"]),
        album=TALB(encoding=0, text=["Test Album"]),
        albumartist=TPE2(encoding=0, text=["Test Artist"]),
        track=TRCK(encoding=0, text=["1/10"]),
        disc=TPOS(encoding=0, text=["1/1"]),
        year=TYER(encoding=0, text=["2020"]),
        genre=TCON(encoding=0, text=["Rock"]),
        mbid=TXXX(encoding=0, desc="MusicBrainz Track Id", text=["11111111-1111-1111-1111-111111111111"]),
    )

    # 2. Portuguese diacritics, forced UTF-16 (spec §8: "Ç, ã, õ, é must survive").
    write_silent_mp3(FIXTURES_DIR / "unicode_tagged.mp3")
    tag(
        FIXTURES_DIR / "unicode_tagged.mp3",
        title=TIT2(encoding=1, text=["Configuração é Assim"]),
        artist=TPE1(encoding=1, text=["Cão Ção"]),
        album=TALB(encoding=1, text=["Canção Nações"]),
    )

    # 3. No ID3 tag at all.
    write_silent_mp3(FIXTURES_DIR / "untagged.mp3")

    # 4. Partial tags (title + artist, no album) — Tier 0 must NOT skip this one.
    write_silent_mp3(FIXTURES_DIR / "partial_tagged.mp3")
    tag(
        FIXTURES_DIR / "partial_tagged.mp3",
        title=TIT2(encoding=0, text=["Partial Track"]),
        artist=TPE1(encoding=0, text=["Partial Artist"]),
    )

    # 5. Untagged, noisy filename — for Tier 2 filename-parser tests (Phase 2).
    write_silent_mp3(FIXTURES_DIR / "03 - Artista Teste - Faixa Config (Official Video) [320kbps].mp3")

    print("Fixtures written to", FIXTURES_DIR)


if __name__ == "__main__":
    main()
