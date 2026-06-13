"""ORM-only setting_changed receivers."""

from django.conf import settings
from django.core.signals import setting_changed
from django.db import connections, router
from django.db.utils import ConnectionRouter
from django.utils import timezone


def clear_routers_cache(*, setting, **kwargs):
    if setting == "DATABASE_ROUTERS":
        router.routers = ConnectionRouter().routers


def update_connections_time_zone(*, setting, **kwargs):
    if setting == "TIME_ZONE":
        timezone.get_default_timezone.cache_clear()
    if setting in {"TIME_ZONE", "USE_TZ"}:
        for conn in connections.all(initialized_only=True):
            for attr in ("timezone", "timezone_name"):
                try:
                    delattr(conn, attr)
                except AttributeError:
                    pass
            conn.ensure_timezone()


setting_changed.connect(clear_routers_cache)
setting_changed.connect(update_connections_time_zone)
