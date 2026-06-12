from django.utils.version import get_version

VERSION = (6, 2, 0, "alpha", 0)

__version__ = get_version(VERSION)


def setup():
    """
    Configure the settings and populate the app registry.
    URL script prefix and logging configuration are stripped because the HTTP
    layer is not part of this extraction.
    """
    from django.apps import apps
    from django.conf import settings

    apps.populate(settings.INSTALLED_APPS)
