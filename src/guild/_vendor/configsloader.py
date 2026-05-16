"""Vendored ConfigsLoader — multi-source configuration loading.

Provides Field descriptor and ConfigsLoader base class that supports:
- Class-level field declarations with Field()
- TOML file loading
- Environment variable overlay
- CLI argument overlay
- Default values from Field declarations
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

__all__ = ["ConfigsLoader", "Field"]


class FieldDescriptor:
    """Descriptor that stores metadata for a configuration field."""

    def __init__(
        self,
        default: Any = None,
        section: str = "",
        flags: list[str] | None = None,
        env: str = "",
        description: str = "",
    ) -> None:
        self.default = default
        self.section = section
        self.flags = flags or []
        self.env = env
        self.description = description
        self.attr_name: str = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.attr_name = name

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        return obj.__dict__.get(self.attr_name, self.default)

    def __set__(self, obj: Any, value: Any) -> None:
        obj.__dict__[self.attr_name] = value


def Field(
    default: Any = None,
    section: str = "",
    flags: list[str] | None = None,
    env: str = "",
    description: str = "",
) -> Any:
    """Declare a configuration field with metadata."""
    return FieldDescriptor(
        default=default,
        section=section,
        flags=flags,
        env=env,
        description=description,
    )


class _ConfigsLoaderMeta(type):
    """Metaclass that collects Field descriptors into _fields registry."""

    def __new__(mcs, name: str, bases: tuple[type, ...], namespace: dict[str, Any]) -> type:
        cls = super().__new__(mcs, name, bases, namespace)
        # Collect all FieldDescriptor instances from all MRO classes
        fields: dict[str, FieldDescriptor] = {}
        for klass in reversed(cls.__mro__):
            for attr_name, attr_val in vars(klass).items():
                if isinstance(attr_val, FieldDescriptor):
                    attr_val.attr_name = attr_name
                    fields[attr_name] = attr_val
        cls._fields = fields  # type: ignore[attr-defined]
        return cls


class ConfigsLoader(metaclass=_ConfigsLoaderMeta):
    """Base class for declarative configuration with multi-source loading."""

    _fields: dict[str, FieldDescriptor]

    def __init__(self, **kwargs: Any) -> None:
        # Set fields from kwargs; for fields not in kwargs, use default
        for field_name, field_desc in self._fields.items():
            if field_name in kwargs:
                value = kwargs[field_name]
                # Coerce value to field's type based on default
                value = self._coerce(field_desc, value)
                setattr(self, field_name, value)
            else:
                setattr(self, field_name, field_desc.default)

    @classmethod
    def _coerce(cls, field_desc: FieldDescriptor, value: Any) -> Any:
        """Coerce a value to match the field's default type."""
        default = field_desc.default
        if value is None:
            return value
        if default is None:
            return value

        target_type = type(default)

        # Handle enum types
        if hasattr(target_type, "__members__"):
            if isinstance(value, str):
                # Try to find enum value by value string
                for member in target_type:
                    if member.value == value:
                        return member
                # Try by name
                try:
                    return target_type(value)
                except (ValueError, KeyError):
                    return value
            return value

        # Handle basic types
        if isinstance(value, target_type):
            return value

        try:
            if target_type is bool:
                if isinstance(value, str):
                    return value.lower() in ("true", "1", "yes")
                return bool(value)
            if target_type is int:
                return int(value)
            if target_type is float:
                return float(value)
            if target_type is str:
                return str(value)
        except (ValueError, TypeError):
            pass

        return value

    @classmethod
    def load(
        cls,
        config_path: Path | str | None = None,
        cli_args: list[str] | None = None,
        env_prefix: str | None = None,
        # Alternative parameter names used by the codebase
        file: Path | str | None = None,
        args: list[str] | None = None,
        **kwargs: Any,
    ) -> ConfigsLoader:
        """Load configuration from multiple sources.

        Resolution order (highest priority first):
        1. CLI arguments
        2. Environment variables
        3. Config file (TOML)
        4. Default values

        Supports both parameter naming conventions:
        - config_path / cli_args / env_prefix (canonical)
        - file / args (shorthand used by Guild)
        """
        # Normalize parameter names
        toml_path = file or config_path
        arg_list = args if args is not None else cli_args
        if arg_list is None:
            arg_list = []

        values: dict[str, Any] = {}

        # 1. Load from TOML file
        if toml_path:
            file_values = cls._load_toml(toml_path)
            values.update(file_values)

        # 2. Overlay environment variables
        env_values = cls._load_env()
        values.update(env_values)

        # 3. Overlay CLI args
        cli_values = cls._parse_cli_args(arg_list)
        values.update(cli_values)

        # 4. Overlay explicit kwargs
        values.update(kwargs)

        return cls(**values)

    @classmethod
    def _load_toml(cls, path: Path | str) -> dict[str, Any]:
        """Load field values from a TOML file.

        The TOML file is organized by sections (e.g., [provider]).
        Fields are matched by their section + field_name.
        """
        path = Path(path)
        if not path.is_file():
            return {}

        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            return {}

        values: dict[str, Any] = {}

        for field_name, field_desc in cls._fields.items():
            section = field_desc.section
            if section and section in data and isinstance(data[section], dict):
                if field_name in data[section]:
                    values[field_name] = data[section][field_name]
            elif field_name in data:
                # Top-level key (no section)
                values[field_name] = data[field_name]

        return values

    @classmethod
    def _load_env(cls) -> dict[str, Any]:
        """Load field values from environment variables."""
        values: dict[str, Any] = {}

        for field_name, field_desc in cls._fields.items():
            if field_desc.env:
                env_val = os.environ.get(field_desc.env)
                if env_val is not None:
                    values[field_name] = env_val

        return values

    @classmethod
    def _parse_cli_args(cls, args: list[str]) -> dict[str, Any]:
        """Parse CLI arguments matching field flags."""
        values: dict[str, Any] = {}

        # Build a map of flag -> field_name
        flag_map: dict[str, str] = {}
        for field_name, field_desc in cls._fields.items():
            for flag in field_desc.flags:
                flag_map[flag] = field_name

        i = 0
        while i < len(args):
            arg = args[i]
            if arg in flag_map and i + 1 < len(args):
                field_name = flag_map[arg]
                values[field_name] = args[i + 1]
                i += 2
            else:
                i += 1

        return values
