from dorm.utils.version import get_version

VERSION = (6, 2, 0, "alpha", 0)

__version__ = get_version(VERSION)


def setup():
    """
    Configure the settings and populate the app registry.
    URL script prefix and logging configuration are stripped because the HTTP
    layer is not part of this extraction.
    """
    from dorm.apps import apps
    from dorm.conf import settings

    apps.populate(settings.INSTALLED_APPS)
