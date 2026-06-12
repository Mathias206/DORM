import pytest
from django.db import connection, transaction
from .models import Author, Book, Tag

_tables_created = False


def _create_tables():
    global _tables_created
    if _tables_created:
        return
    existing = set(connection.introspection.table_names())
    with connection.schema_editor() as editor:
        for model in (Author, Tag, Book):
            if model._meta.db_table not in existing:
                editor.create_model(model)
    _tables_created = True


@pytest.fixture(scope='session', autouse=True)
def setup_tables():
    _create_tables()


@pytest.fixture(autouse=True)
def db():
    yield
    # Clean up data between tests.
    Book.objects.all().delete()
    Tag.objects.all().delete()
    Author.objects.all().delete()


def test_create_and_query(db):
    a = Author.objects.create(name='Alice', email='alice@example.com')
    Book.objects.create(title='Deep Work', author=a)
    assert Book.objects.filter(author__name='Alice').count() == 1


def test_select_related(db):
    a = Author.objects.create(name='Bob', email='bob@example.com')
    Book.objects.create(title='Test Book', author=a)
    book = Book.objects.select_related('author').first()
    assert book.author.name == 'Bob'


def test_m2m(db):
    a = Author.objects.create(name='Carol', email='carol@example.com')
    t = Tag.objects.create(name='python')
    b = Book.objects.create(title='Python Tricks', author=a)
    b.tags.add(t)
    assert Book.objects.filter(tags__name='python').count() == 1


def test_annotate(db):
    from django.db.models import Count
    a = Author.objects.create(name='Dave', email='dave@example.com')
    Book.objects.create(title='Book 1', author=a)
    Book.objects.create(title='Book 2', author=a)
    result = Author.objects.annotate(book_count=Count('books')).get(pk=a.pk)
    assert result.book_count == 2
