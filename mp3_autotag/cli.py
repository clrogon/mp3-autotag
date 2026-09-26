"""mp3-autotag CLI (spec §5). Only `scan` is implemented so far (Phase 1);
the rest are stubs so `--help` reflects the full command surface early."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from mp3_autotag import db
from mp3_autotag.config import Config, ConfigError, load_config
from mp3_autotag.logging_setup import configure_logging
from mp3_autotag.scan import scan_path

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
    tiers: str = typer.Option("1,2,3", "--tiers"),
) -> None:
    """Run the pipeline, store candidates in the DB. Never writes to files."""
    _not_implemented("identify", phase=4)


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
    _not_implemented("report", phase=4)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
