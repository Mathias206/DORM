"""aiosqlite backend for the async ORM."""

from __future__ import annotations

from typing import Any

import aiosqlite
from django.utils.regex_helper import _lazy_re_compile

_FORMAT_QMARK_REGEX = _lazy_re_compile(r"(?<!%)%s")


class AsyncSQLiteBackend:
    """Async backend backed by ``aiosqlite``."""

    vendor = "sqlite"
    display_name = "SQLite"

    @property
    def data_types(self):
        from django.db.backends.sqlite3.base import DatabaseWrapper
        return DatabaseWrapper.data_types

    @property
    def data_type_check_constraints(self):
        from django.db.backends.sqlite3.base import DatabaseWrapper
        return DatabaseWrapper.data_type_check_constraints

    @property
    def data_types_suffix(self):
        from django.db.backends.sqlite3.base import DatabaseWrapper
        return DatabaseWrapper.data_types_suffix

    @property
    def operators(self):
        from django.db.backends.sqlite3.base import DatabaseWrapper
        return DatabaseWrapper.operators

    @property
    def pattern_ops(self):
        from django.db.backends.sqlite3.base import DatabaseWrapper
        return DatabaseWrapper.pattern_ops

    @property
    def pattern_esc(self):
        from django.db.backends.sqlite3.base import DatabaseWrapper
        return DatabaseWrapper.pattern_esc

    def __init__(self, path: str):
        self.path = path

    @staticmethod
    def create_operations(connection):
        from django.db.backends.sqlite3.operations import DatabaseOperations

        class AsyncSQLiteOperations(DatabaseOperations):
            def __init__(self, connection):
                super().__init__(connection)

            def __del__(self):
                # Avoid reference-cycle GC issues caused by BaseDatabaseOperations.__del__.
                pass

        return AsyncSQLiteOperations(connection)

    @staticmethod
    def create_features(connection):
        from django.db.backends.sqlite3.features import DatabaseFeatures

        class AsyncSQLiteFeatures(DatabaseFeatures):
            def __init__(self, connection):
                self.connection = connection

        return AsyncSQLiteFeatures(connection)

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
