import dorm
from dorm.conf import settings as django_settings


def pytest_configure():
    import tests_ours.settings as s
    if not django_settings.configured:
        django_settings.configure(
            DATABASES=s.DATABASES,
            DEFAULT_AUTO_FIELD=s.DEFAULT_AUTO_FIELD,
            USE_TZ=s.USE_TZ,
            TIME_ZONE=s.TIME_ZONE,
            USE_I18N=s.USE_I18N,
            USE_L10N=s.USE_L10N,
            INSTALLED_APPS=s.INSTALLED_APPS,
        )
    dorm.setup()
