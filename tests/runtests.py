#!/usr/bin/env python
"""
Test runner for the extracted Django ORM test suite.

Based on Django's original tests/runtests.py, but stripped of web-framework
dependencies (contrib apps, middleware, templates, static files, selenium, etc.).
"""

import argparse
import os
import sys
import warnings
from pathlib import Path

import dorm
from dorm.apps import apps
from dorm.conf import settings
from dorm.core.exceptions import ImproperlyConfigured
from dorm.db import connection, connections
from dorm.test import TestCase, TransactionTestCase
from dorm.test.runner import get_runner
from dorm.test.utils import NullTimeKeeper, TimeKeeper
from dorm.utils.deprecation import (
    RemovedAfterNextVersionWarning,
    RemovedInNextVersionWarning,
)
from dorm.utils.functional import classproperty


# Make deprecation warnings errors to ensure no usage of deprecated features.
warnings.simplefilter("error", RemovedInNextVersionWarning)
warnings.simplefilter("error", RemovedAfterNextVersionWarning)
# Make resource and runtime warning errors to ensure no usage of error prone
# patterns.
warnings.simplefilter("error", ResourceWarning)
warnings.simplefilter("error", RuntimeWarning)


RUNTESTS_DIR = os.path.abspath(os.path.dirname(__file__))

# Subdirectories of RUNTESTS_DIR to skip when searching for test modules.
SUBDIRS_TO_SKIP = {
    "": {"import_error_package", "test_runner_apps"},
}


def get_test_modules():
    """
    Scan the tests directory and yield the names of all test modules.

    A test module is a subdirectory of RUNTESTS_DIR that contains __init__.py.
    """
    subdirs_to_skip = SUBDIRS_TO_SKIP[""]
    with os.scandir(RUNTESTS_DIR) as entries:
        for f in entries:
            if (
                "." in f.name
                or os.path.basename(f.name) in subdirs_to_skip
                or f.is_file()
                or not os.path.exists(os.path.join(f.path, "__init__.py"))
            ):
                continue
            yield f.name


def get_label_module(label):
    """Return the top-level module part for a test label."""
    path = Path(label)
    if len(path.parts) == 1:
        return label.split(".")[0]

    if not path.exists():
        raise RuntimeError(f"Test label path {label} does not exist")
    path = path.resolve()
    rel_path = path.relative_to(RUNTESTS_DIR)
    return rel_path.parts[0]


def get_filtered_test_modules(start_at, start_after, test_labels=None):
    if test_labels is None:
        test_labels = []

    label_modules = set()
    for label in test_labels:
        label_modules.add(get_label_module(label))

    def _module_match_label(module_name, label):
        return module_name == label or module_name.startswith(label + ".")

    start_label = start_at or start_after
    for test_module in get_test_modules():
        if start_label:
            if not _module_match_label(test_module, start_label):
                continue
            start_label = ""
            if not start_at:
                continue

        if not test_labels or any(
            _module_match_label(test_module, label_module)
            for label_module in label_modules
        ):
            yield test_module


def get_installed():
    return [app_config.name for app_config in apps.get_app_configs()]


def get_apps_to_install(test_modules):
    for test_module in test_modules:
        yield test_module


def setup_collect_tests(start_at, start_after, test_labels=None):
    state = {
        "INSTALLED_APPS": settings.INSTALLED_APPS,
        "LANGUAGE_CODE": getattr(settings, "LANGUAGE_CODE", "en-us"),
        "MIGRATION_MODULES": getattr(settings, "MIGRATION_MODULES", {}),
        "SILENCED_SYSTEM_CHECKS": getattr(settings, "SILENCED_SYSTEM_CHECKS", []),
    }

    settings.LANGUAGE_CODE = "en"
    settings.MIGRATION_MODULES = {}
    settings.SILENCED_SYSTEM_CHECKS = [
        "fields.W342",  # ForeignKey(unique=True) -> OneToOneField
    ]

    dorm.setup()

    test_modules = list(
        get_filtered_test_modules(
            start_at,
            start_after,
            test_labels=test_labels,
        )
    )
    return test_modules, state


def teardown_collect_tests(state):
    for key, value in state.items():
        setattr(settings, key, value)


def setup_run_tests(verbosity, start_at, start_after, test_labels=None):
    test_modules, state = setup_collect_tests(
        start_at, start_after, test_labels=test_labels
    )

    installed_apps = set(get_installed())
    for app in get_apps_to_install(test_modules):
        if app in installed_apps:
            continue
        if verbosity >= 2:
            print(f"Importing application {app}")
        settings.INSTALLED_APPS.append(app)
        installed_apps.add(app)

    apps.set_installed_apps(settings.INSTALLED_APPS)

    # Force declaring available_apps in TransactionTestCase for faster tests.
    def no_available_apps(cls):
        raise Exception(
            "Please define available_apps in TransactionTestCase and its subclasses."
        )

    TransactionTestCase.available_apps = classproperty(no_available_apps)
    TestCase.available_apps = None

    os.environ["RUNNING_DJANGOS_TEST_SUITE"] = "true"

    test_labels = test_labels or test_modules
    return test_labels, state


def teardown_run_tests(state):
    teardown_collect_tests(state)
    del os.environ["RUNNING_DJANGOS_TEST_SUITE"]


def django_tests(
    verbosity,
    interactive,
    failfast,
    keepdb,
    reverse,
    test_labels,
    debug_sql,
    parallel,
    tags,
    exclude_tags,
    test_name_patterns,
    start_at,
    start_after,
    pdb,
    buffer,
    timing,
    shuffle,
    durations=None,
):
    if verbosity >= 1:
        print("Testing against Django installed in '%s'" % os.path.dirname(dorm.__file__))

    process_setup_args = (verbosity, start_at, start_after, test_labels)
    test_labels, state = setup_run_tests(*process_setup_args)

    if not hasattr(settings, "TEST_RUNNER"):
        settings.TEST_RUNNER = "dorm.test.runner.DiscoverRunner"

    TestRunner = get_runner(settings)
    test_runner = TestRunner(
        verbosity=verbosity,
        interactive=interactive,
        failfast=failfast,
        keepdb=keepdb,
        reverse=reverse,
        debug_sql=debug_sql,
        parallel=parallel,
        tags=tags,
        exclude_tags=exclude_tags,
        test_name_patterns=test_name_patterns,
        pdb=pdb,
        buffer=buffer,
        timing=timing,
        shuffle=shuffle,
        durations=durations,
    )
    failures = test_runner.run_tests(test_labels)
    teardown_run_tests(state)
    return failures


def paired_tests(paired_test, options, test_labels, start_at, start_after):
    if not test_labels:
        test_labels = collect_test_modules(start_at, start_after)

    print("***** Running paired tests")
    subprocess_args = [sys.executable, __file__]
    if options.settings:
        subprocess_args.append("--settings=%s" % options.settings)
    if options.failfast:
        subprocess_args.append("--failfast")
    if options.verbosity:
        subprocess_args.append("--verbosity=%s" % options.verbosity)

    for i, label in enumerate(test_labels):
        if label == paired_test:
            continue
        print(
            "***** Pair %d: Running tests '%s' and '%s'"
            % (i, paired_test, label)
        )
        failures = subprocess.run(subprocess_args + [paired_test, label])
        if failures:
            sys.exit(1)


def collect_test_modules(start_at, start_after):
    test_modules, state = setup_collect_tests(start_at, start_after)
    teardown_collect_tests(state)
    return test_modules


def bisect_tests(bisection_label, options, test_labels, start_at, start_after):
    import subprocess

    if not test_labels:
        test_labels = collect_test_modules(start_at, start_after)

    print("***** Bisecting test suite: %s" % " ".join(test_labels))

    for label in [bisection_label, "model_inheritance_same_model_name"]:
        try:
            test_labels.remove(label)
        except ValueError:
            pass

    subprocess_args = [sys.executable, __file__]
    if options.settings:
        subprocess_args.append("--settings=%s" % options.settings)
    if options.failfast:
        subprocess_args.append("--failfast")
    if options.verbosity:
        subprocess_args.append("--verbosity=%s" % options.verbosity)

    iteration = 1
    while len(test_labels) > 1:
        midpoint = len(test_labels) // 2
        test_labels_a = test_labels[:midpoint] + [bisection_label]
        test_labels_b = test_labels[midpoint:] + [bisection_label]
        print("***** Pass %da: Running the first half of the test suite" % iteration)
        print("***** Test labels: %s" % " ".join(test_labels_a))
        failures_a = subprocess.run(subprocess_args + test_labels_a)

        print("***** Pass %db: Running the second half of the test suite" % iteration)
        print("***** Test labels: %s" % " ".join(test_labels_b))
        failures_b = subprocess.run(subprocess_args + test_labels_b)

        if failures_a and failures_b:
            print("***** Split point not found")
            sys.exit(1)
        elif failures_a:
            test_labels = test_labels_a[:-1]
        elif failures_b:
            test_labels = test_labels_b[:-1]
        else:
            print("***** Split point not found")
            sys.exit(1)

        iteration += 1

    print("***** Found problem in: %s" % test_labels[0])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Django ORM test suite.")
    parser.add_argument(
        "modules",
        nargs="*",
        help="Optional path(s) to test modules; e.g. 'queries' or 'queries.tests'.",
    )
    parser.add_argument(
        "-v",
        "--verbosity",
        default=1,
        type=int,
        choices=[0, 1, 2, 3],
        help="Verbosity level; 0=minimal output, 1=normal output, 2=all output.",
    )
    parser.add_argument(
        "--noinput",
        action="store_false",
        dest="interactive",
        help="Do NOT prompt the user for input of any kind.",
    )
    parser.add_argument(
        "--failfast",
        action="store_true",
        help="Stop running the test suite after first failed test.",
    )
    parser.add_argument(
        "--keepdb",
        action="store_true",
        help="Preserves the test DB between runs.",
    )
    parser.add_argument(
        "--reverse",
        action="store_true",
        help="Sort test suites and test cases in opposite order to debug "
        "test side effects.",
    )
    parser.add_argument(
        "--settings",
        help="Python path to settings module, e.g. 'myproject.settings'. "
        "If this isn't provided, the DJANGO_SETTINGS_MODULE environment "
        "variable is used.",
    )
    parser.add_argument(
        "--debug-sql",
        action="store_true",
        help="Turn on the SQL query logger within tests.",
    )
    parser.add_argument(
        "--parallel",
        nargs="?",
        const="auto",
        default=0,
        type=int,
        metavar="N",
        help='Run tests using up to N parallel processes. Use the value "auto" '
        "to run one test process for each processor core.",
    )
    parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        help="Run only tests with the specified tags. Can be used multiple times.",
    )
    parser.add_argument(
        "--exclude-tag",
        dest="exclude_tags",
        action="append",
        help="Do not run tests with the specified tag. Can be used multiple times.",
    )
    parser.add_argument(
        "--start-after",
        dest="start_after",
        help="Run tests starting after the specified top-level module.",
    )
    parser.add_argument(
        "--start-at",
        dest="start_at",
        help="Run tests starting at the specified top-level module.",
    )
    parser.add_argument(
        "--pdb", action="store_true", help="Runs the PDB debugger on error or failure."
    )
    parser.add_argument(
        "-b",
        "--buffer",
        action="store_true",
        help="Discard output of passing tests.",
    )
    parser.add_argument(
        "--timing",
        action="store_true",
        help="Output timings, including database set up and total run time.",
    )
    parser.add_argument(
        "-k",
        dest="test_name_patterns",
        action="append",
        help=(
            "Only run test methods and classes matching test name pattern. "
            "Same as unittest -k option. Can be used multiple times."
        ),
    )
    parser.add_argument(
        "--durations",
        dest="durations",
        type=int,
        default=None,
        metavar="N",
        help="Show the N slowest test cases (N=0 for all).",
    )
    parser.add_argument(
        "--shuffle",
        dest="shuffle",
        nargs="?",
        default=False,
        const=None,
        help="Shuffle the order of test cases to help detect side effects.",
    )
    parser.add_argument(
        "--bisect",
        dest="bisect",
        metavar="TEST_LABEL",
        help="Bisect the test suite to find the test that fails when paired "
        "with TEST_LABEL.",
    )
    parser.add_argument(
        "--pair",
        dest="pair",
        metavar="TEST_LABEL",
        help="Run TEST_LABEL paired with every other test to find "
        "incompatibilities.",
    )

    options = parser.parse_args()

    options.modules = [os.path.normpath(labels) for labels in options.modules]

    mutually_exclusive_options = [
        options.start_at,
        options.start_after,
        options.modules,
    ]
    enabled_module_options = [
        bool(option) for option in mutually_exclusive_options
    ].count(True)
    if enabled_module_options > 1:
        print(
            "Aborting: --start-at, --start-after, and test labels are mutually "
            "exclusive."
        )
        sys.exit(1)
    for opt_name in ["start_at", "start_after"]:
        opt_val = getattr(options, opt_name)
        if opt_val:
            if "." in opt_val:
                print(
                    "Aborting: --%s must be a top-level module."
                    % opt_name.replace("_", "-")
                )
                sys.exit(1)
            setattr(options, opt_name, os.path.normpath(opt_val))

    if options.settings:
        os.environ["DJANGO_SETTINGS_MODULE"] = options.settings
    else:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "test_sqlite")
        options.settings = os.environ["DJANGO_SETTINGS_MODULE"]

    if options.bisect:
        bisect_tests(
            options.bisect,
            options,
            options.modules,
            options.start_at,
            options.start_after,
        )
    elif options.pair:
        paired_tests(
            options.pair,
            options,
            options.modules,
            options.start_at,
            options.start_after,
        )
    else:
        time_keeper = TimeKeeper() if options.timing else NullTimeKeeper()
        with time_keeper.timed("Total run"):
            failures = django_tests(
                options.verbosity,
                options.interactive,
                options.failfast,
                options.keepdb,
                options.reverse,
                options.modules,
                options.debug_sql,
                options.parallel,
                options.tags,
                options.exclude_tags,
                options.test_name_patterns,
                options.start_at,
                options.start_after,
                options.pdb,
                options.buffer,
                options.timing,
                options.shuffle,
                getattr(options, "durations", None),
            )
        time_keeper.print_results()
        if failures:
            sys.exit(1)
