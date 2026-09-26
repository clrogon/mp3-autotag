from __future__ import annotations

from pathlib import Path

import pytest

from mp3_autotag import db
from mp3_autotag.config import Config

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def memory_conn():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def default_config() -> Config:
    return Config()
