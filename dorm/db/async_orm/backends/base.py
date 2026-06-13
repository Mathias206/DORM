"""Async database backend protocol."""

from __future__ import annotations

from typing import Any, Protocol


class AsyncBackend(Protocol):
    """Minimal interface an async database backend must provide."""

    async def connect(self) -> Any:
        """Open and return a raw async connection."""
        ...

    async def close(self, conn: Any) -> None:
        """Close the raw connection."""
        ...

    async def execute(self, conn: Any, sql: str, params: tuple | list | None) -> Any:
        """Execute ``sql`` with ``params`` and return a raw cursor/result."""
        ...

    async def fetchone(self, cursor: Any) -> tuple | None:
        """Return one row from the cursor."""
        ...

    async def fetchall(self, cursor: Any) -> list[tuple]:
        """Return all remaining rows from the cursor."""
        ...

    def rowcount(self, cursor: Any) -> int:
        """Number of rows produced or affected by the last statement."""
        ...

    def lastrowid(self, cursor: Any) -> int | None:
        """Last inserted row id, if any."""
        ...

    def description(self, cursor: Any) -> list[tuple] | None:
        """Cursor description metadata."""
        ...

    async def close_cursor(self, cursor: Any) -> None:
        """Close a cursor/result object when done."""
        ...
