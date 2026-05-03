"""Tests for token usage tracking and display (REQ-10.1)."""

import asyncio

import pytest

pytestmark = pytest.mark.integration

from typer.testing import CliRunner

from guild.cli.main import app

runner = CliRunner()


class TestTokenDisplay:
    """REQ-10.1: Token usage visible in guild status."""

    def test_status_shows_token_columns(self, tmp_path, monkeypatch):
        """Status agents table should have token columns."""
        runner.invoke(app, ["init", str(tmp_path)])
        monkeypatch.chdir(tmp_path)

        # Add an agent with token data directly
        async def _add_agent():
            from guild.core.storage import Storage

            s = Storage(tmp_path / ".guild" / "guild.db")
            await s.connect()
            await s.register_agent("test-agent", "coder")
            await s.update_agent("test-agent", status="done", token_input="150", token_output="75")
            await s.close()

        asyncio.run(_add_agent())
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "150" in result.stdout
        assert "75" in result.stdout
