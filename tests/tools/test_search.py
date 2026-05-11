"""Tests for search and glob tools (REQ-08.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from guild.tools.search import (
    MAX_GLOB_RESULTS,
    MAX_SEARCH_RESULTS,
    execute_glob,
    execute_search,
)


@pytest.mark.unit
@pytest.mark.req("REQ-08.3")
class TestSearch:
    """Tests for execute_search."""

    async def test_search_finds_matching_lines(self, tmp_path: object) -> None:
        f = tmp_path / "code.py"  # type: ignore[operator]
        f.write_text("line 1\nhello world\nline 3\n")

        result = await execute_search(
            {"pattern": "hello", "path": str(tmp_path)},
            working_dir=str(tmp_path),
        )

        assert result.success is True
        assert "hello world" in result.output

    async def test_search_returns_no_matches_message(self, tmp_path: object) -> None:
        f = tmp_path / "empty.py"  # type: ignore[operator]
        f.write_text("nothing here\n")

        result = await execute_search(
            {"pattern": "zzzzz_nomatch", "path": str(tmp_path)},
            working_dir=str(tmp_path),
        )

        assert result.success is True
        assert "no matches" in result.output.lower()

    async def test_search_invalid_regex_returns_error(self, tmp_path: object) -> None:
        f = tmp_path / "x.py"  # type: ignore[operator]
        f.write_text("content\n")

        result = await execute_search(
            {"pattern": "[invalid", "path": str(tmp_path)},
            working_dir=str(tmp_path),
        )

        assert result.success is False
        assert result.error is not None
        assert "regex" in result.error.lower() or "pattern" in result.error.lower()

    async def test_search_respects_include_filter(self, tmp_path: object) -> None:
        py_file = tmp_path / "code.py"  # type: ignore[operator]
        py_file.write_text("match_this\n")
        txt_file = tmp_path / "data.txt"  # type: ignore[operator]
        txt_file.write_text("match_this\n")

        result = await execute_search(
            {"pattern": "match_this", "path": str(tmp_path), "include": "*.py"},
            working_dir=str(tmp_path),
        )

        assert result.success is True
        assert "code.py" in result.output
        assert "data.txt" not in result.output

    async def test_search_skips_git_directory(self, tmp_path: object) -> None:
        git_dir = tmp_path / ".git"  # type: ignore[operator]
        git_dir.mkdir()
        git_file = git_dir / "config"
        git_file.write_text("match_secret\n")

        src_file = tmp_path / "src.py"  # type: ignore[operator]
        src_file.write_text("match_secret\n")

        result = await execute_search(
            {"pattern": "match_secret", "path": str(tmp_path)},
            working_dir=str(tmp_path),
        )

        assert result.success is True
        assert "src.py" in result.output
        assert ".git" not in result.output

    async def test_search_truncates_at_max_results(self, tmp_path: object) -> None:
        # Create many files with matches
        for i in range(MAX_SEARCH_RESULTS + 50):
            f = tmp_path / f"file_{i:04d}.txt"  # type: ignore[operator]
            f.write_text(f"match_line_{i}\n")

        result = await execute_search(
            {"pattern": "match_line_", "path": str(tmp_path)},
            working_dir=str(tmp_path),
        )

        assert result.success is True
        assert "truncated" in result.output.lower() or "limit" in result.output.lower()


@pytest.mark.unit
@pytest.mark.req("REQ-08.3")
class TestGlob:
    """Tests for execute_glob."""

    async def test_glob_finds_matching_files(self, tmp_path: object) -> None:
        (tmp_path / "main.py").write_text("")  # type: ignore[operator]
        (tmp_path / "utils.py").write_text("")  # type: ignore[operator]
        (tmp_path / "readme.md").write_text("")  # type: ignore[operator]

        result = await execute_glob(
            {"pattern": "**/*.py", "path": str(tmp_path)},
            working_dir=str(tmp_path),
        )

        assert result.success is True
        assert "main.py" in result.output
        assert "utils.py" in result.output
        assert "readme.md" not in result.output

    async def test_glob_returns_no_files_message(self, tmp_path: object) -> None:
        result = await execute_glob(
            {"pattern": "**/*.xyz", "path": str(tmp_path)},
            working_dir=str(tmp_path),
        )

        assert result.success is True
        assert "no files" in result.output.lower() or "no matches" in result.output.lower()

    async def test_glob_skips_git_directory(self, tmp_path: object) -> None:
        git_dir = tmp_path / ".git"  # type: ignore[operator]
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n")

        (tmp_path / "app.py").write_text("")  # type: ignore[operator]

        result = await execute_glob(
            {"pattern": "**/*", "path": str(tmp_path)},
            working_dir=str(tmp_path),
        )

        assert result.success is True
        assert "app.py" in result.output
        assert ".git" not in result.output

    async def test_glob_limits_results(self, tmp_path: object) -> None:
        # Create more files than MAX_GLOB_RESULTS
        sub = tmp_path / "many"  # type: ignore[operator]
        sub.mkdir()
        for i in range(MAX_GLOB_RESULTS + 50):
            (sub / f"file_{i:04d}.txt").write_text("")

        result = await execute_glob(
            {"pattern": "**/*.txt", "path": str(tmp_path)},
            working_dir=str(tmp_path),
        )

        assert result.success is True
        assert "truncated" in result.output.lower() or "limit" in result.output.lower()


# ======================================================================
# Search tool edge cases (from coverage gaps)
# ======================================================================


@pytest.mark.unit
@pytest.mark.req("REQ-08.3")
class TestSearchToolEdgeCases:
    """Cover search/glob tool edge cases."""

    async def test_search_empty_pattern_returns_error(self) -> None:
        """Missing pattern returns error."""
        result = await execute_search({"pattern": ""}, working_dir="/tmp")
        assert result.success is False
        assert "pattern" in (result.error or "").lower()

    async def test_search_path_not_found(self, tmp_path: Path) -> None:
        """Non-existent path returns error."""
        result = await execute_search(
            {"pattern": "hello", "path": str(tmp_path / "nope")},
            working_dir=str(tmp_path),
        )
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    async def test_search_single_file(self, tmp_path: Path) -> None:
        """Search on a single file works."""
        f = tmp_path / "test.txt"
        f.write_text("hello world\ngoodbye world\n")
        result = await execute_search(
            {"pattern": "hello", "path": str(f)},
            working_dir=str(tmp_path),
        )
        assert result.success is True
        assert "hello" in result.output

    async def test_search_file_oserror_skipped(self, tmp_path: Path) -> None:
        """Files that raise OSError on read are silently skipped."""
        f = tmp_path / "test.txt"
        f.write_text("content")
        # Make file unreadable
        f.chmod(0o000)
        try:
            result = await execute_search(
                {"pattern": "content", "path": str(tmp_path)},
                working_dir=str(tmp_path),
            )
            # Should not error out, just find no matches
            assert result.success is True
        finally:
            f.chmod(0o644)

    async def test_search_is_relative_to_false(self, tmp_path: Path) -> None:
        """File not relative to base uses absolute path in results."""
        from guild.tools.search import _is_relative_to

        assert _is_relative_to(Path("/a/b/c"), Path("/a/b")) is True
        assert _is_relative_to(Path("/x/y"), Path("/a/b")) is False

    async def test_glob_empty_pattern_returns_error(self) -> None:
        """Missing glob pattern returns error."""
        result = await execute_glob({"pattern": ""}, working_dir="/tmp")
        assert result.success is False
        assert "pattern" in (result.error or "").lower()

    async def test_glob_path_not_found(self, tmp_path: Path) -> None:
        """Non-existent path returns error."""
        result = await execute_glob(
            {"pattern": "*.txt", "path": str(tmp_path / "nope")},
            working_dir=str(tmp_path),
        )
        assert result.success is False
        assert "not found" in (result.error or "").lower()
