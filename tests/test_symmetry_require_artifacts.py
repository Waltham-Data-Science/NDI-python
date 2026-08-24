"""Tests for ``NDI_SYMMETRY_REQUIRE_ARTIFACTS`` in ``tests/symmetry/conftest.py``.

Measured behaviour before this switch existed: with ``/tmp/NDI/symmetryTest``
absent -- i.e. MATLAB Stage 1 produced nothing at all -- the exact CI command
``pytest tests/symmetry/read_artifacts/ -v --tb=short`` reported
``42 skipped in 1.35s`` and exited **0**.  The symmetry job was green with zero
cross-language comparisons performed.

Every read test guards on ``if not artifact_dir.exists(): pytest.skip(...)``;
there are 35 such sites across 14 files.  Editing 35 sentences would leave the
36th unguarded, so the switch is implemented once, at the surface: a
``pytest_runtest_makereport`` wrapper that turns *any* skip in the symmetry tree
into a failure when the environment variable is set.  Local development keeps
the skips; CI sets the variable.

The subprocess tests run the real symmetry tests against an empty temp root, so
they exercise the real code path rather than a re-implementation of it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.symmetry.conftest import REQUIRE_ARTIFACTS_ENV, require_artifacts_enabled

REPO_ROOT = Path(__file__).resolve().parent.parent

# A small read-side module with no heavy imports, used as the canary.
CANARY = "tests/symmetry/read_artifacts/util/test_profile.py"


class TestRequireArtifactsEnabled:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_truthy_values_enable_it(self, value):
        assert require_artifacts_enabled({REQUIRE_ARTIFACTS_ENV: value}) is True

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
    def test_falsy_values_leave_it_off(self, value):
        assert require_artifacts_enabled({REQUIRE_ARTIFACTS_ENV: value}) is False

    def test_unset_leaves_it_off(self):
        assert require_artifacts_enabled({}) is False


def _run_symmetry(tmp_path, env_extra):
    env = dict(os.environ)
    # Point every tempdir lookup at an empty directory so the symmetry
    # artifact root cannot exist -- the "MATLAB produced nothing" condition.
    env["TMPDIR"] = str(tmp_path)
    env["TEMP"] = str(tmp_path)
    env["TMP"] = str(tmp_path)
    env.pop(REQUIRE_ARTIFACTS_ENV, None)
    env.update(env_extra)
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "pytest", CANARY, "-q", "-p", "no:cacheprovider", "--no-header"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.slow
class TestSkipsBecomeFailures:
    def test_missing_artifacts_skip_silently_by_default(self, tmp_path):
        """The pre-existing local-developer behaviour must be preserved."""
        result = _run_symmetry(tmp_path, {})
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "skipped" in combined
        assert "failed" not in combined

    def test_missing_artifacts_fail_when_required(self, tmp_path):
        """This is the case that used to report a green job with 0 comparisons."""
        result = _run_symmetry(tmp_path, {REQUIRE_ARTIFACTS_ENV: "1"})
        combined = result.stdout + result.stderr
        assert result.returncode != 0, combined
        assert "failed" in combined
        assert REQUIRE_ARTIFACTS_ENV in combined
