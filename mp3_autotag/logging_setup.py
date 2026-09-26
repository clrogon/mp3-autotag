"""Rotating log file + rich console output (spec §7.11)."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler


def configure_logging(verbose: bool, log_path: str | Path = "mp3-autotag.log") -> None:
    root = logging.getLogger("mp3_autotag")
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()

    console_handler = RichHandler(show_time=False, show_path=False)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(console_handler)

    file_handler = RotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(file_handler)
