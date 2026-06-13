"""Phase 0/1/2 tests for the async-native ORM backend, compiler, and reads."""

from datetime import datetime

import pytest
from dorm.db.models.sql.constants import MULTI, ROW_COUNT
from dorm.db.models.sql.subqueries import DeleteQuery, InsertQuery, UpdateQuery
from dorm.db.models.query_utils import Q

from dorm.db.async_orm import AsyncDatabase
from tests_ours.models import Author, Book


def _db():
    return AsyncDatabase("sqlite+aiosqlite:///:memory:")


async def _create_author_table(session):
    await session.execute(
        '''
        CREATE TABLE "tests_ours_author" (
            "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
            "name" varchar(200) NOT NULL,
            "email" varchar(254) NOT NULL UNIQUE,
            "created_at" datetime NOT NULL
        )
        '''
    )


async def _create_book_table(session):
    await session.execute(
        '''
        CREATE TABLE "tests_ours_book" (
            "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
            "title" varchar(200) NOT NULL,
            "author_id" bigint NOT NULL REFERENCES "tests_ours_author" ("id"),
            "published" date NULL
        )
        '''
    )


async def _insert_author(session, name, email):
    result = await session.execute(
        '''INSERT INTO tests_ours_author (name, email, created_at)
           VALUES (?, ?, ?)''',
        (name, email, datetime.utcnow().isoformat()),
    )
    return result.lastrowid


@pytest.mark.asyncio
async def test_async_session_roundtrip():
    async with _db().session() as session:
        await session.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, name TEXT)")
        await session.execute("INSERT INTO demo (name) VALUES (?)", ("Alice",))
        result = await session.execute(
            "SELECT * FROM demo WHERE name = ?", ("Alice",)
        )
        row = await result.fetchone()
        assert row == (1, "Alice")


@pytest.mark.asyncio
async def test_async_session_lastrowid_and_fetchall():
    async with _db().session() as session:
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
    async with _db().session() as session:
        await _create_author_table(session)
        await _insert_author(session, "Alice", "alice@example.com")
        await _insert_author(session, "Bob", "bob@example.com")

        compiler = Author.objects.all().query.get_compiler(using="default")
        chunks = await compiler.execute_sql_async(MULTI, session=session)
        rows = list(compiler.results_iter(chunks))
        assert len(rows) == 2
        assert {row[1] for row in rows} == {"Alice", "Bob"}


@pytest.mark.asyncio
async def test_async_compiler_insert_update_delete():
    async with _db().session() as session:
        await _create_author_table(session)

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


@pytest.mark.asyncio
async def test_async_queryset_get():
    async with _db().session() as session:
        await _create_author_table(session)
        pk = await _insert_author(session, "Alice", "alice@example.com")

        author = await Author.objects.aget(session, pk=pk)
        assert author.name == "Alice"

        with pytest.raises(Author.DoesNotExist):
            await Author.objects.aget(session, pk=999)


@pytest.mark.asyncio
async def test_async_queryset_first_last_all():
    async with _db().session() as session:
        await _create_author_table(session)
        await _insert_author(session, "Alice", "alice@example.com")
        await _insert_author(session, "Bob", "bob@example.com")
        await _insert_author(session, "Carol", "carol@example.com")

        first = await Author.objects.afirst(session)
        assert first.name == "Alice"

        last = await Author.objects.alast(session)
        # Default ordering is by pk ascending, so reverse -> Carol.
        assert last.name == "Carol"

        names = [a.name async for a in Author.objects.aall(session)]
        assert names == ["Alice", "Bob", "Carol"]

        filtered = [a.name async for a in Author.objects.filter(name__startswith="A").aall(session)]
        assert filtered == ["Alice"]


@pytest.mark.asyncio
async def test_async_queryset_count_exists():
    async with _db().session() as session:
        await _create_author_table(session)
        await _insert_author(session, "Alice", "alice@example.com")
        await _insert_author(session, "Bob", "bob@example.com")

        assert await Author.objects.acount(session) == 2
        assert await Author.objects.filter(name="Alice").aexists(session) is True
        assert await Author.objects.filter(name="Zoe").aexists(session) is False


@pytest.mark.asyncio
async def test_async_queryset_values_and_values_list():
    async with _db().session() as session:
        await _create_author_table(session)
        await _insert_author(session, "Alice", "alice@example.com")

        rows = [row async for row in Author.objects.values("name", "email").aall(session)]
        assert rows == [{"name": "Alice", "email": "alice@example.com"}]

        rows = [
            row async for row in Author.objects.values_list("name", "email").aall(session)
        ]
        assert rows == [("Alice", "alice@example.com")]

        names = [n async for n in Author.objects.values_list("name", flat=True).aall(session)]
        assert names == ["Alice"]


@pytest.mark.asyncio
async def test_async_queryset_select_related():
    async with _db().session() as session:
        await _create_author_table(session)
        await _create_book_table(session)
        author_pk = await _insert_author(session, "Alice", "alice@example.com")
        await session.execute(
            "INSERT INTO tests_ours_book (title, author_id, published) VALUES (?, ?, ?)",
            ("Deep Work", author_pk, None),
        )

        book = await Book.objects.select_related("author").aget(session, title="Deep Work")
        assert book.title == "Deep Work"
        assert book.author.name == "Alice"


@pytest.mark.asyncio
async def test_async_queryset_aiterator():
    async with _db().session() as session:
        await _create_author_table(session)
        for i in range(5):
            await _insert_author(session, f"Author {i}", f"a{i}@example.com")

        names = [a.name async for a in Author.objects.aiterator(session)]
        assert names == [f"Author {i}" for i in range(5)]


@pytest.mark.asyncio
async def test_async_queryset_acreate():
    async with _db().session() as session:
        await _create_author_table(session)
        author = await Author.objects.acreate(
            session, name="Alice", email="alice@example.com"
        )
        assert author.pk == 1
        assert author.name == "Alice"
        fetched = await Author.objects.aget(session, pk=author.pk)
        assert fetched.email == "alice@example.com"


@pytest.mark.asyncio
async def test_async_model_asave():
    async with _db().session() as session:
        await _create_author_table(session)
        author = Author(name="Alice", email="alice@example.com")
        await author.asave(session)
        assert author.pk == 1

        author.name = "Alicia"
        await author.asave(session)
        fetched = await Author.objects.aget(session, pk=author.pk)
        assert fetched.name == "Alicia"


@pytest.mark.asyncio
async def test_async_queryset_abulk_create():
    async with _db().session() as session:
        await _create_author_table(session)
        objs = [
            Author(name="Alice", email="alice@example.com"),
            Author(name="Bob", email="bob@example.com"),
            Author(name="Carol", email="carol@example.com"),
        ]
        created = await Author.objects.abulk_create(session, objs)
        assert len(created) == 3
        assert {a.pk for a in created} == {1, 2, 3}
        assert await Author.objects.acount(session) == 3


@pytest.mark.asyncio
async def test_async_queryset_aupdate():
    async with _db().session() as session:
        await _create_author_table(session)
        pk = await _insert_author(session, "Alice", "alice@example.com")
        updated = await Author.objects.filter(pk=pk).aupdate(
            session, name="Alicia"
        )
        assert updated == 1
        author = await Author.objects.aget(session, pk=pk)
        assert author.name == "Alicia"


@pytest.mark.asyncio
async def test_async_queryset_adelete():
    async with _db().session() as session:
        await _create_author_table(session)
        await _create_book_table(session)
        pk = await _insert_author(session, "Alice", "alice@example.com")
        deleted, _ = await Author.objects.filter(pk=pk).adelete(session)
        assert deleted == 1
        assert await Author.objects.acount(session) == 0


@pytest.mark.asyncio
async def test_async_model_adelete():
    async with _db().session() as session:
        await _create_author_table(session)
        await _create_book_table(session)
        author = await Author.objects.acreate(
            session, name="Alice", email="alice@example.com"
        )
        await author.adelete(session)
        assert author.pk is None
        assert await Author.objects.acount(session) == 0


@pytest.mark.asyncio
async def test_async_model_arefresh_from_db():
    async with _db().session() as session:
        await _create_author_table(session)
        author = await Author.objects.acreate(
            session, name="Alice", email="alice@example.com"
        )
        await Author.objects.filter(pk=author.pk).aupdate(
            session, name="Alicia"
        )
        await author.arefresh_from_db(session)
        assert author.name == "Alicia"
