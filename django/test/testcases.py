"""Django test case classes (ORM-only subset)."""

import logging
import sys
import unittest
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from inspect import iscoroutinefunction
from unittest import mock
from unittest.util import safe_repr

from asgiref.sync import async_to_sync

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import DEFAULT_DB_ALIAS, connection, connections, transaction
from django.db.backends.base.base import NO_DB_ALIAS, BaseDatabaseWrapper
from django.test.utils import (
    Approximate,
    CaptureQueriesContext,
    modify_settings,
    override_settings,
)
from django.utils.version import PYPY

__all__ = (
    "TestCase",
    "TransactionTestCase",
    "SimpleTestCase",
    "skipIfDBFeature",
    "skipUnlessDBFeature",
    "skipUnlessAnyDBFeature",
)

__unittest = True

logger = logging.getLogger("django.test")


def to_list(value):
    """Put value into a list if it's not already one."""
    if not isinstance(value, list):
        value = [value]
    return value


class _DatabaseFailure:
    def __init__(self, wrapped, message):
        self.wrapped = wrapped
        self.message = message

    def __call__(self, *args, **kwargs):
        raise AssertionError(self.message)


class SimpleTestCase(unittest.TestCase):
    databases = set()
    _disallowed_database_msg = (
        "Database %(operation)s to %(alias)r are not allowed in SimpleTestCase "
        "subclasses. Either subclass TestCase or TransactionTestCase to ensure "
        "proper test isolation or add %(alias)r to %(test)s.databases to silence "
        "this failure."
    )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if cls._overridden_settings:
            cls.enterClassContext(override_settings(**cls._overridden_settings))
        if cls._modified_settings:
            cls.enterClassContext(modify_settings(cls._modified_settings))
        cls._add_databases_failures()
        cls.addClassCleanup(cls._remove_databases_failures)

    @classmethod
    def _validate_databases(cls):
        if cls.databases == "__all__":
            return frozenset(connections)
        for alias in cls.databases:
            if alias not in connections:
                message = (
                    "%s.%s.databases refers to %r which is not defined in "
                    "settings.DATABASES." % (cls.__module__, cls.__qualname__, alias)
                )
                raise ImproperlyConfigured(message)
        return frozenset(cls.databases)

    @classmethod
    def _add_databases_failures(cls):
        cls.databases = cls._validate_databases()
        for alias in connections:
            if alias in cls.databases:
                continue
            connection = connections[alias]
            disallowed_methods = (
                connection.features.disallowed_simple_test_case_connection_methods
            )
            for name, operation in disallowed_methods:
                message = cls._disallowed_database_msg % {
                    "test": "%s.%s" % (cls.__module__, cls.__qualname__),
                    "alias": alias,
                    "operation": operation,
                }
                method = getattr(connection, name)
                setattr(connection, name, _DatabaseFailure(method, message))
        cls.enterClassContext(
            mock.patch.object(
                BaseDatabaseWrapper,
                "ensure_connection",
                new=cls.ensure_connection_patch_method(),
            )
        )

    @classmethod
    def _remove_databases_failures(cls):
        for alias in connections:
            if alias in cls.databases:
                continue
            connection = connections[alias]
            disallowed_methods = (
                connection.features.disallowed_simple_test_case_connection_methods
            )
            for name, _ in disallowed_methods:
                method = getattr(connection, name)
                setattr(connection, name, method.wrapped)

    @classmethod
    def ensure_connection_patch_method(cls):
        real_ensure_connection = BaseDatabaseWrapper.ensure_connection

        def patched_ensure_connection(self, *args, **kwargs):
            if (
                self.connection is None
                and self.alias not in cls.databases
                and self.alias != NO_DB_ALIAS
                and self.alias in connections
            ):
                message = cls._disallowed_database_msg % {
                    "test": f"{cls.__module__}.{cls.__qualname__}",
                    "alias": self.alias,
                    "operation": "threaded connections",
                }
                return _DatabaseFailure(self.ensure_connection, message)()

            real_ensure_connection(self, *args, **kwargs)

        return patched_ensure_connection

    def __call__(self, result=None):
        self._setup_and_call(result)

    def debug(self):
        debug_result = unittest.suite._DebugResult()
        self._setup_and_call(debug_result, debug=True)

    def _setup_and_call(self, result, debug=False):
        testMethod = getattr(self, self._testMethodName)
        skipped = getattr(self.__class__, "__unittest_skip__", False) or getattr(
            testMethod, "__unittest_skip__", False
        )

        if iscoroutinefunction(testMethod):
            setattr(self, self._testMethodName, async_to_sync(testMethod))

        if not skipped:
            try:
                self._pre_setup()
            except Exception:
                if debug:
                    raise
                result.addError(self, sys.exc_info())
                return
        if debug:
            super().debug()
        else:
            super().__call__(result)
        if not skipped:
            try:
                self._post_teardown()
            except Exception:
                if debug:
                    raise
                result.addError(self, sys.exc_info())
                return

    def _pre_setup(self):
        pass

    def _post_teardown(self):
        pass

    def settings(self, **kwargs):
        """Return a context manager or decorator to temporarily override settings."""
        return override_settings(**kwargs)

    def assertQuerySetEqual(self, qs, values, transform=None, ordered=True, msg=None):
        values = list(values)
        items = qs
        if transform is not None:
            items = map(transform, items)
        if not ordered:
            from collections import Counter

            return self.assertDictEqual(Counter(items), Counter(values), msg=msg)
        if len(values) > 1 and hasattr(qs, "ordered") and not qs.ordered:
            raise ValueError(
                "Trying to compare non-ordered queryset against more than one "
                "ordered value."
            )
        return self.assertEqual(list(items), values, msg=msg)


class TransactionTestCase(SimpleTestCase):
    reset_sequences = False
    fixtures = None
    databases = {DEFAULT_DB_ALIAS}
    serialized_rollback = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not issubclass(cls, TestCase):
            cls._pre_setup()
            cls._pre_setup_ran_eagerly = True

    @classmethod
    def _databases_names(cls, include_mirrors=True):
        return [
            alias
            for alias in connections
            if alias in cls.databases
            and (
                include_mirrors
                or not connections[alias].settings_dict["TEST"]["MIRROR"]
            )
        ]

    @classmethod
    def _pre_setup(cls):
        super()._pre_setup()
        cls._fixture_setup()
        for db_name in cls._databases_names(include_mirrors=False):
            connections[db_name].queries_log.clear()

    @staticmethod
    def _reset_sequences(db_name):
        conn = connections[db_name]
        if conn.features.supports_sequence_reset:
            from django.core.management.color import no_style

            sql_list = conn.ops.sequence_reset_by_name_sql(
                no_style(), conn.introspection.sequence_list()
            )
            if sql_list:
                with transaction.atomic(using=db_name):
                    with conn.cursor() as cursor:
                        for sql in sql_list:
                            cursor.execute(sql)

    @classmethod
    def _fixture_setup(cls):
        for db_name in cls._databases_names(include_mirrors=False):
            if cls.reset_sequences:
                cls._reset_sequences(db_name)

            if cls.serialized_rollback and hasattr(
                connections[db_name], "_test_serialized_contents"
            ):
                connections[db_name].creation.deserialize_db_from_string(
                    connections[db_name]._test_serialized_contents
                )

            if cls.fixtures:
                from django.core.management import call_command

                call_command("loaddata", *cls.fixtures, verbosity=0, database=db_name)

    def _should_reload_connections(self):
        return True

    def _post_teardown(self):
        try:
            self._fixture_teardown()
            super()._post_teardown()
            if self._should_reload_connections():
                for conn in connections.all(initialized_only=True):
                    conn.close()
        finally:
            pass

    def _fixture_teardown(self):
        for db_name in self._databases_names(include_mirrors=False):
            from django.core.management import call_command

            call_command(
                "flush",
                verbosity=0,
                interactive=False,
                database=db_name,
                reset_sequences=False,
            )

    def assertNumQueries(self, num, func=None, *args, using=DEFAULT_DB_ALIAS, **kwargs):
        conn = connections[using]
        context = _AssertNumQueriesContext(self, num, conn)
        if func is None:
            return context

        with context:
            func(*args, **kwargs)


class _AssertNumQueriesContext(CaptureQueriesContext):
    def __init__(self, test_case, num, connection):
        self.test_case = test_case
        self.num = num
        super().__init__(connection)

    def __exit__(self, exc_type, exc_value, traceback):
        super().__exit__(exc_type, exc_value, traceback)
        if exc_type is not None:
            return
        executed = len(self)
        self.test_case.assertEqual(
            executed,
            self.num,
            "%d queries executed, %d expected\nCaptured queries were:\n%s"
            % (
                executed,
                self.num,
                "\n".join(
                    "%s. %s" % (i, query["sql"])
                    for i, query in enumerate(self.captured_queries, start=1)
                ),
            ),
        )


def connections_support_transactions(aliases=None):
    conns = (
        connections.all()
        if aliases is None
        else (connections[alias] for alias in aliases)
    )
    return all(conn.features.supports_transactions for conn in conns)


def connections_support_savepoints(aliases=None):
    conns = (
        connections.all()
        if aliases is None
        else (connections[alias] for alias in aliases)
    )
    return all(conn.features.uses_savepoints for conn in conns)


class TestData:
    """Descriptor to provide TestCase instance isolation for setUpTestData attrs."""

    memo_attr = "_testdata_memo"

    def __init__(self, name, data):
        self.name = name
        self.data = data

    def get_memo(self, testcase):
        try:
            memo = getattr(testcase, self.memo_attr)
        except AttributeError:
            memo = {}
            setattr(testcase, self.memo_attr, memo)
        return memo

    def __get__(self, instance, owner):
        if instance is None:
            return self.data
        memo = self.get_memo(instance)
        data = deepcopy(self.data, memo)
        setattr(instance, self.name, data)
        return data

    def __repr__(self):
        return "<TestData: name=%r, data=%r>" % (self.name, self.data)


class TestCase(TransactionTestCase):
    @classmethod
    def _enter_atomics(cls):
        atomics = {}
        for db_name in cls._databases_names():
            atomic = transaction.atomic(using=db_name)
            atomic._from_testcase = True
            atomic.__enter__()
            atomics[db_name] = atomic
        return atomics

    @classmethod
    def _rollback_atomics(cls, atomics):
        for db_name in reversed(cls._databases_names()):
            transaction.set_rollback(True, using=db_name)
            atomics[db_name].__exit__(None, None, None)

    @classmethod
    def _databases_support_transactions(cls):
        return connections_support_transactions(cls.databases)

    @classmethod
    def _databases_support_savepoints(cls):
        return connections_support_savepoints(cls.databases)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not (
            cls._databases_support_transactions()
            and cls._databases_support_savepoints()
        ):
            return
        cls.cls_atomics = cls._enter_atomics()

        if cls.fixtures:
            for db_name in cls._databases_names(include_mirrors=False):
                try:
                    from django.core.management import call_command

                    call_command(
                        "loaddata",
                        *cls.fixtures,
                        verbosity=0,
                        database=db_name,
                    )
                except Exception:
                    cls._rollback_atomics(cls.cls_atomics)
                    raise
        pre_attrs = cls.__dict__.copy()
        try:
            cls.setUpTestData()
        except Exception:
            cls._rollback_atomics(cls.cls_atomics)
            raise
        for name, value in cls.__dict__.items():
            if value is not pre_attrs.get(name):
                setattr(cls, name, TestData(name, value))

    @classmethod
    def tearDownClass(cls):
        if (
            cls._databases_support_transactions()
            and cls._databases_support_savepoints()
        ):
            cls._rollback_atomics(cls.cls_atomics)
            for conn in connections.all(initialized_only=True):
                conn.close()
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        pass

    def _should_reload_connections(self):
        if self._databases_support_transactions():
            return False
        return super()._should_reload_connections()

    @classmethod
    def _fixture_setup(cls):
        if not cls._databases_support_transactions():
            cls.setUpTestData()
            return super()._fixture_setup()

        if cls.reset_sequences:
            raise TypeError("reset_sequences cannot be used on TestCase instances")
        cls.atomics = cls._enter_atomics()
        if not cls._databases_support_savepoints():
            if cls.fixtures:
                for db_name in cls._databases_names(include_mirrors=False):
                    from django.core.management import call_command

                    call_command(
                        "loaddata",
                        *cls.fixtures,
                        **{"verbosity": 0, "database": db_name},
                    )
            cls.setUpTestData()

    def _fixture_teardown(self):
        if not self._databases_support_transactions():
            return super()._fixture_teardown()
        try:
            for db_name in reversed(self._databases_names()):
                if self._should_check_constraints(connections[db_name]):
                    connections[db_name].check_constraints()
        finally:
            self._rollback_atomics(self.atomics)

    def _should_check_constraints(self, connection):
        return (
            connection.features.can_defer_constraint_checks
            and not connection.needs_rollback
            and connection.is_usable()
        )

    @classmethod
    @contextmanager
    def captureOnCommitCallbacks(cls, *, using=DEFAULT_DB_ALIAS, execute=False):
        callbacks = []
        start_count = len(connections[using].run_on_commit)
        try:
            yield callbacks
        finally:
            while True:
                callback_count = len(connections[using].run_on_commit)
                for _, callback, robust in connections[using].run_on_commit[
                    start_count:
                ]:
                    callbacks.append(callback)
                    if execute:
                        if robust:
                            try:
                                callback()
                            except Exception as e:
                                name = getattr(callback, "__qualname__", callback)
                                logger.exception(
                                    "Error calling %s in on_commit() (%s).",
                                    name,
                                    e,
                                )
                        else:
                            callback()

                if callback_count == len(connections[using].run_on_commit):
                    break
                start_count = callback_count


class CheckCondition:
    def __init__(self, *conditions):
        self.conditions = conditions

    def add_condition(self, condition, reason):
        return self.__class__(*self.conditions, (condition, reason))

    def __get__(self, instance, cls=None):
        if any(getattr(base, "__unittest_skip__", False) for base in cls.__bases__):
            return True
        for condition, reason in self.conditions:
            if condition():
                cls.__unittest_skip__ = True
                cls.__unittest_skip_why__ = reason
                return True
        return False


def _deferredSkip(condition, reason, name):
    def decorator(test_func):
        nonlocal condition
        if not (
            isinstance(test_func, type) and issubclass(test_func, unittest.TestCase)
        ):

            @wraps(test_func)
            def skip_wrapper(*args, **kwargs):
                if (
                    args
                    and isinstance(args[0], unittest.TestCase)
                    and connection.alias not in getattr(args[0], "databases", {})
                ):
                    raise ValueError(
                        "%s cannot be used on %s as %s doesn't allow queries "
                        "against the %r database."
                        % (
                            name,
                            args[0],
                            args[0].__class__.__qualname__,
                            connection.alias,
                        )
                    )
                if condition():
                    raise unittest.SkipTest(reason)
                return test_func(*args, **kwargs)

            test_item = skip_wrapper
        else:
            test_item = test_func
            databases = getattr(test_item, "databases", None)
            if not databases or connection.alias not in databases:

                def condition():
                    raise ValueError(
                        "%s cannot be used on %s as it doesn't allow queries "
                        "against the '%s' database."
                        % (name, test_item, connection.alias)
                    )

            skip = test_func.__dict__.get("__unittest_skip__")
            if isinstance(skip, CheckCondition):
                test_item.__unittest_skip__ = skip.add_condition(condition, reason)
            elif skip is not True:
                test_item.__unittest_skip__ = CheckCondition((condition, reason))
        return test_item

    return decorator


def skipIfDBFeature(*features):
    return _deferredSkip(
        lambda: any(getattr(connection.features, feature) for feature in features),
        "Database has feature(s) %s" % ", ".join(features),
        "skipIfDBFeature",
    )


def skipUnlessDBFeature(*features):
    return _deferredSkip(
        lambda: not all(getattr(connection.features, feature) for feature in features),
        "Database doesn't support feature(s): %s" % ", ".join(features),
        "skipUnlessDBFeature",
    )


def skipUnlessAnyDBFeature(*features):
    return _deferredSkip(
        lambda: not any(getattr(connection.features, feature) for feature in features),
        "Database doesn't support any of the feature(s): %s" % ", ".join(features),
        "skipUnlessAnyDBFeature",
    )
