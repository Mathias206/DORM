"""asyncpg backend for the async ORM."""

from __future__ import annotations

import ipaddress
import itertools
import json
from functools import partial
from typing import Any

import asyncpg
from dorm.conf import settings
from dorm.utils.regex_helper import _lazy_re_compile

_FORMAT_DOLLAR_REGEX = _lazy_re_compile(r"(?<!%)%s")


class _AsyncpgResult:
    """Wrapper exposing a DB-API-ish interface over asyncpg results."""

    def __init__(self, rows=None, status=None):
        self._rows = rows or []
        self._status = status or ""
        self._idx = 0
        self._description = None

    @staticmethod
    def _to_tuple(row):
        # asyncpg.Record supports sequence access; normalize to tuples for the
        # Django results_iter machinery.
        return tuple(row)

    async def fetchone(self) -> tuple | None:
        if self._idx >= len(self._rows):
            return None
        row = self._rows[self._idx]
        self._idx += 1
        return self._to_tuple(row)

    async def fetchall(self) -> list[tuple]:
        rows = [self._to_tuple(row) for row in self._rows[self._idx :]]
        self._idx = len(self._rows)
        return rows

    async def close(self) -> None:
        pass

    @property
    def rowcount(self) -> int:
        if self._rows:
            return len(self._rows)
        parts = self._status.split()
        if parts and parts[-1].isdigit():
            return int(parts[-1])
        return 0

    @property
    def lastrowid(self) -> int | None:
        return None

    @property
    def description(self) -> list[tuple] | None:
        return self._description


class AsyncPostgreSQLBackend:
    """Async backend backed by ``asyncpg`` with connection pooling."""

    vendor = "postgresql"
    display_name = "PostgreSQL"

    @property
    def data_types(self):
        from dorm.db.backends.postgresql.base import DatabaseWrapper

        return DatabaseWrapper.data_types

    @property
    def data_type_check_constraints(self):
        from dorm.db.backends.postgresql.base import DatabaseWrapper

        return DatabaseWrapper.data_type_check_constraints

    @property
    def data_types_suffix(self):
        from dorm.db.backends.postgresql.base import DatabaseWrapper

        return DatabaseWrapper.data_types_suffix

    @property
    def operators(self):
        from dorm.db.backends.postgresql.base import DatabaseWrapper

        return DatabaseWrapper.operators

    @property
    def pattern_ops(self):
        from dorm.db.backends.postgresql.base import DatabaseWrapper

        return DatabaseWrapper.pattern_ops

    @property
    def pattern_esc(self):
        from dorm.db.backends.postgresql.base import DatabaseWrapper

        return DatabaseWrapper.pattern_esc

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)
        return self._pool

    async def connect(self) -> asyncpg.Connection:
        pool = await self._ensure_pool()
        conn = await pool.acquire()
        await self._init_connection_state(conn)
        return conn

    async def close(self, conn: asyncpg.Connection) -> None:
        if self._pool is not None:
            await self._pool.release(conn)

    async def close_pool(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _init_connection_state(self, conn: asyncpg.Connection) -> None:
        # Match Django's sync backend: set the session time zone.
        if settings.USE_TZ:
            tz_name = "UTC"
        else:
            tz_name = settings.TIME_ZONE
        if tz_name:
            await conn.execute(f"SET TIME ZONE '{tz_name}'")

    @staticmethod
    def _convert_placeholders(sql: str) -> str:
        counter = itertools.count(1)

        def repl(match):
            return f"${next(counter)}"

        sql = _FORMAT_DOLLAR_REGEX.sub(repl, sql)
        return sql.replace("%%", "%")

    async def execute(
        self, conn: asyncpg.Connection, sql: str, params: tuple | list | None
    ) -> _AsyncpgResult:
        if params is None:
            params = ()
        sql = self._convert_placeholders(sql)
        stripped = sql.lstrip()[:6].upper()
        is_returning = "RETURNING" in sql.upper()
        if is_returning or stripped in ("SELECT", "WITH", "EXPLAIN", "VALUES"):
            rows = await conn.fetch(sql, *params)
            return _AsyncpgResult(rows=rows)
        status = await conn.execute(sql, *params)
        return _AsyncpgResult(status=status)

    async def fetchone(self, result: _AsyncpgResult) -> tuple | None:
        return await result.fetchone()

    async def fetchall(self, result: _AsyncpgResult) -> list[tuple]:
        return await result.fetchall()

    def rowcount(self, result: _AsyncpgResult) -> int:
        return result.rowcount

    def lastrowid(self, result: _AsyncpgResult) -> int | None:
        return result.lastrowid

    def description(self, result: _AsyncpgResult) -> list[tuple] | None:
        return result.description

    async def close_cursor(self, result: _AsyncpgResult) -> None:
        await result.close()

    @staticmethod
    def create_operations(connection):
        from dorm.db.backends.postgresql.operations import DatabaseOperations

        class AsyncPostgreSQLOperations(DatabaseOperations):
            def __init__(self, connection):
                super().__init__(connection)

            def __del__(self):
                # Avoid reference-cycle GC issues caused by BaseDatabaseOperations.__del__.
                pass

            def adapt_integerfield_value(self, value, internal_type):
                if value is None or hasattr(value, "resolve_expression"):
                    return value
                return int(value)

            def adapt_json_value(self, value, encoder):
                if value is None:
                    return None
                dumps = json.dumps if encoder is None else partial(json.dumps, cls=encoder)
                return dumps(value)

            def adapt_ipaddressfield_value(self, value):
                if value:
                    return ipaddress.ip_address(value)
                return None

            def last_insert_id(self, cursor, table_name, pk_name):
                # RETURNING is the normal path; asyncpg has no lastrowid.
                return None

            def get_db_converters(self, expression):
                converters = super().get_db_converters(expression)
                if expression.output_field.get_internal_type() == "GenericIPAddressField":
                    converters.append(self.convert_ipaddressfield_value)
                return converters

            def convert_ipaddressfield_value(self, value, expression, connection):
                if value is not None and not isinstance(value, str):
                    return str(value)
                return value

        return AsyncPostgreSQLOperations(connection)

    @staticmethod
    def create_features(connection):
        from dorm.db.backends.postgresql.features import DatabaseFeatures

        class AsyncPostgreSQLFeatures(DatabaseFeatures):
            def __init__(self, connection):
                self.connection = connection

            # asyncpg is always server-side bound.
            max_query_params = 2**16 - 1

            @property
            def uses_server_side_binding(self):
                return False

            @property
            def django_test_skips(self):
                return {}

            @property
            def django_test_expected_failures(self):
                return set()

        return AsyncPostgreSQLFeatures(connection)
