"""Tests for the ``NDI_CLOUD_READONLY`` collection guard in ``tests/conftest.py``.

The read-only prod smoke job in ``.github/workflows/test-cloud-api.yml`` runs
``pytest -m "not destructive"``.  That is one sentence on one command line: a
typo, a copy-paste into a new job, or a future test that forgets the marker and
prod gets written to again.  The guard in ``tests/conftest.py`` protects the
*surface* instead -- with ``NDI_CLOUD_READONLY=1`` set, the session errors out
if any destructive-marked test survived selection.

The subprocess tests below exercise the real conftest against the real
``tests/test_cloud_live.py``, because a unit test of the predicate alone would
not prove the hook is wired up.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import destructive_nodeids, readonly_mode_enabled

REPO_ROOT = Path(__file__).resolve().parent.parent


class _FakeItem:
    """Minimal stand-in for a pytest ``Item``."""

    def __init__(self, nodeid, markers=()):
        self.nodeid = nodeid
        self._markers = set(markers)

    def get_closest_marker(self, name):
        return object() if name in self._markers else None


class TestReadonlyModeEnabled:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values_enable_the_guard(self, value):
        assert readonly_mode_enabled({"NDI_CLOUD_READONLY": value}) is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
    def test_falsy_values_leave_it_off(self, value):
        assert readonly_mode_enabled({"NDI_CLOUD_READONLY": value}) is False

    def test_unset_leaves_it_off(self):
        assert readonly_mode_enabled({}) is False


class TestDestructiveNodeids:
    def test_reports_only_destructive_items(self):
        items = [
            _FakeItem("tests/a.py::test_read"),
            _FakeItem("tests/a.py::test_write", markers=["destructive"]),
            _FakeItem("tests/a.py::test_slow", markers=["slow"]),
        ]
        assert destructive_nodeids(items) == ["tests/a.py::test_write"]

    def test_empty_when_nothing_is_marked(self):
        assert destructive_nodeids([_FakeItem("tests/a.py::test_read")]) == []


def _collect(args, env_extra):
    import os

    env = dict(os.environ)
    env.update(env_extra)
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.slow
class TestGuardEndToEnd:
    """Drive the real conftest against the real cloud test module."""

    def test_readonly_session_errors_when_destructive_tests_are_selected(self):
        result = _collect(["tests/test_cloud_live.py"], {"NDI_CLOUD_READONLY": "1"})
        assert result.returncode != 0, result.stdout + result.stderr
        combined = result.stdout + result.stderr
        assert "NDI_CLOUD_READONLY" in combined
        assert "destructive" in combined

    def test_readonly_session_is_clean_when_destructive_tests_are_deselected(self):
        result = _collect(
            ["tests/test_cloud_live.py", "-m", "not destructive"],
            {"NDI_CLOUD_READONLY": "1"},
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def test_guard_is_inert_when_the_env_var_is_not_set(self):
        result = _collect(["tests/test_cloud_live.py"], {"NDI_CLOUD_READONLY": ""})
        assert result.returncode == 0, result.stdout + result.stderr
