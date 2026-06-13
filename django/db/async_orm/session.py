"""AsyncSession and AsyncDatabase — the public async database API."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
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


class _AtomicContext(AbstractAsyncContextManager):
    """Async transaction/savepoint context manager for AsyncSession."""

    def __init__(self, session: "AsyncSession"):
        self._session = session

    async def __aenter__(self):
        session = self._session
        await session._ensure_connection()
        if session._atomic_nesting == 0:
            await session.execute("BEGIN")
        else:
            await session.execute(f"SAVEPOINT _asp_{session._atomic_nesting}")
        session._atomic_nesting += 1
        return session

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        session = self._session
        session._atomic_nesting -= 1
        if exc_type is None:
            if session._atomic_nesting == 0:
                await session.execute("COMMIT")
            else:
                await session.execute(f"RELEASE SAVEPOINT _asp_{session._atomic_nesting}")
        else:
            if session._atomic_nesting == 0:
                await session.execute("ROLLBACK")
            else:
                await session.execute(f"ROLLBACK TO SAVEPOINT _asp_{session._atomic_nesting}")


class AsyncSession:
    """Explicit, scoped async database session."""

    def __init__(self, backend: Any):
        self._backend = backend
        self._conn: Any = None
        self._atomic_nesting = 0

    async def _ensure_connection(self) -> None:
        if self._conn is None:
            self._conn = await self._backend.connect()

    def atomic(self) -> _AtomicContext:
        """Return an async context manager that begins/commits or rolls back a transaction.

        Nesting is implemented with SAVEPOINT/RELEASE SAVEPOINT.
        """
        return _AtomicContext(self)

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
                # sqlite+aiosqlite:///absolute/path -> rest is /absolute/path
                path = rest[1:] if rest.startswith("/") else rest
                if not path:
                    path = ":memory:"
            return AsyncSQLiteBackend(path)
        raise ValueError(f"Unsupported async database URL: {url!r}")
