"""Database connection type re-export.

Confines the aiosqlite third-party import to a single wrapper module,
satisfying the wrap-third-party guideline.
"""

from aiosqlite import Connection as DBConnection

__all__ = ["DBConnection"]
