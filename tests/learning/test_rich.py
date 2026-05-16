"""Learning tests -- verify assumptions about rich library behavior.

If these break on upgrade, our code likely needs updating.

Guild depends on:
  - Console rendering tables to string (for CLI output)
  - Text with markup support (for styled output)
  - Console with string_io capture (for testing CLI output)
"""

from __future__ import annotations

import pytest
from rich.console import Console
from rich.table import Table
from rich.text import Text

pytestmark = pytest.mark.learning


class TestConsoleTableRendering:
    """Verify Console can render a Table to a captured string."""

    def test_console_renders_table_to_string(self) -> None:
        """Console with StringIO file captures table output as plain text."""
        from io import StringIO

        string_io = StringIO()
        console = Console(file=string_io, width=80)

        table = Table(title="Test Table")
        table.add_column("Name", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("key1", "value1")
        table.add_row("key2", "value2")

        console.print(table)

        output = string_io.getvalue()
        assert "Test Table" in output
        assert "key1" in output
        assert "value1" in output
        assert "key2" in output
        assert "value2" in output

    def test_console_record_mode_captures_output(self) -> None:
        """Console in record mode captures output via export_text."""
        console = Console(record=True, width=80)
        console.print("[bold]Hello[/bold] world")

        text = console.export_text()
        assert "Hello" in text
        assert "world" in text


class TestRichTextMarkup:
    """Verify rich.text.Text supports markup and style operations."""

    def test_text_from_markup(self) -> None:
        """Text.from_markup parses style tags into styled spans."""
        text = Text.from_markup("[bold]Guild[/bold] is [italic]awesome[/italic]")

        # The plain text content has no markup tags
        assert text.plain == "Guild is awesome"

    def test_text_plain_strips_markup(self) -> None:
        """Text.plain returns content without any style information."""
        text = Text.from_markup("[red]Error:[/red] something went wrong")
        assert text.plain == "Error: something went wrong"
        # Verify style spans were actually captured (not just stripped)
        assert len(text._spans) > 0
