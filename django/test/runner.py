"""Minimal test runner stub for the ORM-only extraction.

The full Django DiscoverRunner depends on the web framework. This stub keeps
enough structure for code that imports get_runner or DiscoverRunner, but real
test execution should use pytest with a suitable conftest.
"""

import unittest

from django.db import DEFAULT_DB_ALIAS
from django.test.utils import setup_databases, teardown_databases


class DiscoverRunner:
    """Minimal runner that creates and destroys test databases."""

    def __init__(
        self,
        pattern="test*.py",
        top_level=None,
        verbosity=1,
        interactive=True,
        failfast=False,
        keepdb=False,
        reverse=False,
        debug_mode=False,
        debug_sql=False,
        parallel=0,
        tags=None,
        exclude_tags=None,
        test_name_patterns=None,
        pdb=False,
        buffer=False,
        timing=False,
        shuffle=False,
        **kwargs,
    ):
        self.pattern = pattern
        self.top_level = top_level
        self.verbosity = verbosity
        self.interactive = interactive
        self.failfast = failfast
        self.keepdb = keepdb
        self.reverse = reverse
        self.debug_mode = debug_mode
        self.debug_sql = debug_sql
        self.parallel = parallel
        self.tags = set(tags or [])
        self.exclude_tags = set(exclude_tags or [])
        self.test_name_patterns = test_name_patterns
        self.pdb = pdb
        self.buffer = buffer
        self.timing = timing
        self.shuffle = shuffle

    @classmethod
    def add_arguments(cls, parser):
        pass

    def setup_test_environment(self, **kwargs):
        pass

    def teardown_test_environment(self, **kwargs):
        pass

    def setup_databases(self, **kwargs):
        # Serialization of test DBs requires django.core.serializers, which is
        # not part of the extracted ORM. Skip it unless explicitly requested.
        kwargs.setdefault("serialized_aliases", [])
        return setup_databases(
            self.verbosity,
            self.interactive,
            time_keeper=None,
            keepdb=self.keepdb,
            debug_sql=self.debug_sql,
            parallel=self.parallel,
            **kwargs,
        )

    def teardown_databases(self, old_config, **kwargs):
        teardown_databases(
            old_config,
            self.verbosity,
            parallel=self.parallel,
            keepdb=self.keepdb,
        )

    def build_suite(self, test_labels=None):
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        for label in test_labels or ["."]:
            suite.addTests(loader.discover(label, pattern=self.pattern))
        return suite

    def run_suite(self, suite, **kwargs):
        resultclass = unittest.TextTestResult
        return unittest.TextTestRunner(
            verbosity=self.verbosity,
            failfast=self.failfast,
            buffer=self.buffer,
            resultclass=resultclass,
        ).run(suite)

    def get_databases(self, suite):
        from django.db import connections

        def _iter_tests(suite):
            for test in suite:
                if isinstance(test, unittest.TestSuite):
                    yield from _iter_tests(test)
                else:
                    yield test

        databases = {alias: False for alias in connections}
        for test in _iter_tests(suite):
            test_databases = getattr(test, "databases", None)
            if test_databases == "__all__":
                test_databases = set(connections)
            for alias in test_databases or (DEFAULT_DB_ALIAS,):
                databases[alias] = databases[alias] or bool(
                    getattr(test, "serialized_rollback", False)
                )
        return databases

    def run_tests(self, test_labels, extra_tests=None, **kwargs):
        from django.db import DEFAULT_DB_ALIAS, connections

        self.setup_test_environment()
        suite = self.build_suite(test_labels)
        databases = self.get_databases(suite)
        serialized_aliases = {
            alias for alias, serialize in databases.items() if serialize
        }
        old_config = self.setup_databases(serialized_aliases=serialized_aliases)
        try:
            result = self.run_suite(suite)
        finally:
            self.teardown_databases(old_config)
            self.teardown_test_environment()
        return self.suite_result(suite, result)

    def suite_result(self, suite, result, **kwargs):
        return len(result.failures) + len(result.errors)


def get_runner(settings):
    return DiscoverRunner
