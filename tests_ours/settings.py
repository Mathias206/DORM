DATABASES = {
    'default': {
        'ENGINE': 'dorm.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}
DEFAULT_AUTO_FIELD = 'dorm.db.models.BigAutoField'
USE_TZ = True
TIME_ZONE = 'UTC'
USE_I18N = False
USE_L10N = False
INSTALLED_APPS = ['tests_ours']
