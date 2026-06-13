from django.db import DEFAULT_DB_ALIAS


class TestRouter:
    """Primary/other router for select_for_update tests."""

    def db_for_read(self, model, instance=None, **hints):
        if instance:
            return instance._state.db or "other"
        return "other"

    def db_for_write(self, model, **hints):
        return DEFAULT_DB_ALIAS

    def allow_relation(self, obj1, obj2, **hints):
        return obj1._state.db in ("default", "other") and obj2._state.db in (
            "default",
            "other",
        )

    def allow_migrate(self, db, app_label, **hints):
        return True
