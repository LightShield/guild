"""Tests for standard tool contract (REQ-08.1).

REQ-08.1: Every tool must have: name, description, input schema, execute().
This verifies that TOOL_SCHEMAS follows a consistent structure and that
ToolResult is the universal return type for all tool executors.
"""

from __future__ import annotations

import pytest

from guild.tools.base import TOOL_SCHEMAS, ToolResult


@pytest.mark.unit
@pytest.mark.req("REQ-08.1")
class TestToolSchemaStructure:
    """TOOL_SCHEMAS dict has a proper contract for each tool."""

    def test_all_schemas_have_name_field(self) -> None:
        """Every tool schema must declare a 'name' matching its key."""
        for key, schema in TOOL_SCHEMAS.items():
            assert "name" in schema, f"Tool '{key}' missing 'name' field"
            assert schema["name"] == key, (
                f"Tool key '{key}' does not match schema name '{schema['name']}'"
            )

    def test_all_schemas_have_description_field(self) -> None:
        """Every tool schema must have a non-empty 'description'."""
        for key, schema in TOOL_SCHEMAS.items():
            assert "description" in schema, f"Tool '{key}' missing 'description' field"
            assert isinstance(schema["description"], str)
            assert len(schema["description"]) > 0, (
                f"Tool '{key}' has empty description"
            )

    def test_all_schemas_have_parameters_with_type_object(self) -> None:
        """Every tool schema must have a 'parameters' dict with type 'object'."""
        for key, schema in TOOL_SCHEMAS.items():
            assert "parameters" in schema, f"Tool '{key}' missing 'parameters' field"
            params = schema["parameters"]
            assert isinstance(params, dict)
            assert params.get("type") == "object", (
                f"Tool '{key}' parameters must have type 'object'"
            )

    def test_all_schemas_have_properties_in_parameters(self) -> None:
        """Every tool schema's parameters must have a 'properties' dict."""
        for key, schema in TOOL_SCHEMAS.items():
            params = schema["parameters"]
            assert "properties" in params, (
                f"Tool '{key}' parameters missing 'properties'"
            )
            assert isinstance(params["properties"], dict)
            assert len(params["properties"]) > 0, (
                f"Tool '{key}' has no properties defined"
            )

    def test_all_schemas_have_required_fields_list(self) -> None:
        """Every tool schema must declare 'required' as a list of strings."""
        for key, schema in TOOL_SCHEMAS.items():
            params = schema["parameters"]
            assert "required" in params, (
                f"Tool '{key}' parameters missing 'required' field"
            )
            assert isinstance(params["required"], list)
            # All required fields must exist in properties
            for req_field in params["required"]:
                assert req_field in params["properties"], (
                    f"Tool '{key}': required field '{req_field}' not in properties"
                )

    def test_all_property_definitions_have_type_and_description(self) -> None:
        """Each property within a tool schema must have type and description."""
        for key, schema in TOOL_SCHEMAS.items():
            props = schema["parameters"]["properties"]
            for prop_name, prop_def in props.items():
                assert "type" in prop_def, (
                    f"Tool '{key}' property '{prop_name}' missing 'type'"
                )
                assert "description" in prop_def, (
                    f"Tool '{key}' property '{prop_name}' missing 'description'"
                )

    def test_schemas_contain_expected_tools(self) -> None:
        """We expect at least file_read and file_write in the registry."""
        assert "file_read" in TOOL_SCHEMAS
        assert "file_write" in TOOL_SCHEMAS

    def test_file_read_schema_requires_path(self) -> None:
        """file_read tool must require a 'path' parameter."""
        schema = TOOL_SCHEMAS["file_read"]
        assert "path" in schema["parameters"]["required"]
        assert "path" in schema["parameters"]["properties"]

    def test_file_write_schema_requires_path_and_content(self) -> None:
        """file_write tool must require 'path' and 'content' parameters."""
        schema = TOOL_SCHEMAS["file_write"]
        assert "path" in schema["parameters"]["required"]
        assert "content" in schema["parameters"]["required"]


@pytest.mark.unit
@pytest.mark.req("REQ-08.1")
class TestToolResultContract:
    """ToolResult dataclass is the standard return type for all tools."""

    def test_success_result_has_output_and_no_error(self) -> None:
        """A successful result carries output and error is None."""
        result = ToolResult(success=True, output="file content here")
        assert result.success is True
        assert result.output == "file content here"
        assert result.error is None

    def test_error_result_has_error_field(self) -> None:
        """A failed result carries an error message."""
        result = ToolResult(success=False, output="", error="File not found")
        assert result.success is False
        assert result.error == "File not found"

    def test_str_on_success_returns_output(self) -> None:
        """__str__ for success returns the output directly."""
        result = ToolResult(success=True, output="hello world")
        assert str(result) == "hello world"

    def test_str_on_error_returns_error_prefixed(self) -> None:
        """__str__ for error returns 'Error: <message>'."""
        result = ToolResult(success=False, output="", error="Permission denied")
        assert str(result) == "Error: Permission denied"

    def test_str_on_error_with_none_error(self) -> None:
        """__str__ for failed result with None error."""
        result = ToolResult(success=False, output="partial")
        # success is False but error is None — __str__ uses error path
        assert str(result) == "Error: None"

    def test_result_equality(self) -> None:
        """Two ToolResult instances with same fields are equal (dataclass)."""
        r1 = ToolResult(success=True, output="x")
        r2 = ToolResult(success=True, output="x")
        assert r1 == r2

    def test_result_inequality(self) -> None:
        """Different field values produce non-equal results."""
        r1 = ToolResult(success=True, output="x")
        r2 = ToolResult(success=True, output="y")
        assert r1 != r2


@pytest.mark.unit
@pytest.mark.req("REQ-08.1")
class TestToolExecutorsReturnToolResult:
    """All tool executors must return ToolResult consistently."""

    async def test_file_read_returns_tool_result_on_success(self, tmp_path) -> None:
        """execute_file_read returns ToolResult with success=True."""
        from guild.tools.file_ops import execute_file_read

        p = tmp_path / "test.txt"
        p.write_text("data")
        result = await execute_file_read({"path": str(p)})
        assert isinstance(result, ToolResult)
        assert result.success is True

    async def test_file_read_returns_tool_result_on_error(self) -> None:
        """execute_file_read returns ToolResult with success=False on missing file."""
        from guild.tools.file_ops import execute_file_read

        result = await execute_file_read({"path": "/nonexistent/file.txt"})
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert result.error is not None

    async def test_file_write_returns_tool_result_on_success(self, tmp_path) -> None:
        """execute_file_write returns ToolResult with success=True."""
        from guild.tools.file_ops import execute_file_write

        target = tmp_path / "out.txt"
        result = await execute_file_write({"path": str(target), "content": "hi"})
        assert isinstance(result, ToolResult)
        assert result.success is True

    async def test_file_write_returns_tool_result_on_error(self) -> None:
        """execute_file_write returns ToolResult with success=False on bad path."""
        from guild.tools.file_ops import execute_file_write

        result = await execute_file_write(
            {"path": "/dev/null/impossible/file.txt", "content": "x"}
        )
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert result.error is not None

    async def test_file_read_missing_args_returns_tool_result(self) -> None:
        """execute_file_read with empty args returns ToolResult error."""
        from guild.tools.file_ops import execute_file_read

        result = await execute_file_read({})
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "path" in result.error.lower()

    async def test_file_write_missing_content_returns_tool_result(self) -> None:
        """execute_file_write with missing content returns ToolResult error."""
        from guild.tools.file_ops import execute_file_write

        result = await execute_file_write({"path": "/tmp/x.txt"})
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "content" in result.error.lower()
