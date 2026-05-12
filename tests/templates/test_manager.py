"""Tests for template management."""

from __future__ import annotations

import json

import pytest

from guild.templates.manager import Template, TemplateManager


@pytest.mark.unit
def test_save_template_to_disk(tmp_path: object) -> None:
    """Saving a template creates a JSON file on disk."""
    mgr = TemplateManager(tmp_path)  # type: ignore[arg-type]
    tpl = Template(
        name="code-review",
        description="Run a code review workflow",
        task_template="Review {file} for {criteria}",
        parameters=["file", "criteria"],
    )

    path = mgr.save(tpl)

    assert path.exists()
    data = json.loads(path.read_text())
    assert data["name"] == "code-review"
    assert data["parameters"] == ["file", "criteria"]

    # get() should retrieve it
    loaded = mgr.get("code-review")
    assert loaded is not None
    assert loaded.name == "code-review"
    assert loaded.task_template == "Review {file} for {criteria}"


@pytest.mark.unit
def test_render_template_with_params(tmp_path: object) -> None:
    """Rendering substitutes all provided parameters."""
    mgr = TemplateManager(tmp_path)  # type: ignore[arg-type]
    tpl = Template(
        name="deploy",
        task_template="Deploy {service} to {environment}",
        parameters=["service", "environment"],
    )

    result = mgr.render(tpl, service="auth-api", environment="staging")
    assert result == "Deploy auth-api to staging"


@pytest.mark.unit
def test_render_missing_param_left_as_placeholder(tmp_path: object) -> None:
    """Missing parameters remain as {placeholder} in rendered output."""
    mgr = TemplateManager(tmp_path)  # type: ignore[arg-type]
    tpl = Template(
        name="partial",
        task_template="Fix {bug} in {module}",
        parameters=["bug", "module"],
    )

    result = mgr.render(tpl, bug="NPE")
    assert result == "Fix NPE in {module}"


@pytest.mark.unit
def test_export_template(tmp_path: object) -> None:
    """Exporting a template copies its JSON to the output path."""
    mgr = TemplateManager(tmp_path / "templates")  # type: ignore[arg-type]
    tpl = Template(name="my-tpl", description="A test template")
    mgr.save(tpl)

    export_dir = tmp_path / "exported"  # type: ignore[operator]
    result = mgr.export("my-tpl", export_dir)

    assert result.exists()
    data = json.loads(result.read_text())
    assert data["name"] == "my-tpl"


@pytest.mark.unit
def test_import_template(tmp_path: object) -> None:
    """Importing a template from a file adds it to the manager."""
    # Create a source template file
    source = tmp_path / "source.json"  # type: ignore[operator]
    data = {
        "name": "imported-tpl",
        "description": "Imported from external",
        "team": None,
        "task_template": "Do {thing}",
        "parameters": ["thing"],
        "permission": "ask",
    }
    source.write_text(json.dumps(data))

    mgr = TemplateManager(tmp_path / "templates")  # type: ignore[arg-type]
    tpl = mgr.import_template(source)

    assert tpl.name == "imported-tpl"
    assert tpl.task_template == "Do {thing}"
    # Should now be retrievable
    assert mgr.get("imported-tpl") is not None


# ------------------------------------------------------------------
# Additional coverage tests for list, get, export, import, _load_file
# ------------------------------------------------------------------


@pytest.mark.unit
class TestTemplateList:
    """Tests for TemplateManager.list()."""

    def test_list_returns_all_saved_templates(self, tmp_path: object) -> None:
        """list() returns all templates saved in the directory."""
        mgr = TemplateManager(tmp_path)  # type: ignore[arg-type]
        mgr.save(Template(name="alpha", description="First"))
        mgr.save(Template(name="beta", description="Second"))
        mgr.save(Template(name="gamma", description="Third"))

        templates = mgr.list()

        names = [t.name for t in templates]
        assert "alpha" in names
        assert "beta" in names
        assert "gamma" in names
        assert len(templates) == 3

    def test_list_returns_empty_when_no_templates(self, tmp_path: object) -> None:
        """list() returns empty list when no templates saved."""
        mgr = TemplateManager(tmp_path / "empty-dir")  # type: ignore[arg-type]
        assert mgr.list() == []


@pytest.mark.unit
class TestTemplateGet:
    """Tests for TemplateManager.get()."""

    def test_get_returns_none_for_missing(self, tmp_path: object) -> None:
        """get() returns None when template name does not exist."""
        mgr = TemplateManager(tmp_path)  # type: ignore[arg-type]
        result = mgr.get("nonexistent")
        assert result is None

    def test_get_returns_template_for_existing(self, tmp_path: object) -> None:
        """get() returns the Template when it exists."""
        mgr = TemplateManager(tmp_path)  # type: ignore[arg-type]
        mgr.save(Template(name="exists", description="I exist"))
        result = mgr.get("exists")
        assert result is not None
        assert result.name == "exists"
        assert result.description == "I exist"


@pytest.mark.unit
class TestTemplateExport:
    """Tests for TemplateManager.export()."""

    def test_export_copies_file_to_output_path(self, tmp_path: object) -> None:
        """export() copies the template JSON to the target directory."""
        mgr = TemplateManager(tmp_path / "templates")  # type: ignore[arg-type]
        mgr.save(Template(name="exportable", description="For export"))

        output_dir = tmp_path / "out"  # type: ignore[operator]
        result_path = mgr.export("exportable", output_dir)

        assert result_path.exists()
        data = json.loads(result_path.read_text())
        assert data["name"] == "exportable"

    def test_export_raises_for_missing_template(self, tmp_path: object) -> None:
        """export() raises FileNotFoundError for nonexistent template."""
        mgr = TemplateManager(tmp_path)  # type: ignore[arg-type]
        with pytest.raises(FileNotFoundError, match="not found"):
            mgr.export("no-such-template", tmp_path / "out")  # type: ignore[operator]


@pytest.mark.unit
class TestTemplateImport:
    """Tests for TemplateManager.import_template()."""

    def test_import_loads_and_saves(self, tmp_path: object) -> None:
        """import_template() loads from file and saves to manager."""
        source = tmp_path / "ext.json"  # type: ignore[operator]
        source.write_text(
            json.dumps(
                {
                    "name": "ext-tpl",
                    "description": "External",
                    "team": None,
                    "task_template": "Run {cmd}",
                    "parameters": ["cmd"],
                    "permission": "ask",
                }
            )
        )

        mgr = TemplateManager(tmp_path / "templates")  # type: ignore[arg-type]
        tpl = mgr.import_template(source)

        assert tpl.name == "ext-tpl"
        # Verify it is now persisted
        loaded = mgr.get("ext-tpl")
        assert loaded is not None
        assert loaded.task_template == "Run {cmd}"

    def test_import_raises_for_corrupted_json(self, tmp_path: object) -> None:
        """import_template() raises ValueError for unreadable JSON."""
        bad_file = tmp_path / "bad.json"  # type: ignore[operator]
        bad_file.write_text("not valid json {{{")

        mgr = TemplateManager(tmp_path / "templates")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="Cannot load template"):
            mgr.import_template(bad_file)


@pytest.mark.unit
class TestLoadFileCorrupted:
    """Tests for TemplateManager._load_file with corrupted data."""

    def test_load_file_returns_none_for_corrupted_json(self, tmp_path: object) -> None:
        """_load_file returns None for non-JSON content."""
        mgr = TemplateManager(tmp_path)  # type: ignore[arg-type]
        bad_file = tmp_path / "broken.json"  # type: ignore[operator]
        bad_file.write_text("this is not json")

        result = mgr._load_file(bad_file)
        assert result is None

    def test_load_file_returns_none_for_missing_keys(self, tmp_path: object) -> None:
        """_load_file returns None when JSON is missing required fields."""
        mgr = TemplateManager(tmp_path)  # type: ignore[arg-type]
        # Missing 'name' field which is required by Template dataclass
        bad_file = tmp_path / "incomplete.json"  # type: ignore[operator]
        bad_file.write_text(json.dumps({"description": "no name field"}))

        result = mgr._load_file(bad_file)
        assert result is None

    def test_list_skips_corrupted_files(self, tmp_path: object) -> None:
        """list() skips corrupted template files gracefully."""
        mgr = TemplateManager(tmp_path)  # type: ignore[arg-type]
        # Save a valid template
        mgr.save(Template(name="valid", description="OK"))
        # Write a corrupted file
        bad_file = tmp_path / "bad.json"  # type: ignore[operator]
        bad_file.write_text("corrupted content")

        templates = mgr.list()
        # Only the valid one should be returned
        assert len(templates) == 1
        assert templates[0].name == "valid"
