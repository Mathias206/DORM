from django.utils.version import get_version

VERSION = (6, 2, 0, "alpha", 0)

__version__ = get_version(VERSION)


def setup(set_prefix=True):
    """
    Configure the settings and populate the app registry.
    URL script prefix and logging configuration are stripped because the HTTP
    layer is not part of this extraction.
    """
    from django.apps import apps
    from django.conf import settings

    if set_prefix:
        from django.urls import set_script_prefix

        set_script_prefix(
            "/" if settings.FORCE_SCRIPT_NAME is None else settings.FORCE_SCRIPT_NAME
        )
    apps.populate(settings.INSTALLED_APPS)
