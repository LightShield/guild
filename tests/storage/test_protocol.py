"""Tests for storage/protocol.py — StorageProtocol structural typing (REQ-06.6)."""

from __future__ import annotations

import inspect

import pytest

from guild.storage.protocol import StorageProtocol
from guild.storage.sqlite import Storage


@pytest.mark.unit
@pytest.mark.req("REQ-06.6")
class TestStorageProtocolStructuralMatch:
    """The concrete Storage class satisfies the StorageProtocol structurally."""

    def test_storage_is_runtime_checkable_instance(self) -> None:
        """Storage passes isinstance check against the runtime_checkable protocol."""
        # StorageProtocol is @runtime_checkable, so isinstance works for method presence
        assert isinstance(Storage.__new__(Storage), StorageProtocol)

    def test_protocol_is_runtime_checkable(self) -> None:
        """StorageProtocol has the runtime_checkable decorator."""
        assert hasattr(StorageProtocol, "__protocol_attrs__") or hasattr(
            StorageProtocol, "__abstractmethods__"
        )

    def test_storage_has_all_protocol_methods(self) -> None:
        """Every method defined on StorageProtocol exists on Storage."""
        protocol_methods = [
            name
            for name, _ in inspect.getmembers(StorageProtocol, predicate=inspect.isfunction)
            if not name.startswith("_")
        ]
        for method_name in protocol_methods:
            assert hasattr(Storage, method_name), (
                f"Storage is missing protocol method: {method_name}"
            )


@pytest.mark.unit
@pytest.mark.req("REQ-06.6")
class TestStorageProtocolMethodSignatures:
    """Protocol method signatures are consistent with Storage implementation."""

    def test_connect_is_async(self) -> None:
        """connect() is an async method on the protocol."""
        assert inspect.iscoroutinefunction(Storage.connect)

    def test_create_task_signature(self) -> None:
        """create_task accepts task_id and description."""
        sig = inspect.signature(Storage.create_task)
        params = list(sig.parameters.keys())
        assert "task_id" in params
        assert "description" in params

    def test_list_tasks_has_optional_status(self) -> None:
        """list_tasks has an optional status parameter."""
        sig = inspect.signature(Storage.list_tasks)
        status_param = sig.parameters.get("status")
        assert status_param is not None
        assert status_param.default is None


@pytest.mark.unit
@pytest.mark.req("REQ-06.6")
class TestProtocolModuleExports:
    """The protocol module exports are correct."""

    def test_all_exports(self) -> None:
        """__all__ contains StorageProtocol."""
        import guild.storage.protocol as mod

        assert "StorageProtocol" in mod.__all__

    def test_non_conforming_class_fails_isinstance(self) -> None:
        """A class missing protocol methods fails the isinstance check."""

        class NotAStorage:
            pass

        assert not isinstance(NotAStorage(), StorageProtocol)
