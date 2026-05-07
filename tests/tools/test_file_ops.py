"""Tests for file operation tools (REQ-08.3)."""

from __future__ import annotations

import pytest

from guild.tools.base import resolve_path
from guild.tools.file_ops import MAX_FILE_READ_CHARS, execute_file_read, execute_file_write


@pytest.mark.unit
@pytest.mark.req("REQ-08.3")
class TestFileRead:
    """Tests for execute_file_read."""

    async def test_file_read_returns_content_for_existing_file(self, tmp_path: object) -> None:
        p = tmp_path / "hello.txt"  # type: ignore[operator]
        p.write_text("hello world")

        result = await execute_file_read({"path": str(p)}, working_dir=str(tmp_path))

        assert result.success is True
        assert result.output == "hello world"
        assert result.error is None

    async def test_file_read_returns_error_for_missing_file(self, tmp_path: object) -> None:
        result = await execute_file_read(
            {"path": str(tmp_path / "nonexistent.txt")},  # type: ignore[operator]
            working_dir=str(tmp_path),
        )

        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower() or "does not exist" in result.error.lower()

    async def test_file_read_truncates_large_files(self, tmp_path: object) -> None:
        p = tmp_path / "big.txt"  # type: ignore[operator]
        content = "x" * (MAX_FILE_READ_CHARS + 1000)
        p.write_text(content)

        result = await execute_file_read({"path": str(p)}, working_dir=str(tmp_path))

        assert result.success is True
        assert len(result.output) <= MAX_FILE_READ_CHARS + 100  # allow for truncation message
        assert "truncated" in result.output.lower()

    async def test_file_read_handles_binary_gracefully(self, tmp_path: object) -> None:
        p = tmp_path / "binary.bin"  # type: ignore[operator]
        p.write_bytes(b"\x00\x01\x02\xff\xfe\xfd hello \x80\x81")

        result = await execute_file_read({"path": str(p)}, working_dir=str(tmp_path))

        assert result.success is True
        # Should not raise — uses errors="replace"
        assert "hello" in result.output


@pytest.mark.unit
@pytest.mark.req("REQ-08.3")
class TestFileWrite:
    """Tests for execute_file_write."""

    async def test_file_write_creates_file_with_content(self, tmp_path: object) -> None:
        target = tmp_path / "output.txt"  # type: ignore[operator]

        result = await execute_file_write(
            {"path": str(target), "content": "new content"},
            working_dir=str(tmp_path),
        )

        assert result.success is True
        assert target.read_text() == "new content"

    async def test_file_write_creates_parent_directories(self, tmp_path: object) -> None:
        target = tmp_path / "a" / "b" / "c" / "file.txt"  # type: ignore[operator]

        result = await execute_file_write(
            {"path": str(target), "content": "deep"},
            working_dir=str(tmp_path),
        )

        assert result.success is True
        assert target.exists()
        assert target.read_text() == "deep"

    async def test_file_write_overwrites_existing_file(self, tmp_path: object) -> None:
        target = tmp_path / "exists.txt"  # type: ignore[operator]
        target.write_text("old content")

        result = await execute_file_write(
            {"path": str(target), "content": "new content"},
            working_dir=str(tmp_path),
        )

        assert result.success is True
        assert target.read_text() == "new content"

    async def test_file_write_reports_chars_written(self, tmp_path: object) -> None:
        target = tmp_path / "count.txt"  # type: ignore[operator]
        content = "twelve chars"

        result = await execute_file_write(
            {"path": str(target), "content": content},
            working_dir=str(tmp_path),
        )

        assert result.success is True
        assert str(len(content)) in result.output


@pytest.mark.unit
@pytest.mark.req("REQ-08.3")
class TestResolvePath:
    """Tests for resolve_path helper."""

    def test_resolve_path_makes_relative_absolute(self, tmp_path: object) -> None:
        resolved = resolve_path("subdir/file.txt", str(tmp_path))

        assert resolved.is_absolute()
        assert resolved == tmp_path / "subdir" / "file.txt"  # type: ignore[operator]

    def test_resolve_path_leaves_absolute_unchanged(self, tmp_path: object) -> None:
        abs_path = "/usr/local/something.txt"

        resolved = resolve_path(abs_path, str(tmp_path))

        assert str(resolved) == abs_path
