# Test settings for the extracted Django ORM test suite.

DATABASES = {
    "default": {
        "ENGINE": "dorm.db.backends.sqlite3",
    },
    "other": {
        "ENGINE": "dorm.db.backends.sqlite3",
    },
}

SECRET_KEY = "django_tests_secret_key"
USE_TZ = False
