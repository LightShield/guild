"""Tests for template management."""

from __future__ import annotations

import json

import pytest

from guild.templates.manager import Template, TemplateManager


@pytest.mark.unit
@pytest.mark.req("REQ-19.1")
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
@pytest.mark.req("REQ-19.2")
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
@pytest.mark.req("REQ-19.2")
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
@pytest.mark.req("REQ-19.3")
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
@pytest.mark.req("REQ-19.3")
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
