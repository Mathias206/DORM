"""Integration tests for the asyncpg PostgreSQL backend.

These tests are skipped unless ``ASYNC_POSTGRESQL_URL`` (or
``ASYNC_POSTGRESQL_TEST_DB``) is set in the environment.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone as dt_timezone

import pytest

from django.db.async_orm import AsyncDatabase
from django.db.models.sql.constants import MULTI, ROW_COUNT, SINGLE
from django.db.models.sql.subqueries import DeleteQuery, InsertQuery, UpdateQuery
from django.db.models.query_utils import Q

from tests_ours.models import Author, Book, PGThing, Tag

pytestmark = pytest.mark.asyncio

POSTGRESQL_URL = os.environ.get(
    "ASYNC_POSTGRESQL_TEST_DB", os.environ.get("ASYNC_POSTGRESQL_URL")
)

skip_if_no_postgres = pytest.mark.skipif(
    not POSTGRESQL_URL, reason="No PostgreSQL URL configured"
)


@pytest.fixture
async def pg_db():
    db = AsyncDatabase(POSTGRESQL_URL)
    async with db.session() as session:
        await session.execute("DROP TABLE IF EXISTS tests_ours_book_tags CASCADE")
        await session.execute("DROP TABLE IF EXISTS tests_ours_book CASCADE")
        await session.execute("DROP TABLE IF EXISTS tests_ours_author CASCADE")
        await session.execute("DROP TABLE IF EXISTS tests_ours_tag CASCADE")
        await session.execute("DROP TABLE IF EXISTS tests_ours_pgthing CASCADE")

        await session.execute(
            '''CREATE TABLE tests_ours_author (
                id serial PRIMARY KEY,
                name varchar(200) NOT NULL,
                email varchar(254) NOT NULL UNIQUE,
                created_at timestamp with time zone NOT NULL
            )'''
        )
        await session.execute(
            '''CREATE TABLE tests_ours_book (
                id serial PRIMARY KEY,
                title varchar(200) NOT NULL,
                author_id integer NOT NULL REFERENCES tests_ours_author(id),
                published date NULL
            )'''
        )
        await session.execute(
            '''CREATE TABLE tests_ours_tag (
                id serial PRIMARY KEY,
                name varchar(50) NOT NULL UNIQUE
            )'''
        )
        await session.execute(
            '''CREATE TABLE tests_ours_book_tags (
                id serial PRIMARY KEY,
                book_id integer NOT NULL REFERENCES tests_ours_book(id),
                tag_id integer NOT NULL REFERENCES tests_ours_tag(id)
            )'''
        )
        await session.execute(
            '''CREATE TABLE tests_ours_pgthing (
                id serial PRIMARY KEY,
                data jsonb NOT NULL,
                addr inet NULL
            )'''
        )
    try:
        yield db
    finally:
        async with db.session() as session:
            await session.execute("DROP TABLE IF EXISTS tests_ours_book_tags CASCADE")
            await session.execute("DROP TABLE IF EXISTS tests_ours_book CASCADE")
            await session.execute("DROP TABLE IF EXISTS tests_ours_author CASCADE")
            await session.execute("DROP TABLE IF EXISTS tests_ours_tag CASCADE")
            await session.execute("DROP TABLE IF EXISTS tests_ours_pgthing CASCADE")
        await db.close()


async def test_placeholder_conversion():
    """The backend rewrites Django %s placeholders to $1..$N."""
    from django.db.async_orm.backends.postgresql import AsyncPostgreSQLBackend

    backend = AsyncPostgreSQLBackend("postgresql://localhost/test")
    assert backend._convert_placeholders("SELECT * FROM t WHERE x = %s AND y = %s") == (
        "SELECT * FROM t WHERE x = $1 AND y = $2"
    )
    # Escaped percent literals survive conversion.
    assert backend._convert_placeholders("SELECT '100%%' WHERE x = %s") == (
        "SELECT '100%' WHERE x = $1"
    )


@skip_if_no_postgres
async def test_async_session_roundtrip(pg_db):
    async with pg_db.session() as session:
        await session.execute(
            "INSERT INTO tests_ours_author (name, email, created_at) VALUES ($1, $2, $3)",
            ("Alice", "alice@example.com", datetime.now(dt_timezone.utc)),
        )
        result = await session.execute(
            "SELECT name FROM tests_ours_author WHERE email = $1", ("alice@example.com",)
        )
        rows = await result.fetchall()
        assert rows == [("Alice",)]


@skip_if_no_postgres
async def test_async_compiler_insert_update_delete(pg_db):
    async with pg_db.session() as session:
        # INSERT with RETURNING
        query = InsertQuery(Author)
        obj = Author(name="Alice", email="alice@example.com")
        query.insert_values(Author._meta.local_concrete_fields[1:], [obj])
        compiler = query.get_compiler(connection=session.connection)
        compiler.using = "default"
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
        compiler = query.get_compiler(connection=session.connection)
        compiler.using = "default"
        updated = await compiler.execute_sql_async(ROW_COUNT, session=session)
        assert updated == 1

        # DELETE
        query = DeleteQuery(Author)
        query.add_q(Q(pk=pk))
        compiler = query.get_compiler(connection=session.connection)
        compiler.using = "default"
        deleted = await compiler.execute_sql_async(ROW_COUNT, session=session)
        assert deleted == 1


@skip_if_no_postgres
async def test_async_queryset_crud(pg_db):
    async with pg_db.session() as session:
        author = await Author.objects.acreate(
            session, name="Alice", email="alice@example.com"
        )
        assert author.pk == 1

        fetched = await Author.objects.aget(session, pk=author.pk)
        assert fetched.name == "Alice"

        assert await Author.objects.acount(session) == 1
        assert await Author.objects.aexists(session)

        updated = await Author.objects.filter(pk=author.pk).aupdate(
            session, name="Alicia"
        )
        assert updated == 1

        await fetched.arefresh_from_db(session)
        assert fetched.name == "Alicia"

        deleted, _ = await Author.objects.filter(pk=author.pk).adelete(session)
        assert deleted == 1
        assert await Author.objects.acount(session) == 0


@skip_if_no_postgres
async def test_async_bulk_create(pg_db):
    async with pg_db.session() as session:
        objs = [
            Author(name="Alice", email="alice@example.com"),
            Author(name="Bob", email="bob@example.com"),
            Author(name="Carol", email="carol@example.com"),
        ]
        created = await Author.objects.abulk_create(session, objs)
        assert len(created) == 3
        assert {a.pk for a in created} == {1, 2, 3}
        assert await Author.objects.acount(session) == 3


@skip_if_no_postgres
async def test_async_transactions_and_savepoints(pg_db):
    async with pg_db.session() as session:
        async with session.atomic():
            await Author.objects.acreate(
                session, name="Alice", email="alice@example.com"
            )
            try:
                async with session.atomic():
                    await Author.objects.acreate(
                        session, name="Bob", email="bob@example.com"
                    )
                    # Rollback the inner savepoint.
                    raise RuntimeError("rollback inner")
            except RuntimeError:
                pass
        assert await Author.objects.acount(session) == 1


@skip_if_no_postgres
async def test_async_json_and_ip(pg_db):
    async with pg_db.session() as session:
        thing = await PGThing.objects.acreate(
            session, data={"key": [1, 2, 3]}, addr="192.168.1.1"
        )
        fetched = await PGThing.objects.aget(session, pk=thing.pk)
        assert fetched.data == {"key": [1, 2, 3]}
        assert fetched.addr == "192.168.1.1"


@skip_if_no_postgres
async def test_async_select_related_and_lookups(pg_db):
    async with pg_db.session() as session:
        author = await Author.objects.acreate(
            session, name="Alice", email="alice@example.com"
        )
        await Book.objects.acreate(
            session, title="Deep Work", author=author, published=None
        )

        book = await Book.objects.select_related("author").aget(session, title="Deep Work")
        assert book.author.name == "Alice"

        authors = [
            a async for a in Author.objects.filter(name__startswith="A").aall(session)
        ]
        assert len(authors) == 1
