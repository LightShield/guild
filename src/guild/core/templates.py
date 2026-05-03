"""Session & workflow templates — save and replay workflows (REQ-19)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

__all__ = ["Template", "TemplateManager"]


class Template(BaseModel):
    """A reusable workflow template.

    Attributes:
        name: Template identifier.
        description: What this template does.
        team: Team name to use.
        task_template: Task description with {placeholders}.
        permission: Default permission tier.
        parameters: List of parameter names expected in task_template.
    """

    name: str
    description: str = ""
    team: str | None = None
    task_template: str = ""
    permission: str = "ask"
    parameters: list[str] = Field(default_factory=list)

    def render(self, **kwargs: str) -> str:
        """Render the task template with parameters.

        Args:
            **kwargs: Parameter values to substitute.

        Returns:
            Rendered task description.
        """
        result = self.task_template
        for key, value in kwargs.items():
            result = result.replace(f"{{{key}}}", value)
        return result


class TemplateManager:
    """Manages workflow templates stored as TOML files.

    Args:
        templates_dir: Directory containing template TOML files.
    """

    def __init__(self, templates_dir: Path) -> None:
        self._dir = templates_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[Template]:
        """List all available templates.

        Returns:
            List of Template objects.
        """
        templates = []
        for f in sorted(self._dir.glob("*.toml")):
            try:
                with open(f, "rb") as fh:
                    raw = tomllib.load(fh)
                if "template" in raw:
                    templates.append(Template(**raw["template"]))
            except Exception:
                continue
        return templates

    def get(self, name: str) -> Template | None:
        """Get a template by name.

        Args:
            name: Template name.

        Returns:
            Template or None.
        """
        for t in self.list():
            if t.name == name:
                return t
        return None

    def save(self, template: Template) -> Path:
        """Save a template to disk.

        Args:
            template: Template to save.

        Returns:
            Path to the saved file.
        """
        path = self._dir / f"{template.name}.toml"
        lines = [
            "[template]",
            f'name = "{template.name}"',
            f'description = "{template.description}"',
        ]
        if template.team:
            lines.append(f'team = "{template.team}"')
        lines.append(f'task_template = "{template.task_template}"')
        lines.append(f'permission = "{template.permission}"')
        if template.parameters:
            lines.append(f'parameters = {json.dumps(template.parameters)}')
        lines.append("")
        path.write_text("\n".join(lines))
        return path
