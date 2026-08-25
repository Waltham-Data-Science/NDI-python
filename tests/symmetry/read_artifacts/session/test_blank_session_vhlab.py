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
from tests.symmetry.read_artifacts.session._lab_config_helpers import (
    assert_metadata_readers_agree,
    assert_metadata_readers_match_lab_config,
    assert_sync_rules_agree,
    assert_sync_rules_match_lab_config,
)
from tests.symmetry.read_artifacts.session._summary_helpers import (
    sort_daq_systems_by_name,
)

LAB_NAME = "vhlab"


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

    # ---- lab configuration (M4 / S1 defect fix) ---------------------------
    #
    # Added to this class rather than to a module of its own so the per-lab
    # context stays in one place.  Neither the daqmetadatareader file
    # parameters nor the syncrule documents appear in sessionSummary, so the
    # comparison above passed throughout the W3-A defect -- ndi.setup.lab()
    # dropping every metadata reader's file parameter and installing no sync
    # rules at all -- and would pass again if it regressed.  See
    # _lab_config_helpers for why the expectations come from the shared
    # ndi_common JSON rather than from ndi.setup.lab's own helpers.

    def test_blank_session_vhlab_metadata_reader_file_parameters(self, source_type):
        """Each daqmetadatareader carries the file parameter the lab config declares."""
        _artifact_dir, session = self._open_session(source_type)
        assert_metadata_readers_match_lab_config(session, LAB_NAME, source_type)

    def test_blank_session_vhlab_sync_rules_installed(self, source_type):
        """The lab's syncrules are installed, with their parameters intact."""
        _artifact_dir, session = self._open_session(source_type)
        assert_sync_rules_match_lab_config(session, LAB_NAME, source_type)

    def _open_both_languages(self):
        """Open the MATLAB and Python artifacts of this lab, or skip.

        Skips unless BOTH exist: a one-sided "comparison" would report success
        having compared one artifact to itself.
        """
        sessions = {}
        for source in SOURCE_TYPES:
            artifact_dir = self._artifact_dir(source)
            if not artifact_dir.is_dir():
                pytest.skip(
                    f"Cross-language comparison needs both artifact sets; "
                    f"{artifact_dir} ({source}) is missing."
                )
            sessions[source] = ndi_session_dir("exp1", artifact_dir)
        return sessions["pythonArtifacts"], sessions["matlabArtifacts"]

    def test_blank_session_vhlab_metadata_readers_agree_across_languages(self):
        """MATLAB and Python wrote the same per-DAQ-system metadata readers."""
        python_session, matlab_session = self._open_both_languages()
        assert_metadata_readers_agree(python_session, matlab_session, LAB_NAME)

    def test_blank_session_vhlab_sync_rules_agree_across_languages(self):
        """MATLAB and Python installed the same syncrules."""
        python_session, matlab_session = self._open_both_languages()
        assert_sync_rules_agree(python_session, matlab_session, LAB_NAME)
