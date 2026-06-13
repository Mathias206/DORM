"""aiosqlite backend for the async ORM."""

from __future__ import annotations

from typing import Any

import aiosqlite
from django.utils.regex_helper import _lazy_re_compile

_FORMAT_QMARK_REGEX = _lazy_re_compile(r"(?<!%)%s")


class AsyncSQLiteBackend:
    """Async backend backed by ``aiosqlite``."""

    def __init__(self, path: str):
        self.path = path

    async def connect(self) -> aiosqlite.Connection:
        # isolation_level=None gives us explicit transaction control.
        return await aiosqlite.connect(self.path, isolation_level=None)

    async def close(self, conn: aiosqlite.Connection) -> None:
        await conn.close()

    async def execute(
        self, conn: aiosqlite.Connection, sql: str, params: tuple | list | None
    ) -> aiosqlite.Cursor:
        if params is None:
            params = ()
        # Django generates "format" style placeholders, but sqlite3 expects
        # "qmark" style. Mirror django.db.backends.sqlite3.SQLiteCursorWrapper.
        sql = _FORMAT_QMARK_REGEX.sub("?", sql).replace("%%", "%")
        return await conn.execute(sql, params)

    async def fetchone(self, cursor: aiosqlite.Cursor) -> tuple | None:
        return await cursor.fetchone()

    async def fetchall(self, cursor: aiosqlite.Cursor) -> list[tuple]:
        return await cursor.fetchall()

    def rowcount(self, cursor: aiosqlite.Cursor) -> int:
        return cursor.rowcount

    def lastrowid(self, cursor: aiosqlite.Cursor) -> int | None:
        return cursor.lastrowid

    def description(self, cursor: aiosqlite.Cursor) -> list[tuple] | None:
        return cursor.description

    async def close_cursor(self, cursor: aiosqlite.Cursor) -> None:
        await cursor.close()
