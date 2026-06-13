"""
Settings and configuration for Django.

Read values from the module specified by the DJANGO_SETTINGS_MODULE environment
variable, and then from dorm.conf.global_settings; see the global_settings.py
for a list of all possible variables.
"""

import importlib
import os
import time
import warnings
import zoneinfo

from dorm.conf import global_settings
from dorm.core.exceptions import ImproperlyConfigured
from dorm.utils.deprecation import (
    RemovedInDjango70Warning,
    warn_about_external_use,
)
from dorm.utils.functional import LazyObject, empty
from dorm.utils.warnings import django_file_prefixes

ENVIRONMENT_VARIABLE = "DJANGO_SETTINGS_MODULE"
DEFAULT_STORAGE_ALIAS = "default"

# RemovedInDjango70Warning.
USE_BLANK_CHOICE_DASH_DEPRECATED_MSG = (
    "The USE_BLANK_CHOICE_DASH setting is deprecated. If you wish to define "
    "your own default blank choice label, override "
    "dorm.db.models.fields.BLANK_CHOICE_LABEL in your app's ready() method."
)

class SettingsReference(str):
    """
    String subclass which references a current settings value. It's treated as
    the value in memory but serializes to a settings.NAME attribute reference.
    """

    def __new__(self, value, setting_name):
        return str.__new__(self, value)

    def __init__(self, value, setting_name):
        self.setting_name = setting_name


class LazySettings(LazyObject):
    """
    A lazy proxy for either global Django settings or a custom settings object.
    The user can manually configure settings prior to using them. Otherwise,
    Django uses the settings module pointed to by DJANGO_SETTINGS_MODULE.
    """

    def _setup(self, name=None):
        """
        Load the settings module pointed to by the environment variable. This
        is used the first time settings are needed, if the user hasn't
        configured settings manually.
        """
        settings_module = os.environ.get(ENVIRONMENT_VARIABLE)
        if not settings_module:
            desc = ("setting %s" % name) if name else "settings"
            raise ImproperlyConfigured(
                "Requested %s, but settings are not configured. "
                "You must either define the environment variable %s "
                "or call settings.configure() before accessing settings."
                % (desc, ENVIRONMENT_VARIABLE)
            )

        self._wrapped = Settings(settings_module)

    def __repr__(self):
        # Hardcode the class name as otherwise it yields 'Settings'.
        if self._wrapped is empty:
            return "<LazySettings [Unevaluated]>"
        return '<LazySettings "%(settings_module)s">' % {
            "settings_module": self._wrapped.SETTINGS_MODULE,
        }

    def __getattr__(self, name):
        """Return the value of a setting and cache it in self.__dict__."""
        if (_wrapped := self._wrapped) is empty:
            self._setup(name)
            _wrapped = self._wrapped
        val = getattr(_wrapped, name)

        self.__dict__[name] = val
        return val

    def __setattr__(self, name, value):
        """
        Set the value of setting. Clear all cached values if _wrapped changes
        (@override_settings does this) or clear single values when set.
        """
        if name == "_wrapped":
            self.__dict__.clear()
        else:
            self.__dict__.pop(name, None)

        # RemovedInDjango70Warning.
        if name == "USE_BLANK_CHOICE_DASH":
            _show_settings_deprecation_warning(
                USE_BLANK_CHOICE_DASH_DEPRECATED_MSG, RemovedInDjango70Warning
            )

        super().__setattr__(name, value)

    def __delattr__(self, name):
        """Delete a setting and clear it from cache if needed."""
        super().__delattr__(name)
        self.__dict__.pop(name, None)

    def configure(self, default_settings=global_settings, **options):
        """
        Called to manually configure the settings. The 'default_settings'
        parameter sets where to retrieve any unspecified values from (its
        argument must support attribute access (__getattr__)).
        """
        if self._wrapped is not empty:
            raise RuntimeError("Settings already configured.")

        holder = UserSettingsHolder(default_settings)
        for name, value in options.items():
            if not name.isupper():
                raise TypeError("Setting %r must be uppercase." % name)
            setattr(holder, name, value)
        self._wrapped = holder

    @property
    def configured(self):
        """Return True if the settings have already been configured."""
        return self._wrapped is not empty


class Settings:
    def __init__(self, settings_module):
        # update this dict from global settings (but only for ALL_CAPS
        # settings)
        for setting in dir(global_settings):
            if setting.isupper():
                setattr(self, setting, getattr(global_settings, setting))

        # store the settings module in case someone later cares
        self.SETTINGS_MODULE = settings_module

        mod = importlib.import_module(self.SETTINGS_MODULE)

        tuple_settings = (
            "INSTALLED_APPS",
            "LOCALE_PATHS",
        )
        self._explicit_settings = set()
        for setting in dir(mod):
            if setting.isupper():
                setting_value = getattr(mod, setting)

                if setting in tuple_settings and not isinstance(
                    setting_value, (list, tuple)
                ):
                    raise ImproperlyConfigured(
                        "The %s setting must be a list or a tuple." % setting
                    )
                setattr(self, setting, setting_value)
                self._explicit_settings.add(setting)

        # RemovedInDjango70Warning.
        if "USE_BLANK_CHOICE_DASH" in self._explicit_settings:
            warnings.warn(
                USE_BLANK_CHOICE_DASH_DEPRECATED_MSG,
                RemovedInDjango70Warning,
                skip_file_prefixes=django_file_prefixes(),
            )

        if hasattr(time, "tzset") and self.TIME_ZONE:
            try:
                zoneinfo.ZoneInfo(self.TIME_ZONE)
            except zoneinfo.ZoneInfoNotFoundError:
                raise ValueError("Incorrect timezone setting: %s" % self.TIME_ZONE)
            # Move the time zone info into os.environ. See ticket #2315 for why
            # we don't do this unconditionally (breaks Windows).
            os.environ["TZ"] = self.TIME_ZONE
            time.tzset()

    def is_overridden(self, setting):
        return setting in self._explicit_settings

    def __repr__(self):
        return '<%(cls)s "%(settings_module)s">' % {
            "cls": self.__class__.__name__,
            "settings_module": self.SETTINGS_MODULE,
        }


class UserSettingsHolder:
    """Holder for user configured settings."""

    # SETTINGS_MODULE doesn't make much sense in the manually configured
    # (standalone) case.
    SETTINGS_MODULE = None

    def __init__(self, default_settings):
        """
        Requests for configuration variables not in this class are satisfied
        from the module specified in default_settings (if possible).
        """
        self.__dict__["_deleted"] = set()
        self.default_settings = default_settings

    def __getattr__(self, name):
        if not name.isupper() or name in self._deleted:
            raise AttributeError
        return getattr(self.default_settings, name)

    def __setattr__(self, name, value):
        self._deleted.discard(name)
        # RemovedInDjango70Warning.
        if name == "USE_BLANK_CHOICE_DASH":
            _show_settings_deprecation_warning(
                USE_BLANK_CHOICE_DASH_DEPRECATED_MSG, RemovedInDjango70Warning
            )

        super().__setattr__(name, value)

    def __delattr__(self, name):
        self._deleted.add(name)
        if hasattr(self, name):
            super().__delattr__(name)

    def __dir__(self):
        return sorted(
            s
            for s in [*self.__dict__, *dir(self.default_settings)]
            if s not in self._deleted
        )

    def is_overridden(self, setting):
        deleted = setting in self._deleted
        set_locally = setting in self.__dict__
        set_on_default = getattr(
            self.default_settings, "is_overridden", lambda s: False
        )(setting)
        return deleted or set_locally or set_on_default

    def __repr__(self):
        return "<%(cls)s>" % {
            "cls": self.__class__.__name__,
        }


def _show_settings_deprecation_warning(message, category):
    """Issue a warning when external code uses a deprecated setting.

    Allow Django's own code to use the setting without emitting the warning.
    This function should only be called from within settings-related code.
    """
    warn_about_external_use(
        message,
        category,
        skip_name_prefixes=(
            # Include all settings-related code here. (Do not include all of
            # "dorm.conf", which would incorrectly identify any deprecated
            # settings usage inside dorm.conf.urls as external.)
            "dorm.conf.LazySettings",
            "dorm.conf.Settings",
            "dorm.conf.UserSettingsHolder",
            "dorm.utils.functional.LazyObject",  # LazySettings superclass.
            # Test utilities are not part of the extracted ORM, so no test
            # prefixes are needed here.
        ),
    )


settings = LazySettings()
