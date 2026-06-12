"""Minimal test runner stub for the ORM-only extraction.

The full Django DiscoverRunner depends on the web framework. This stub keeps
enough structure for code that imports get_runner or DiscoverRunner, but real
test execution should use pytest with a suitable conftest.
"""

import unittest

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

    def run_tests(self, test_labels, extra_tests=None, **kwargs):
        self.setup_test_environment()
        old_config = self.setup_databases()
        try:
            suite = self.build_suite(test_labels)
            result = self.run_suite(suite)
        finally:
            self.teardown_databases(old_config)
            self.teardown_test_environment()
        return self.suite_result(suite, result)

    def suite_result(self, suite, result, **kwargs):
        return len(result.failures) + len(result.errors)


def get_runner(settings):
    return DiscoverRunner
