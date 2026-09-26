# mp3-autotag

A local Python CLI that identifies MP3 files and writes correct, consistent
ID3 metadata and cover art, using a tiered pipeline (AcoustID fingerprint →
MusicBrainz filename search → optional commercial recognition → manual
review). Safe by default: dry-run, backups, a change journal, and rollback.

Full design: see `SPEC.md`.

## Status

Build phases (see `SPEC.md` §10):

- [x] Phase 1 — project skeleton, config loader, SQLite schema, `scan`
- [x] Phase 2 — filename parser + Tier 2
- [ ] Phase 3 — Tier 1 (AcoustID) fingerprinting
- [ ] Phase 4 — candidate selection, conflict rule, `identify`/`report`
- [ ] Phase 5 — `apply`, backups, journal, `rollback`
- [ ] Phase 6 — review CSV export/import
- [ ] Phase 7 — Tier 3 commercial recognition (optional)
- [ ] Phase 8 — full setup README

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

`fpcalc` (from [Chromaprint](https://acoustid.org/chromaprint)) is required
for fingerprinting; install it and ensure it's on `PATH`, or set
`general.fpcalc_path` in `mp3-autotag.toml`. Without it, `scan` still works
but skips fingerprinting.

## Usage so far

```bash
mp3-autotag scan <path> [--limit N]
```

Other commands (`identify`, `review`, `apply`, `rollback`, `report`) are
wired into the CLI but not implemented yet — each prints which build phase
it belongs to.

## Tests

```bash
pytest
```

Fixtures under `tests/fixtures/` are synthetic, self-generated silent MP3s
(no copyrighted audio) — see `tests/fixtures/generate_fixtures.py`.

## Config

Copy `mp3-autotag.example.toml` to `mp3-autotag.toml` and adjust. Secrets
(`ACOUSTID_API_KEY`, etc.) are read from environment variables only, never
from the config file.
