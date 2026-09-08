"""The strict-mode skip backstop in ``tests/conftest.py``.

A backstop that has never been seen to fire is indistinguishable from one
that does nothing -- which is the same argument the bridge guard makes about
a check that skips. These build the skip by hand, in a bridge-named module,
and assert what the run reports.

Deliberately NOT named ``test_matlab_bridge_*.py``: this file's own tests
must be free to skip, and it does not read the NDI-matlab tree.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.conftest import BRIDGE_MODULE_PREFIX, STRICT_ENV_VAR

REPO_ROOT = Path(__file__).resolve().parent.parent

#: A module that does nothing but skip, one call deep so the backstop is
#: shown catching a skip it could not have read off the test's own source.
SKIPPING_MODULE = """
import pytest


def _a_helper_that_skips():
    pytest.skip("the MATLAB tree is missing")


def test_that_skips():
    _a_helper_that_skips()
"""


def _run(tmp_path: Path, filename: str, strict: bool) -> subprocess.CompletedProcess:
    """Run one generated test file in a subprocess, with this repo's conftest.

    A subprocess because the thing under test is a pytest hook: it has to be
    a real collection-and-report cycle, not a simulated one.
    """
    target = tmp_path / filename
    target.write_text(SKIPPING_MODULE, encoding="utf-8")
    env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(REPO_ROOT),
        "HOME": str(tmp_path),
    }
    if strict:
        env[STRICT_ENV_VAR] = "1"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(target),
            "-p",
            "tests.conftest",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
    )


class TestTheSkipBackstop:
    def test_a_skipping_bridge_test_fails_under_strict(self, tmp_path):
        result = _run(tmp_path, f"{BRIDGE_MODULE_PREFIX}generated.py", strict=True)
        assert result.returncode != 0, result.stdout
        assert "1 failed" in result.stdout, result.stdout
        assert f"SKIPPED while {STRICT_ENV_VAR} is set" in result.stdout, result.stdout

    def test_the_same_skip_is_allowed_without_strict(self, tmp_path):
        """Strict mode is what makes a skip dishonest. A developer with no
        NDI-matlab checkout must still get a skip, not a failure."""
        result = _run(tmp_path, f"{BRIDGE_MODULE_PREFIX}generated.py", strict=False)
        assert result.returncode == 0, result.stdout
        assert "1 skipped" in result.stdout, result.stdout

    def test_a_skip_outside_the_bridge_modules_is_untouched(self, tmp_path):
        """An optional dependency or a platform-specific test is a
        legitimate skip; the rule is about bridge gates only."""
        result = _run(tmp_path, "test_something_else.py", strict=True)
        assert result.returncode == 0, result.stdout
        assert "1 skipped" in result.stdout, result.stdout
