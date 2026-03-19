"""Read and verify symmetry artifacts for a blank vhlab NDI session.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+session/blankSessionVhlab.m

This test loads artifacts produced by *either* the MATLAB or the Python
``makeArtifacts`` suite and verifies that the Python NDI stack can open the
session and produce a matching session summary.
"""

import json

import pytest

from ndi.session.dir import ndi_session_dir
from ndi.util import compareSessionSummary, sessionSummary
from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE
from tests.symmetry.read_artifacts.session._summary_helpers import (
    sort_daq_systems_by_name,
)


@pytest.fixture(params=SOURCE_TYPES)
def source_type(request):
    """Parameterize over matlabArtifacts / pythonArtifacts."""
    return request.param


class TestBlankSessionVhlab:
    """Mirror of ndi.symmetry.readArtifacts.session.blankSessionVhlab."""

    def _artifact_dir(self, source_type: str):
        return (
            SYMMETRY_BASE / source_type / "session" / "blankSessionVhlab" / "testBlankSessionVhlab"
        )

    def _open_session(self, source_type):
        artifact_dir = self._artifact_dir(source_type)
        if not artifact_dir.exists():
            pytest.skip(
                f"Artifact directory from {source_type} does not exist. "
                f"Run the corresponding makeArtifacts suite first."
            )
        return artifact_dir, ndi_session_dir("exp1", artifact_dir)

    def test_blank_session_vhlab_summary(self, source_type):
        """Verify that the live session summary matches sessionSummary.json."""
        artifact_dir, session = self._open_session(source_type)

        summary_path = artifact_dir / "sessionSummary.json"
        if not summary_path.exists():
            pytest.skip(f"sessionSummary.json not found in {source_type} artifact directory.")

        expected_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        actual_summary = sessionSummary(session)

        sort_daq_systems_by_name(actual_summary)
        sort_daq_systems_by_name(expected_summary)

        report = compareSessionSummary(
            actual_summary,
            expected_summary,
            excludeFiles=["sessionSummary.json", "jsonDocuments"],
        )

        assert (
            len(report) == 0
        ), f"Session summary mismatch against {source_type} generated artifacts:\n" + "\n".join(
            report
        )
