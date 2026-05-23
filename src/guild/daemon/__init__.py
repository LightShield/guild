"""Daemon module — background agent execution and supervision.

Submodules are intentionally not imported here. The daemon runner is executed
with ``python -m guild.daemon.run``, and eager re-exports can create circular
imports while Python initializes the package before the submodule.
"""

__all__: list[str] = []
