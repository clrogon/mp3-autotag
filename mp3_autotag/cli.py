"""mp3-autotag CLI (spec §5). Only `scan` is implemented so far (Phase 1);
the rest are stubs so `--help` reflects the full command surface early."""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from mp3_autotag import __version__, db
from mp3_autotag.acoustid_client import AcoustidClient
from mp3_autotag.config import Config, ConfigError, load_config
from mp3_autotag.fingerprint import resolve_fpcalc_path
from mp3_autotag.logging_setup import configure_logging
from mp3_autotag.musicbrainz_client import MusicBrainzClient, configure_user_agent
from mp3_autotag.pipeline import identify_file
from mp3_autotag.rate_limit import RateLimiter
from mp3_autotag.scan import iter_mp3_files, scan_path
from mp3_autotag.tags import existing_tags_from_row

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


class State:
    config: Config
    verbose: bool = False


state = State()


@app.callback()
def main_callback(
    config: Optional[Path] = typer.Option(None, "--config", help="Path to mp3-autotag.toml"),
    verbose: bool = typer.Option(False, "--verbose", help="Verbose logging"),
) -> None:
    try:
        state.config = load_config(config)
    except ConfigError as exc:
        console.print(f"[red]Config error:[/red] {exc}")
        raise typer.Exit(code=1)
    state.verbose = verbose
    configure_logging(verbose)


def _not_implemented(command: str, phase: int) -> None:
    console.print(
        f"[yellow]`{command}` is not implemented yet (build Phase {phase} — see spec §10).[/yellow]"
    )
    raise typer.Exit(code=1)


@app.command()
def scan(
    path: Path = typer.Argument(..., exists=True, help="File or folder to scan recursively"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Process only the first N files"),
) -> None:
    """Inventory files, read existing tags, compute fingerprints (cached)."""
    conn = db.connect(state.config.general.db_path)
    db.init_schema(conn)
    run_id = db.new_run(conn, "scan", json.dumps({"path": str(path), "limit": limit}))

    try:
        summary = scan_path(path, state.config, conn, limit=limit)
    except Exception:
        db.finish_run(conn, run_id, "failed")
        raise
    else:
        db.finish_run(conn, run_id, "completed")
    finally:
        conn.close()

    table = Table(title=f"scan: {path}")
    table.add_column("metric")
    table.add_column("count", justify="right")
    table.add_row("total files", str(summary.total_files))
    table.add_row("tags already complete (title/artist/album)", str(summary.tags_complete))
    table.add_row("fingerprinted (cached or computed)", str(summary.fingerprinted))
    table.add_row("fingerprint skipped (fpcalc not found)", str(summary.fingerprint_skipped_no_fpcalc))
    table.add_row("fingerprint failed", str(summary.fingerprint_failed))
    console.print(table)


@app.command()
def identify(
    path: Path = typer.Argument(..., exists=True),
    tiers: str = typer.Option(
        "1,2,3", "--tiers", help="Comma-separated Tier 1/2/3 subset to attempt this run"
    ),
    force: bool = typer.Option(False, "--force", help="Disable the Tier 0 skip-check"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Process only the first N files"),
) -> None:
    """Run the pipeline, store candidates in the DB. Never writes to files."""
    cfg = state.config
    requested_tiers = {int(t.strip()) for t in tiers.split(",") if t.strip()}
    enabled_tiers = ({0} if not force else set()) | (requested_tiers & set(cfg.tiers.enabled) & {1, 2, 3})

    conn = db.connect(cfg.general.db_path)
    db.init_schema(conn)
    run_id = db.new_run(
        conn, "identify", json.dumps({"path": str(path), "tiers": sorted(enabled_tiers), "force": force})
    )

    # Refresh inventory, tags and the fpcalc cache before identifying.
    scan_path(path, cfg, conn, limit=limit)

    mb_client = None
    if 2 in enabled_tiers:
        configure_user_agent("mp3-autotag", __version__, cfg.general.require_contact_email())
        mb_client = MusicBrainzClient(conn, RateLimiter(1.0))

    acoustid_client = None
    fpcalc_path = resolve_fpcalc_path(cfg)
    if 1 in enabled_tiers:
        if not cfg.acoustid_api_key:
            console.print("[yellow]ACOUSTID_API_KEY not set; skipping Tier 1 for this run.[/yellow]")
            enabled_tiers.discard(1)
        else:
            acoustid_client = AcoustidClient(conn, RateLimiter(1 / 3), api_key=cfg.acoustid_api_key)

    files = iter_mp3_files(path)
    if limit is not None:
        files = files[:limit]

    counts: Counter[str] = Counter()
    for file_path in files:
        row = conn.execute(
            "SELECT * FROM files WHERE file_path = ?", (str(file_path),)
        ).fetchone()
        existing = existing_tags_from_row(row)
        outcome = identify_file(
            file_path,
            existing,
            row["duration_s"],
            row["file_hash"],
            cfg,
            conn,
            enabled_tiers,
            mb_client,
            acoustid_client,
            fpcalc_path,
        )
        db.insert_candidates(conn, run_id, str(file_path), outcome.stored)
        db.update_file_status(conn, str(file_path), outcome.status)
        db.record_identify_result(conn, run_id, str(file_path), outcome.status, outcome.accepted_tier, outcome.error)
        counts[outcome.status] += 1

    db.finish_run(conn, run_id, "completed")
    conn.close()

    table = Table(title=f"identify: {path} (run {run_id})")
    table.add_column("status")
    table.add_column("count", justify="right")
    for status, n in sorted(counts.items()):
        table.add_row(status, str(n))
    console.print(table)
    console.print(f"Run ID: [bold]{run_id}[/bold]")


@app.command()
def review(
    import_csv: Optional[Path] = typer.Option(None, "--import", help="Import decisions from CSV"),
) -> None:
    """Export the review queue to CSV; import decisions back with --import."""
    _not_implemented("review", phase=6)


@app.command()
def apply(
    path: Path = typer.Argument(..., exists=True),
    write: bool = typer.Option(False, "--write", help="Actually modify files (default: dry-run)"),
) -> None:
    """Dry-run by default; --write is required to modify files."""
    _not_implemented("apply", phase=5)


@app.command()
def rollback(run_id: str = typer.Argument(...)) -> None:
    """Restore files from backup for a given apply run."""
    _not_implemented("rollback", phase=5)


@app.command()
def report(run_id: Optional[str] = typer.Argument(None)) -> None:
    """Summary: matched per tier, low-confidence, failures."""
    conn = db.connect(state.config.general.db_path)

    if run_id is None:
        run_id = db.latest_run_id(conn, "identify")
        if run_id is None:
            console.print("[yellow]No `identify` runs found yet.[/yellow]")
            conn.close()
            raise typer.Exit(code=1)

    rows = db.identify_result_counts(conn, run_id)
    conn.close()

    if not rows:
        console.print(f"[yellow]No results found for run {run_id}.[/yellow]")
        raise typer.Exit(code=1)

    table = Table(title=f"report: run {run_id}")
    table.add_column("status")
    table.add_column("count", justify="right")
    for row in rows:
        table.add_row(row["status"], str(row["n"]))
    console.print(table)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
