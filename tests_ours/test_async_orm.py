"""Phase 0/1 tests for the async-native ORM backend and compiler."""

import pytest
from django.db.models.sql.subqueries import DeleteQuery, InsertQuery, UpdateQuery
from django.db.models.query_utils import Q

from django.db.async_orm import AsyncDatabase
from django.db.models.sql.constants import MULTI, ROW_COUNT

from .models import Author


@pytest.mark.asyncio
async def test_async_session_roundtrip():
    db = AsyncDatabase("sqlite+aiosqlite:///:memory:")
    async with db.session() as session:
        await session.execute(
            "CREATE TABLE demo (id INTEGER PRIMARY KEY, name TEXT)"
        )
        await session.execute("INSERT INTO demo (name) VALUES (?)", ("Alice",))
        result = await session.execute(
            "SELECT * FROM demo WHERE name = ?", ("Alice",)
        )
        row = await result.fetchone()
        assert row == (1, "Alice")


@pytest.mark.asyncio
async def test_async_session_lastrowid_and_fetchall():
    db = AsyncDatabase("sqlite+aiosqlite:///:memory:")
    async with db.session() as session:
        await session.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, value INTEGER)"
        )
        r1 = await session.execute(
            "INSERT INTO items (value) VALUES (?)", (10,)
        )
        assert r1.lastrowid == 1
        await session.execute("INSERT INTO items (value) VALUES (?)", (20,))
        result = await session.execute("SELECT * FROM items ORDER BY id")
        rows = await result.fetchall()
        assert rows == [(1, 10), (2, 20)]


@pytest.mark.asyncio
async def test_async_compiler_select():
    db = AsyncDatabase("sqlite+aiosqlite:///:memory:")
    async with db.session() as session:
        await session.execute(
            """
            CREATE TABLE tests_ours_author (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(200) NOT NULL,
                email VARCHAR(254) NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
        await session.execute(
            "INSERT INTO tests_ours_author (name, email, created_at) VALUES (?, ?, ?)",
            ("Alice", "alice@example.com", "2024-01-01 00:00:00"),
        )
        await session.execute(
            "INSERT INTO tests_ours_author (name, email, created_at) VALUES (?, ?, ?)",
            ("Bob", "bob@example.com", "2024-01-01 00:00:00"),
        )

        compiler = Author.objects.all().query.get_compiler(using="default")
        chunks = await compiler.execute_sql_async(MULTI, session=session)
        rows = list(compiler.results_iter(chunks))
        assert len(rows) == 2
        assert {row[1] for row in rows} == {"Alice", "Bob"}


@pytest.mark.asyncio
async def test_async_compiler_insert_update_delete():
    db = AsyncDatabase("sqlite+aiosqlite:///:memory:")
    async with db.session() as session:
        await session.execute(
            """
            CREATE TABLE tests_ours_author (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(200) NOT NULL,
                email VARCHAR(254) NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )

        # INSERT
        query = InsertQuery(Author)
        obj = Author(name="Alice", email="alice@example.com")
        query.insert_values(Author._meta.local_concrete_fields[1:], [obj])
        compiler = query.get_compiler(using="default")
        rows = await compiler.execute_sql_async(
            returning_fields=[Author._meta.pk], session=session
        )
        assert len(rows) == 1
        pk = rows[0][0]
        assert pk == 1

        # UPDATE
        query = UpdateQuery(Author)
        query.add_update_values({"name": "Alicia"})
        query.add_q(Q(pk=pk))
        compiler = query.get_compiler(using="default")
        updated = await compiler.execute_sql_async(ROW_COUNT, session=session)
        assert updated == 1

        # Verify update
        compiler = Author.objects.filter(pk=pk).query.get_compiler(using="default")
        chunks = await compiler.execute_sql_async(MULTI, session=session)
        rows = list(compiler.results_iter(chunks))
        assert rows[0][1] == "Alicia"

        # DELETE
        query = DeleteQuery(Author)
        query.add_q(Q(pk=pk))
        compiler = query.get_compiler(using="default")
        deleted = await compiler.execute_sql_async(ROW_COUNT, session=session)
        assert deleted == 1

        compiler = Author.objects.all().query.get_compiler(using="default")
        chunks = await compiler.execute_sql_async(MULTI, session=session)
        rows = list(compiler.results_iter(chunks))
        assert rows == []
