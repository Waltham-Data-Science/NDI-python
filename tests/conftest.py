"""Pytest configuration and fixtures for NDI tests.

A SKIP IN A BRIDGE TEST IS A FAILURE WHEN STRICT MODE IS ON.

The bridge guard rests on one idea: a check that could not run must not
report the same result as a check that ran and passed (#77). Strict mode is
how CI says "the NDI-matlab tree is there, so anything that cannot run is a
broken job, not a missing developer checkout" -- and every gate that reaches
for the tree honours it today by calling :func:`pytest.fail` instead of
:func:`pytest.skip`.

Nothing enforced that. It was a convention each new gate had to remember,
and the failure mode when one forgot is silent by construction: a skipped
test is green, so the check that was supposed to be watching reports
nothing and the build stays clean. NDR-python hit this three times over --
a bridge job that named only one of its test files, 79 skips per matrix
job, and three ungated skips inside the drift self-tests, which are the
positive controls for the drift rule itself (VH-Lab/NDR-python#25). Both
repos share this suite's shape and #211's strict-mode convention, so both
want the same backstop.

This turns the convention into a rule: under ``NDI_BRIDGE_CHECK_STRICT``,
any skip in a ``test_matlab_bridge_*.py`` module fails. It is deliberately
a blanket rule rather than a list of known gates -- a list is the thing
that goes stale, and the point is to catch the gate nobody remembered to
add.

Skips elsewhere in the suite are untouched: an optional dependency or a
platform-specific test is a legitimate skip, and this says nothing about
those.
"""

from __future__ import annotations

import os

import pytest

#: CI sets this after checking NDI-matlab out. See #77 and section 7 of
#: docs/developer_notes/ndi_matlab_python_bridge.yaml.
STRICT_ENV_VAR = "NDI_BRIDGE_CHECK_STRICT"

#: Modules the rule covers. Every bridge gate lives in one of these.
BRIDGE_MODULE_PREFIX = "test_matlab_bridge_"


def _strict() -> bool:
    return bool(os.environ.get(STRICT_ENV_VAR, "").strip())


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Report a skipped bridge test as a failure under strict mode.

    Rewriting the report rather than the test is what makes this a
    backstop: it catches ``pytest.skip`` called anywhere the test reaches,
    a ``skipif`` marker, and a skip raised inside a helper several frames
    down -- none of which a check reading the test's own source would see.
    """
    outcome = yield
    report = outcome.get_result()

    if not report.skipped or not _strict():
        return
    if not os.path.basename(str(item.fspath)).startswith(BRIDGE_MODULE_PREFIX):
        return

    report.outcome = "failed"
    report.longrepr = (
        f"{item.nodeid} SKIPPED while {STRICT_ENV_VAR} is set.\n\n"
        "Strict mode means the NDI-matlab tree was supposed to be present, so "
        "a bridge test that skips is a check reporting nothing while the build "
        "stays green -- the exact failure the bridge guard exists to prevent "
        "(#77). Either make the gate call pytest.fail under strict mode, the "
        "way require_matlab_root does, or fix whatever made the test "
        "unrunnable.\n\n"
        f"Original skip reason: {report.longrepr}"
    )
