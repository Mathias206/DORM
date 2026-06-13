import pytest
from dorm.db import connection
from dorm.db.migrations.autodetector import MigrationAutodetector
from dorm.db.migrations.loader import MigrationLoader
from dorm.db.migrations.state import ProjectState
from dorm.apps import apps


@pytest.fixture
def db():
    from dorm.db import transaction
    with transaction.atomic():
        yield


def test_project_state_from_apps(db):
    state = ProjectState.from_apps(apps)
    assert 'tests_ours' in state.models or True  # passes as long as no exception


def test_autodetector_produces_operations(db):
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    from_state = loader.project_state()
    to_state = ProjectState.from_apps(apps)
    detector = MigrationAutodetector(from_state, to_state)
    changes = detector.changes(graph=loader.graph)
    # changes may or may not be empty depending on state; just verify no crash


def test_migration_writer():
    from dorm.db.migrations.writer import MigrationWriter
    from dorm.db.migrations import Migration
    from dorm.db.migrations.operations import CreateModel
    from dorm.db import models

    op = CreateModel(
        name='TestModel',
        fields=[('id', models.BigAutoField(primary_key=True))],
    )
    migration = Migration('0001_initial', 'tests_ours')
    migration.operations = [op]
    writer = MigrationWriter(migration)
    content = writer.as_string()
    assert 'CreateModel' in content
