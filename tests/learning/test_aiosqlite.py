# Learning tests — verify assumptions about aiosqlite behavior.
# If these break on upgrade, our code likely needs updating.
#
# Guild depends on:
#   - PRAGMA journal_mode=WAL works and is reported back
#   - aiosqlite.Row acts as dict (supports dict(row), row[key])
#   - executescript() can run multi-statement DDL
#   - WAL mode allows concurrent reads

from __future__ import annotations

import asyncio

import aiosqlite
import pytest


@pytest.mark.unit
class TestWalModeCanBeSet:
    """Verify PRAGMA journal_mode=WAL works — used in Storage.connect()."""

    async def test_wal_mode_can_be_set(self, tmp_path) -> None:
        db_path = str(tmp_path / "test.db")
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("PRAGMA journal_mode=WAL")
            row = await cursor.fetchone()
            assert row[0] == "wal"

    async def test_wal_mode_persists_after_reopen(self, tmp_path) -> None:
        db_path = str(tmp_path / "test.db")
        async with aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")

        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("PRAGMA journal_mode")
            row = await cursor.fetchone()
            assert row[0] == "wal"


@pytest.mark.unit
class TestRowFactoryMakesDictRows:
    """Verify aiosqlite.Row lets us call dict(row) — used everywhere in Storage."""

    async def test_row_factory_makes_dict_rows(self, tmp_path) -> None:
        db_path = str(tmp_path / "test.db")
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
            await db.execute("INSERT INTO t (name) VALUES (?)", ("alice",))
            await db.commit()

            cursor = await db.execute("SELECT * FROM t")
            row = await cursor.fetchone()

            # Our code relies on dict(row) to convert to plain dict
            d = dict(row)
            assert d["id"] == 1
            assert d["name"] == "alice"

    async def test_row_supports_key_access(self, tmp_path) -> None:
        db_path = str(tmp_path / "test.db")
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("CREATE TABLE t (val TEXT)")
            await db.execute("INSERT INTO t VALUES (?)", ("hello",))
            await db.commit()

            cursor = await db.execute("SELECT * FROM t")
            row = await cursor.fetchone()
            # Row also supports index access
            assert row[0] == "hello"
            assert row["val"] == "hello"


@pytest.mark.unit
class TestExecutescriptCreatesTables:
    """Verify executescript works for multi-statement DDL — used in Storage.connect()."""

    async def test_executescript_creates_tables(self, tmp_path) -> None:
        db_path = str(tmp_path / "test.db")
        schema = """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            description TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            block_name TEXT NOT NULL
        );
        """
        async with aiosqlite.connect(db_path) as db:
            await db.executescript(schema)
            await db.commit()

            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            rows = await cursor.fetchall()
            table_names = {row[0] for row in rows}
            assert "tasks" in table_names
            assert "agents" in table_names

    async def test_executescript_is_idempotent_with_if_not_exists(self, tmp_path) -> None:
        db_path = str(tmp_path / "test.db")
        schema = "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY);"
        async with aiosqlite.connect(db_path) as db:
            await db.executescript(schema)
            await db.executescript(schema)  # should not raise
            await db.commit()


@pytest.mark.unit
class TestConcurrentReadsWorkInWalMode:
    """Verify concurrent reads work in WAL mode — core assumption for Guild."""

    async def test_concurrent_reads_work_in_wal_mode(self, tmp_path) -> None:
        db_path = str(tmp_path / "test.db")

        # Set up schema and seed data
        async with aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
            for i in range(10):
                await db.execute("INSERT INTO t (val) VALUES (?)", (f"row-{i}",))
            await db.commit()

        # Open two connections and read concurrently
        async def read_all(path: str) -> list:
            async with aiosqlite.connect(path) as db:
                cursor = await db.execute("SELECT * FROM t")
                return await cursor.fetchall()

        results = await asyncio.gather(read_all(db_path), read_all(db_path))
        assert len(results[0]) == 10
        assert len(results[1]) == 10

    async def test_read_while_write_in_wal_mode(self, tmp_path) -> None:
        """A reader should see committed data even while another connection writes."""
        db_path = str(tmp_path / "test.db")

        async with aiosqlite.connect(db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
            await db.execute("INSERT INTO t (val) VALUES (?)", ("initial",))
            await db.commit()

        # Reader connection sees committed data
        async with aiosqlite.connect(db_path) as reader:
            cursor = await reader.execute("SELECT COUNT(*) FROM t")
            row = await cursor.fetchone()
            assert row[0] == 1
