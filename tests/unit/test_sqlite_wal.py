"""SQLite WAL is verified against a FILE-backed database (WAL does not apply in memory)."""

import sqlite3

import pytest

from tmc_access.infrastructure.persistence.sqlite import connect


@pytest.mark.unit
def test_wal_enabled_on_file_backed_db(tmp_path) -> None:
    db = tmp_path / "nested" / "edge.db"
    conn = connect(db)
    try:
        assert db.exists()
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 100
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()
    # WAL is persistent: a plain connection must observe it too.
    other = sqlite3.connect(db)
    try:
        assert other.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        other.close()


@pytest.mark.unit
@pytest.mark.parametrize("bad", [":memory:", "file::memory:?cache=shared", ""])
def test_in_memory_paths_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        connect(bad)
