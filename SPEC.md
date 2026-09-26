# mp3-autotag — Build Spec for Claude Code

## 0. Instructions to Claude Code

- Read this whole spec before writing code. Propose a short implementation plan first and wait for approval.
- Build in the phases in §10. Finish each phase with passing tests before starting the next.
- Never modify real audio files during development. Use the fixtures in `tests/fixtures/` only.
- If a requirement here is ambiguous or conflicts with an API's actual behaviour, stop and ask. Do not guess.
- Do not invent API endpoints or response fields. Verify them against the official docs listed in §12.

---

## 1. Goal

Build a local Python CLI that identifies MP3 files and writes correct, consistent ID3 metadata and cover art.

It uses a tiered pipeline:

1. Audio fingerprinting (AcoustID / MusicBrainz) as the primary method.
2. Filename parsing plus a MusicBrainz text search as the fallback.
3. An optional commercial recognition API (AudD or ACRCloud) for what is still unmatched.
4. A manual review queue for everything that stays uncertain.

The tool must be safe by default:

- It runs as a dry-run unless told otherwise.
- It backs up files before writing.
- It keeps a journal of every change.
- It supports rollback.

---

## 2. Assumptions (adjustable)

| Item | Default |
|---|---|
| OS | Windows 10/11 (must also run on macOS/Linux) |
| Python | 3.11+ |
| Library size | 1,000–10,000 MP3 files |
| Use | Personal, non-commercial (required by AcoustID free-tier terms) |
| Catalogue | Mixed international, Angolan and Lusophone music. Expect lower MusicBrainz/AcoustID coverage for regional tracks. |
| Tag version | ID3v2.3, for Windows Explorer and car-stereo compatibility. Configurable to v2.4. |

---

## 3. Scope

**In scope**
- `.mp3` files only.
- Recursive folder scan.
- Tags written:
  - title
  - artist
  - album
  - album artist
  - track number/total
  - disc number
  - year
  - genre (optional)
  - MusicBrainz IDs
  - embedded front cover
- Optional file renaming by template, off by default.

**Out of scope for v1**
- FLAC, M4A and other formats. Design the tag layer so they can be added later.
- GUI.
- Lyrics.
- Duplicate detection. Only log likely duplicates when two files resolve to the same recording ID.

---

## 4. Tech stack

| Purpose | Package / tool |
|---|---|
| Tag read/write | `mutagen` |
| Fingerprinting | `pyacoustid` plus the `fpcalc` binary from Chromaprint. Path configurable; must be on PATH or set in config. |
| MusicBrainz lookups | `musicbrainzngs` |
| Fuzzy matching | `rapidfuzz` |
| Cover art | Cover Art Archive via HTTP (`httpx` or `requests`) |
| CLI | `typer` |
| Console output | `rich` |
| Cache and journal | `sqlite3` (stdlib) |
| Config | `tomllib` (stdlib) plus environment variables for secrets |
| Tests | `pytest` |

Packaging: `pyproject.toml`, installable with `pip install -e .`, entry point `mp3-autotag`.

---

## 5. CLI commands

```
mp3-autotag scan     <path>                  # inventory files, read existing tags, compute fingerprints (cached)
mp3-autotag identify <path> [--tiers 1,2,3]  # run the pipeline, store candidates in the DB; never writes to files
mp3-autotag review                           # export review queue to CSV; import decisions back with --import <csv>
mp3-autotag apply    <path> [--write]        # dry-run by default; --write is required to modify files
mp3-autotag rollback <run-id>                # restore files from backup for a given apply run
mp3-autotag report   [<run-id>]              # summary: matched per tier, low-confidence, failures
```

Global flags:
- `--config <file>`
- `--verbose`
- `--limit N`, to process only the first N files for testing

---

## 6. Pipeline logic

For each file, stop at the first tier that yields an **accepted** match.

### Tier 0 — Skip check
- Skip the file if it already has title, artist and album, and either:
  - it already has a MusicBrainz recording ID, or
  - the existing tags fuzzy-match the parsed filename at ≥ 90.
- Mark the result `SKIPPED_COMPLETE`.
- `--force` disables this tier.

### Tier 1 — Fingerprint (AcoustID)
- Run `fpcalc` and cache the fingerprint and duration by file hash.
- Look up AcoustID and request recording metadata.
- **Accept** when both hold:
  - the AcoustID score is ≥ `tier1_min_score` (default 0.90), and
  - the candidate recording length is within ±`duration_tolerance_s` (default 3 s) of the file's duration.
- If the recording appears on several releases, choose one in this order:
  1. The release whose album or year best matches the existing tags or the filename.
  2. Otherwise, an official studio album over a compilation.
  3. Otherwise, the earliest release.
- Store every candidate, not only the winner.

### Tier 2 — Filename search
- Parse the filename. Handle these patterns and noise:
  - `Artist - Title`
  - `NN - Artist - Title`
  - `NN. Title` (artist taken from the parent folder)
  - `Artist_-_Title`
  - Strip noise such as `(Official Video)`, `[320kbps]`, `(Audio)`, `lyrics`, site watermarks and trailing IDs.
  - Put the noise patterns in config as a regex list.
- Search MusicBrainz recordings by artist and title.
- Score each candidate with `rapidfuzz` (token_set_ratio) on both artist and title.
- **Accept** when all hold:
  - the combined score is ≥ `tier2_min_score` (default 88),
  - the duration is within tolerance, when available, and
  - the lead over the second-best candidate is ≥ 5 points.

### Tier 3 — Commercial recognition (optional, off by default)
- Enable in config and provide an API key through an environment variable (`AUDD_API_TOKEN` or the ACRCloud credentials).
- Send a 15-second clip, taken from about 30 % into the track, not the intro.
- Accept at the provider's confidence threshold, which is configurable.
- Map the result back to MusicBrainz when possible.
- Log each call's cost, and respect `tier3_max_calls_per_run` (default 50) to cap spend.

### Tier 4 — Manual review
- Everything not accepted goes here with the top 3 candidates.
- The CSV columns are:
  - file path
  - current tags
  - candidate 1–3 (artist, title, album, year, source, score, MBID)
  - `decision`, one of `1`, `2`, `3`, `skip` or `manual`
  - `manual_*` override columns
- `review --import` applies the decisions to the DB only. Files are changed by `apply`.

### Conflict rule
If Tier 1 and the Tier 2 filename parse disagree strongly (artist similarity < 50), do not auto-accept. Send the file to review with both candidates. Either the fingerprint is wrong or the file is mislabelled, and a human must decide.

---

## 7. Safety and operations (non-negotiable)

1. **Dry-run default.** `apply` without `--write` prints a diff table per file (field, old value, new value) and writes nothing.
2. **Backup before write.** Copy each file to `backups/<run-id>/<relative-path>` before modifying it. Abort the file if the backup fails.
3. **Journal.** SQLite table `changes` with columns:
   - run_id
   - file_path
   - file_hash_before
   - file_hash_after
   - field
   - old_value
   - new_value
   - source_tier
   - timestamp
4. **Rollback.** `rollback <run-id>` restores from backup and verifies the hash against `file_hash_before`.
5. **Atomic writes.** Write tags to a temporary copy, verify it re-reads cleanly with mutagen, then replace the original.
6. **Audio stream untouched.** Only the ID3 frames change. After the write, a test must confirm that the audio frames' hash is unchanged.
7. **Rate limits.**
   - MusicBrainz: at most 1 request per second, with a descriptive User-Agent (`mp3-autotag/<version> ( <contact-email> )`), as MusicBrainz requires.
   - AcoustID: at most 3 requests per second.
   - Retry with exponential backoff on 503 and 429 responses.
8. **Cache.** Cache fingerprints and API responses in SQLite, keyed by file hash and query, so that re-runs cost no API calls.
9. **Secrets.** API keys only from environment variables or a `.env` file listed in `.gitignore`. Never log keys.
10. **Resumable.** An interrupted run continues from where it stopped (state lives in the DB).
11. **Logging.** Rotating log file plus a `rich` console summary.

---

## 8. Tag-writing rules

- Default ID3v2.3, with UTF-16 encoding for non-ASCII text. Portuguese diacritics must survive; test with `Ç`, `ã`, `õ` and `é`.
- Fields written:

  | Field | ID3 frame |
  |---|---|
  | title | `TIT2` |
  | artist | `TPE1` |
  | album | `TALB` |
  | album artist | `TPE2` |
  | track number | `TRCK` (`n/total`) |
  | disc number | `TPOS` |
  | year | `TYER` (v2.3) or `TDRC` (v2.4) |
  | genre | `TCON` (only if `write_genre = true`) |
  | MusicBrainz IDs | `TXXX:MusicBrainz Track Id`, `TXXX:MusicBrainz Album Id`, `TXXX:MusicBrainz Artist Id` |
  | AcoustID | `TXXX:Acoustid Id` |
  | cover art | `APIC` |

- The MusicBrainz and AcoustID frame names must match Picard's, so Picard and beets can read them.
- Cover art:
  - Embed the front cover from the Cover Art Archive (500 px thumbnail, configurable) as `APIC` type 3.
  - Replace an existing cover only if `replace_cover = true`.
- Remove ID3v1 tags only if `strip_id3v1 = true` (default false).
- Keep existing fields that the match does not provide. Never blank a field.
- Optional rename: when `rename.enabled = true`, apply `rename.template` (default `{albumartist}/{album}/{track:02d} - {title}.mp3`).
  - Sanitise names for Windows by removing reserved characters and trailing dots or spaces.
  - Rename only with `--write`, and journal the old path.

---

## 9. Config file (`mp3-autotag.toml`)

```toml
[general]
id3_version = "2.3"
contact_email = "you@example.com"   # required for MusicBrainz User-Agent
fpcalc_path = ""                     # empty = find on PATH
db_path = "mp3-autotag.db"
backup_dir = "backups"

[thresholds]
tier1_min_score = 0.90
tier2_min_score = 88
tier2_min_margin = 5
duration_tolerance_s = 3
conflict_artist_similarity = 50

[tiers]
enabled = [0, 1, 2]                  # add 3 to enable commercial recognition
tier3_provider = "audd"              # "audd" | "acrcloud"
tier3_max_calls_per_run = 50

[tags]
write_genre = false
replace_cover = false
cover_size = 500
strip_id3v1 = false

[rename]
enabled = false
template = "{albumartist}/{album}/{track:02d} - {title}.mp3"

[filename]
noise_patterns = [
  '\(official (music )?video\)',
  '\[\d{3}\s?kbps\]',
  '\(audio\)',
  '\blyrics?\b',
]
```

API key (`ACOUSTID_API_KEY`, required) and optional provider keys come from environment variables.

---

## 10. Build phases

| Phase | Deliverable | Done when |
|---|---|---|
| 1 | Project skeleton, config loader, SQLite schema, `scan` command | `scan` inventories fixtures and reads existing tags |
| 2 | Filename parser plus Tier 2 | Parser unit tests pass on at least 20 filename patterns, noisy and Lusophone names included |
| 3 | Tier 1 fingerprinting with cache and rate limiting | Fixture file identified; second run makes zero API calls |
| 4 | Candidate selection, conflict rule, `identify` and `report` | Each tier accepts or rejects correctly in tests with mocked API responses |
| 5 | `apply` (dry-run and write), backups, journal, `rollback` | Write → rollback returns a byte-identical file; audio-stream hash unchanged |
| 6 | Review CSV export/import | Round-trip test passes |
| 7 | Tier 3 provider adapter (optional) | Works behind a feature flag; spend cap enforced |
| 8 | README with setup (fpcalc install, API key, first run on 50 files) | A new user can run it end to end |

---

## 11. Testing requirements

- Tests use mocked HTTP. No live API calls in CI. Keep an optional `--live` marker for manual runs.
- Fixtures are 3–5 short, legally redistributable MP3s: public-domain or CC0 audio, or generated tones for tag-only tests.
- Required test cases:
  - unicode and diacritics round-trip
  - ID3v2.3 compliance
  - audio-stream hash unchanged after write
  - rollback restores byte-identical files
  - dry-run writes nothing (file mtime and hash unchanged)
  - rate limiter enforces its limits
  - conflict rule routes the file to review
  - interrupted run resumes

---

## 12. Reference docs (verify before implementing)

- AcoustID web service: https://acoustid.org/webservice
- Chromaprint / fpcalc: https://acoustid.org/chromaprint
- MusicBrainz API and rate limiting: https://musicbrainz.org/doc/MusicBrainz_API
- Cover Art Archive API: https://musicbrainz.org/doc/Cover_Art_Archive/API
- mutagen ID3: https://mutagen.readthedocs.io/
- Picard tag mapping: https://picard-docs.musicbrainz.org/en/appendices/tag_mapping.html
- AudD API: https://docs.audd.io/
- ACRCloud: https://docs.acrcloud.com/

---

## 13. Acceptance criteria (v1)

- [ ] On a 50-file sample of the real library, dry-run output is reviewed and the run completes with no crashes.
- [ ] 0 files changed without `--write`.
- [ ] 100 % of written files are restorable through `rollback`.
- [ ] Every accepted match records its tier, score and source in the journal.
- [ ] Unmatched files are present in the review CSV. None are silently dropped.
- [ ] `report` shows counts per tier plus skipped, review and failed.
