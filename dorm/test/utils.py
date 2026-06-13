"""Django test utilities (ORM-only subset)."""

import gc
import logging
import os
import sys
import time
import warnings
from collections import defaultdict
from contextlib import contextmanager
from io import StringIO
from functools import wraps
from inspect import iscoroutinefunction
from unittest import TestCase, skipIf, skipUnless

from dorm.apps import apps
from dorm.conf import UserSettingsHolder, settings
from dorm.core.exceptions import ImproperlyConfigured
from dorm.core.signals import setting_changed
from dorm.db import DEFAULT_DB_ALIAS, connections
from dorm.test import signals  # noqa: F401 - registers setting_changed receivers
from dorm.utils.version import PYPY


__all__ = (
    "Approximate",
    "CaptureQueriesContext",
    "ignore_warnings",
    "isolate_apps",
    "modify_settings",
    "override_settings",
    "override_system_checks",
    "requires_tz_support",
    "setup_databases",
    "setup_test_environment",
    "teardown_databases",
    "teardown_test_environment",
    "tag",
)

TZ_SUPPORT = hasattr(time, "tzset")


class Approximate:
    def __init__(self, val, places=7):
        self.val = val
        self.places = places

    def __repr__(self):
        return repr(self.val)

    def __eq__(self, other):
        return self.val == other or round(abs(self.val - other), self.places) == 0


class TestContextDecorator:
    """
    A base class that can either be used as a context manager during tests
    or as a test function or unittest.TestCase subclass decorator.
    """

    def __init__(self, attr_name=None, kwarg_name=None):
        self.attr_name = attr_name
        self.kwarg_name = kwarg_name

    def enable(self):
        raise NotImplementedError

    def disable(self):
        raise NotImplementedError

    def __enter__(self):
        return self.enable()

    def __exit__(self, exc_type, exc_value, traceback):
        self.disable()

    def decorate_class(self, cls):
        if issubclass(cls, TestCase):
            decorated_setUp = cls.setUp

            def setUp(inner_self):
                context = self.enable()
                inner_self.addCleanup(self.disable)
                if self.attr_name:
                    setattr(inner_self, self.attr_name, context)
                decorated_setUp(inner_self)

            cls.setUp = setUp
            return cls
        raise TypeError("Can only decorate subclasses of unittest.TestCase")

    def decorate_callable(self, func):
        if iscoroutinefunction(func):
            @wraps(func)
            async def inner(*args, **kwargs):
                with self as context:
                    if self.kwarg_name:
                        kwargs[self.kwarg_name] = context
                    return await func(*args, **kwargs)
        else:
            @wraps(func)
            def inner(*args, **kwargs):
                with self as context:
                    if self.kwarg_name:
                        kwargs[self.kwarg_name] = context
                    return func(*args, **kwargs)

        return inner

    def __call__(self, decorated):
        if isinstance(decorated, type):
            return self.decorate_class(decorated)
        elif callable(decorated):
            return self.decorate_callable(decorated)
        raise TypeError("Cannot decorate object of type %s" % type(decorated))


class override_settings(TestContextDecorator):
    """Decorator/context manager to temporarily override Django settings."""

    enable_exception = None

    def __init__(self, **kwargs):
        self.options = kwargs
        super().__init__()

    def enable(self):
        if "INSTALLED_APPS" in self.options:
            try:
                apps.set_installed_apps(self.options["INSTALLED_APPS"])
            except Exception:
                apps.unset_installed_apps()
                raise
        override = UserSettingsHolder(settings._wrapped)
        for key, new_value in self.options.items():
            setattr(override, key, new_value)
        self.wrapped = settings._wrapped
        settings._wrapped = override
        for key, new_value in self.options.items():
            try:
                setting_changed.send(
                    sender=settings._wrapped.__class__,
                    setting=key,
                    value=new_value,
                    enter=True,
                )
            except Exception as exc:
                self.enable_exception = exc
                self.disable()

    def disable(self):
        settings._wrapped = self.wrapped
        del self.wrapped
        if "INSTALLED_APPS" in self.options:
            apps.unset_installed_apps()
        responses = []
        for key in self.options:
            new_value = getattr(settings, key, None)
            responses_for_setting = setting_changed.send_robust(
                sender=settings._wrapped.__class__,
                setting=key,
                value=new_value,
                enter=False,
            )
            responses.extend(responses_for_setting)
        if self.enable_exception is not None:
            exc = self.enable_exception
            self.enable_exception = None
            raise exc
        for _, response in responses:
            if isinstance(response, Exception):
                raise response

    def save_options(self, test_func):
        if test_func._overridden_settings is None:
            test_func._overridden_settings = self.options
        else:
            test_func._overridden_settings = {
                **test_func._overridden_settings,
                **self.options,
            }

    def decorate_class(self, cls):
        from dorm.test import SimpleTestCase

        if not issubclass(cls, SimpleTestCase):
            raise ValueError(
                "Only subclasses of Django SimpleTestCase can be decorated "
                "with override_settings"
            )
        self.save_options(cls)
        return cls


class modify_settings(override_settings):
    """Like override_settings, but for mutating list/tuple settings."""

    def __init__(self, *args, **kwargs):
        if args:
            assert not kwargs
            self.operations = args[0]
        else:
            assert not args
            self.operations = list(kwargs.items())
        super(override_settings, self).__init__()

    def save_options(self, test_func):
        if test_func._modified_settings is None:
            test_func._modified_settings = self.operations
        else:
            test_func._modified_settings = (
                list(test_func._modified_settings) + self.operations
            )

    def enable(self):
        self.options = {}
        for name, operations in self.operations:
            try:
                value = self.options[name]
            except KeyError:
                value = list(getattr(settings, name, []))
            for action, items in operations.items():
                if action == "append":
                    value = value + [item for item in items if item not in value]
                elif action == "prepend":
                    value = [item for item in items if item not in value] + value
                elif action == "remove":
                    value = [item for item in value if item not in items]
                else:
                    raise ValueError("Unsupported action: %s" % action)
            self.options[name] = value
        super().enable()


def dependency_ordered(test_databases, dependencies):
    """Reorder test_databases to honor TEST[DEPENDENCIES]."""
    ordered_test_databases = []
    resolved_databases = set()
    dependencies_map = {}

    for sig, (_, aliases) in test_databases:
        all_deps = set()
        for alias in aliases:
            all_deps.update(dependencies.get(alias, []))
        if not all_deps.isdisjoint(aliases):
            raise ImproperlyConfigured(
                "Circular dependency: databases %r depend on each other, "
                "but are aliases." % aliases
            )
        dependencies_map[sig] = all_deps

    while test_databases:
        changed = False
        deferred = []
        for signature, (db_name, aliases) in test_databases:
            if dependencies_map[signature].issubset(resolved_databases):
                resolved_databases.update(aliases)
                ordered_test_databases.append((signature, (db_name, aliases)))
                changed = True
            else:
                deferred.append((signature, (db_name, aliases)))
        if not changed:
            raise ImproperlyConfigured("Circular dependency in TEST[DEPENDENCIES]")
        test_databases = deferred
    return ordered_test_databases


def get_unique_databases_and_mirrors(aliases=None):
    """Figure out which databases actually need to be created."""
    if aliases is None:
        aliases = connections
    mirrored_aliases = {}
    test_databases = {}
    dependencies = {}
    default_sig = connections[DEFAULT_DB_ALIAS].creation.test_db_signature()

    for alias in connections:
        connection = connections[alias]
        test_settings = connection.settings_dict["TEST"]

        if test_settings["MIRROR"]:
            mirrored_aliases[alias] = test_settings["MIRROR"]
        elif alias in aliases:
            item = test_databases.setdefault(
                connection.creation.test_db_signature(),
                (connection.settings_dict["NAME"], []),
            )
            if alias == DEFAULT_DB_ALIAS:
                item[1].insert(0, alias)
            else:
                item[1].append(alias)

            if "DEPENDENCIES" in test_settings:
                dependencies[alias] = test_settings["DEPENDENCIES"]
            else:
                if (
                    alias != DEFAULT_DB_ALIAS
                    and connection.creation.test_db_signature() != default_sig
                ):
                    dependencies[alias] = test_settings.get(
                        "DEPENDENCIES", [DEFAULT_DB_ALIAS]
                    )

    test_databases = dict(dependency_ordered(test_databases.items(), dependencies))
    return test_databases, mirrored_aliases


def setup_databases(
    verbosity,
    interactive,
    *,
    time_keeper=None,
    keepdb=False,
    debug_sql=False,
    parallel=0,
    aliases=None,
    serialized_aliases=None,
    **kwargs,
):
    """Create the test databases."""
    test_databases, mirrored_aliases = get_unique_databases_and_mirrors(aliases)

    old_names = []
    serialize_connections = []

    for db_name, aliases in test_databases.values():
        first_alias = None
        for alias in aliases:
            connection = connections[alias]
            old_names.append((connection, db_name, first_alias is None))

            if first_alias is None:
                first_alias = alias
                connection.creation.create_test_db(
                    verbosity=verbosity,
                    autoclobber=not interactive,
                    keepdb=keepdb,
                )
                if serialized_aliases is None or alias in serialized_aliases:
                    serialize_connections.append(connection)
                if parallel > 1:
                    for index in range(parallel):
                        connection.creation.clone_test_db(
                            suffix=str(index + 1),
                            verbosity=verbosity,
                            keepdb=keepdb,
                        )
            else:
                connections[alias].creation.set_as_test_mirror(
                    connections[first_alias].settings_dict
                )

    for alias, mirror_alias in mirrored_aliases.items():
        connections[alias].creation.set_as_test_mirror(
            connections[mirror_alias].settings_dict
        )

    for serialize_connection in serialize_connections:
        serialize_connection._test_serialized_contents = (
            serialize_connection.creation.serialize_db_to_string()
        )

    if debug_sql:
        for alias in connections:
            connections[alias].force_debug_cursor = True

    return old_names


def teardown_databases(old_config, verbosity, parallel=0, keepdb=False):
    """Destroy all the non-mirror databases."""
    for connection, old_name, destroy in old_config:
        if destroy:
            if parallel > 1:
                for index in range(parallel):
                    connection.creation.destroy_test_db(
                        suffix=str(index + 1),
                        verbosity=verbosity,
                        keepdb=keepdb,
                    )
            connection.creation.destroy_test_db(
                old_name, verbosity=verbosity, keepdb=keepdb
            )


class NullTimeKeeper:
    def timed(self, name):
        return _null_context()

    def print_results(self):
        pass


class TimeKeeper:
    def __init__(self):
        self.records = []

    def timed(self, name):
        return _TestTiming(self, name)

    def print_results(self):
        if self.records:
            print("\nTimings")
            print("=" * 40)
            for name, elapsed in self.records:
                print("%-40s %.4fs" % (name, elapsed))


class _TestTiming:
    def __init__(self, keeper, name):
        self.keeper = keeper
        self.name = name

    def __enter__(self):
        self.start = time.perf_counter()

    def __exit__(self, exc_type, exc_value, traceback):
        self.keeper.records.append((self.name, time.perf_counter() - self.start))


@contextmanager
def _null_context():
    yield


def iter_test_cases(tests):
    """Return an iterator over a test suite's unittest.TestCase objects."""
    for test in tests:
        if isinstance(test, str):
            raise TypeError(
                f"Test {test!r} must be a test case or test suite not string "
                f"(was found in {tests!r})."
            )
        if isinstance(test, TestCase):
            yield test
        else:
            yield from iter_test_cases(test)


class CaptureQueriesContext:
    """Context manager to capture DB queries."""

    def __init__(self, connection):
        self.connection = connection

    def __iter__(self):
        return iter(self.captured_queries)

    def __getitem__(self, index):
        return self.captured_queries[index]

    def __len__(self):
        return len(self.captured_queries)

    @property
    def captured_queries(self):
        return self.connection.queries[self.initial_queries : self.final_queries]

    def __enter__(self):
        self.force_debug_cursor = self.connection.force_debug_cursor
        self.connection.force_debug_cursor = True
        self.initial_queries = len(self.connection.queries_log)
        self.final_queries = None
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.connection.force_debug_cursor = self.force_debug_cursor
        self.final_queries = len(self.connection.queries_log)


def setup_test_environment(debug=None):
    """Minimal test environment setup (ORM-only)."""
    pass


def teardown_test_environment():
    """Minimal test environment teardown (ORM-only)."""
    pass


class ignore_warnings(TestContextDecorator):
    """Context manager or decorator to ignore warnings."""

    def __init__(self, **kwargs):
        self.ignore_kwargs = kwargs
        if "message" in self.ignore_kwargs or "module" in self.ignore_kwargs:
            self.filter_func = warnings.filterwarnings
        else:
            self.filter_func = warnings.simplefilter
        super().__init__()

    def enable(self):
        self.catch_warnings = warnings.catch_warnings()
        self.catch_warnings.__enter__()
        self.filter_func("ignore", **self.ignore_kwargs)

    def disable(self):
        self.catch_warnings.__exit__(*sys.exc_info())


class isolate_apps(TestContextDecorator):
    """Decorator/context manager to register models in an isolated app registry."""

    def __init__(self, *installed_apps, **kwargs):
        self.installed_apps = installed_apps
        super().__init__(**kwargs)

    def enable(self):
        from dorm.apps.registry import Apps
        from dorm.db.models.options import Options

        self.old_apps = Options.default_apps
        apps = Apps(self.installed_apps)
        Options.default_apps = apps
        return apps

    def disable(self):
        from dorm.db.models.options import Options

        Options.default_apps = self.old_apps


@contextmanager
def register_lookup(field, *lookups, lookup_name=None):
    """Context manager to temporarily register lookups on a model field."""
    try:
        for lookup in lookups:
            field.register_lookup(lookup, lookup_name)
        yield
    finally:
        for lookup in lookups:
            field._unregister_lookup(lookup, lookup_name)


def override_system_checks(new_checks):
    """Decorator/context manager to override system checks registry."""
    from dorm.core.checks.registry import registry

    class OverrideSystemChecks(TestContextDecorator):
        def __init__(self, new_checks):
            self.new_checks = new_checks
            super().__init__()

        def enable(self):
            self.old_checks = registry.registered_checks
            registry.registered_checks = set()
            for check in self.new_checks:
                registry.register(check, deploy=False)
                registry.register(check, deploy=True)
            return new_checks

        def disable(self):
            registry.registered_checks = self.old_checks

    return OverrideSystemChecks(new_checks)


def garbage_collect():
    """Force garbage collection."""
    gc.collect()
    if PYPY:
        gc.collect()


@contextmanager
def extend_sys_path(*paths):
    """Context manager to temporarily add paths to sys.path."""
    _orig_sys_path = sys.path[:]
    sys.path.extend(paths)
    try:
        yield
    finally:
        sys.path = _orig_sys_path


@contextmanager
def captured_output(stream_name):
    """Return a context manager used by captured_stdout/stdin/stderr."""
    orig_stdout = getattr(sys, stream_name)
    setattr(sys, stream_name, StringIO())
    try:
        yield getattr(sys, stream_name)
    finally:
        setattr(sys, stream_name, orig_stdout)


def captured_stdout():
    return captured_output("stdout")


def captured_stderr():
    return captured_output("stderr")


def captured_stdin():
    return captured_output("stdin")


@contextmanager
def freeze_time(t):
    """Context manager to temporarily freeze time.time()."""
    _real_time = time.time
    time.time = lambda: t
    try:
        yield
    finally:
        time.time = _real_time


def tag(*tags):
    """Decorator to add tags to a test class or method."""

    def decorator(obj):
        if hasattr(obj, "tags"):
            obj.tags = obj.tags.union(tags)
        else:
            setattr(obj, "tags", set(tags))
        return obj

    return decorator


def requires_tz_support(func):
    """Decorator for tests requiring time zone support."""
    return skipUnless(
        TZ_SUPPORT,
        "This test relies on the ability to run a program with an arbitrary "
        "time zone, but your operating system isn't able to do that.",
    )(func)
