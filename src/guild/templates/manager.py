"""Template management: save, render, import/export."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path  # noqa: TC003

__all__ = ["Template", "TemplateManager"]

logger = logging.getLogger(__name__)


@dataclass
class Template:
    """A reusable parameterized workflow template."""

    name: str
    description: str = ""
    team: str | None = None
    task_template: str = ""  # with {placeholders}
    parameters: list[str] = field(default_factory=list)
    permission: str = "ask"


class TemplateManager:
    """Manages template CRUD, rendering, and import/export."""

    def __init__(self, templates_dir: Path) -> None:
        self._dir = templates_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _template_path(self, name: str) -> Path:
        return self._dir / f"{name}.json"

    def list(self) -> list[Template]:
        """List all saved templates."""
        templates: list[Template] = []
        for p in sorted(self._dir.glob("*.json")):
            tpl = self._load_file(p)
            if tpl is not None:
                templates.append(tpl)
        return templates

    def get(self, name: str) -> Template | None:
        """Get a template by name."""
        path = self._template_path(name)
        if not path.exists():
            return None
        return self._load_file(path)

    def save(self, template: Template) -> Path:
        """Save a template to disk as JSON."""
        path = self._template_path(template.name)
        data = asdict(template)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        logger.debug("Saved template %s", template.name)
        return path

    def render(self, template: Template, **params: str) -> str:
        """Render template task string, substituting parameters.

        Missing parameters are left as {placeholder}.
        """
        result = template.task_template
        for key, value in params.items():
            result = result.replace(f"{{{key}}}", value)
        return result

    def export(self, name: str, output_path: Path) -> Path:
        """Export a template file to a target path."""
        src = self._template_path(name)
        if not src.exists():
            msg = f"Template '{name}' not found"
            raise FileNotFoundError(msg)
        output_path.mkdir(parents=True, exist_ok=True)
        dest = output_path / src.name
        shutil.copy2(src, dest)
        logger.info("Exported template %s to %s", name, dest)
        return dest

    def import_template(self, source_path: Path) -> Template:
        """Import a template from a JSON file."""
        tpl = self._load_file(source_path)
        if tpl is None:
            msg = f"Cannot load template from {source_path}"
            raise ValueError(msg)
        self.save(tpl)
        logger.info("Imported template %s from %s", tpl.name, source_path)
        return tpl

    def _load_file(self, path: Path) -> Template | None:
        """Load a Template from a JSON file."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Template(**data)
        except (json.JSONDecodeError, TypeError, KeyError):
            logger.warning("Failed to load template from %s", path)
            return None
