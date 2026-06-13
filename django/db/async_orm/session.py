"""AsyncSession and AsyncDatabase — the public async database API."""

from __future__ import annotations

from typing import Any

from .backends.sqlite import AsyncSQLiteBackend


class AsyncResult:
    """Wrapper around a backend-specific async cursor/result."""

    def __init__(self, raw: Any, backend: Any):
        self._raw = raw
        self._backend = backend

    async def fetchone(self) -> tuple | None:
        return await self._backend.fetchone(self._raw)

    async def fetchall(self) -> list[tuple]:
        return await self._backend.fetchall(self._raw)

    @property
    def rowcount(self) -> int:
        return self._backend.rowcount(self._raw)

    @property
    def lastrowid(self) -> int | None:
        return self._backend.lastrowid(self._raw)

    @property
    def description(self) -> list[tuple] | None:
        return self._backend.description(self._raw)

    async def close(self) -> None:
        await self._backend.close_cursor(self._raw)


class AsyncSession:
    """Explicit, scoped async database session."""

    def __init__(self, backend: Any):
        self._backend = backend
        self._conn: Any = None

    async def _ensure_connection(self) -> None:
        if self._conn is None:
            self._conn = await self._backend.connect()

    async def execute(self, sql: str, params: tuple | list | None = None) -> AsyncResult:
        await self._ensure_connection()
        raw_cursor = await self._backend.execute(self._conn, sql, params)
        return AsyncResult(raw_cursor, self._backend)

    async def commit(self) -> None:
        if self._conn is not None:
            await self._conn.commit()

    async def rollback(self) -> None:
        if self._conn is not None:
            await self._conn.rollback()

    async def close(self) -> None:
        if self._conn is not None:
            await self._backend.close(self._conn)
            self._conn = None

    async def __aenter__(self) -> "AsyncSession":
        await self._ensure_connection()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.close()


class AsyncDatabase:
    """Factory for async sessions from a connection URL."""

    def __init__(self, url: str):
        self._backend = self._backend_from_url(url)

    def session(self) -> AsyncSession:
        return AsyncSession(self._backend)

    @staticmethod
    def _backend_from_url(url: str) -> Any:
        if url.startswith("sqlite+aiosqlite://"):
            rest = url[len("sqlite+aiosqlite://") :]
            if rest == ":memory:":
                path = ":memory:"
            else:
                # Path may start with /// or //host/; keep it simple.
                path = rest.lstrip("/")
                if not path:
                    path = ":memory:"
            return AsyncSQLiteBackend(path)
        raise ValueError(f"Unsupported async database URL: {url!r}")
