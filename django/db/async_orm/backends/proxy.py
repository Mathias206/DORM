"""Lightweight connection proxy used by the async SQL compiler."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone


class AsyncDatabaseConnectionProxy:
    """
    Stand-in for a Django ``DatabaseWrapper`` during async query compilation.

    The SQL compiler only needs a small subset of the wrapper interface:
    ``vendor``, ``alias``, ``ops``, ``features``, ``data_types``,
    ``data_type_check_constraints``, ``data_types_suffix``, ``DatabaseError``,
    ``get_autocommit()``, ``display_name``, and a couple of timezone helpers.
    This proxy provides those by delegating operations/features construction
    to the active async backend.
    """

    def __init__(self, session: Any, alias: str):
        self._session = session
        self._backend = session._backend
        self.alias = alias

        self.vendor = self._backend.vendor
        self.display_name = self._backend.display_name

        self.ops = self._backend.create_operations(self)
        self.features = self._backend.create_features(self)

        self.data_types = self._backend.data_types
        self.data_type_check_constraints = self._backend.data_type_check_constraints
        self.data_types_suffix = self._backend.data_types_suffix

        self.operators = self._backend.operators
        self.pattern_ops = self._backend.pattern_ops
        self.pattern_esc = self._backend.pattern_esc

        self.DatabaseError = DatabaseError

    def get_autocommit(self) -> bool:
        # asyncpg/aiosqlite are in autocommit mode until AsyncSession.atomic()
        # explicitly issues BEGIN. Reflect that so select_for_update checks are
        # consistent with the actual session state.
        return getattr(self._session, "_atomic_nesting", 0) == 0

    @property
    def timezone(self):
        if settings.USE_TZ:
            return timezone.get_current_timezone()
        return None

    @property
    def timezone_name(self) -> str:
        if settings.USE_TZ:
            return "UTC"
        return settings.TIME_ZONE
