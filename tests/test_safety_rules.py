"""Tests for safety rules in tool descriptions (REQ-08.9)."""

import pytest

pytestmark = pytest.mark.unit

from guild.core.agent import BUILTIN_TOOLS


class TestSafetyRules:
    """REQ-08.9: Safety rules embedded in tool descriptions."""

    def test_shell_has_safety_rules(self):
        desc = BUILTIN_TOOLS["shell"]["function"]["description"]
        assert "NEVER" in desc
        assert "destructive" in desc.lower() or "rm -rf" in desc

    def test_file_write_has_safety_rules(self):
        desc = BUILTIN_TOOLS["file_write"]["function"]["description"]
        assert "SAFETY" in desc
        assert "read" in desc.lower()  # "read before editing"

    def test_file_read_has_description(self):
        desc = BUILTIN_TOOLS["file_read"]["function"]["description"]
        assert "read" in desc.lower() or "Read" in desc

    def test_search_has_description(self):
        desc = BUILTIN_TOOLS["search"]["function"]["description"]
        assert "search" in desc.lower() or "pattern" in desc.lower()

    def test_all_tools_have_descriptions(self):
        for name, tool in BUILTIN_TOOLS.items():
            desc = tool["function"]["description"]
            assert len(desc) > 10, f"Tool '{name}' has too short a description"
