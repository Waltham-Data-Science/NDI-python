"""Read and verify symmetry artifacts for a blank rayolab NDI session.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+session/blankSessionRayolab.m

Loads the artifact directory written by the rayolab makeArtifacts pair
(in either pythonArtifacts or matlabArtifacts) and verifies:

- the session opens cleanly via ndi.session.dir;
- exactly two DAQ systems are present, named 'rayo_intanSeries' and
  'rayo_stim';
- both DAQ systems use ndi.file.navigator.rhd_series as their file
  navigator (asserted via the MATLAB-compatible NDI_FILENAVIGATOR_CLASS
  string for cross-language parity);
- the sessionSummary.json manifest, if present, matches the live
  summary produced by sessionSummary() (with daq-system order
  normalized to avoid spurious failures).
"""

import json

import pytest

from ndi.session.dir import ndi_session_dir
from ndi.util import compareSessionSummary, sessionSummary
from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE
from tests.symmetry.read_artifacts.session._summary_helpers import (
    sort_daq_systems_by_name,
)

EXPECTED_DAQ_NAMES = {"rayo_intanSeries", "rayo_stim"}
RHD_SERIES_CLASS = "ndi.file.navigator.rhd_series"


@pytest.fixture(params=SOURCE_TYPES)
def source_type(request):
    return request.param


class TestBlankSessionRayolab:
    """Mirror of ndi.symmetry.readArtifacts.session.blankSessionRayolab."""

    def _artifact_dir(self, source_type: str):
        return (
            SYMMETRY_BASE
            / source_type
            / "session"
            / "blankSessionRayolab"
            / "testBlankSessionRayolab"
        )

    def _open_session(self, source_type):
        artifact_dir = self._artifact_dir(source_type)
        if not artifact_dir.exists():
            pytest.skip(
                f"Artifact directory from {source_type} does not exist. "
                f"Run the corresponding makeArtifacts suite first."
            )
        return artifact_dir, ndi_session_dir("exp1", artifact_dir)

    def test_blank_session_rayolab_daq_systems(self, source_type):
        """Verify rayo_intanSeries + rayo_stim are present with rhd_series."""
        _artifact_dir, session = self._open_session(source_type)

        daqs = session.daqsystem_load(name="(.*)")
        if daqs is None:
            daqs = []
        elif not isinstance(daqs, list):
            daqs = [daqs]

        assert len(daqs) == 2, (
            f"Expected 2 DAQ systems in {source_type} rayolab session, "
            f"got {len(daqs)}."
        )

        names = {getattr(d, "name", "") for d in daqs}
        for expected in EXPECTED_DAQ_NAMES:
            assert expected in names, (
                f"Expected DAQ system {expected!r} not found in {source_type}; "
                f"got {sorted(names)!r}."
            )

        # Each DAQ system should use ndi.file.navigator.rhd_series. We
        # compare against the MATLAB-compatible class string carried by
        # the python navigator (NDI_FILENAVIGATOR_CLASS) so a matlab- or
        # python-written session both pass this check.
        for d in daqs:
            nav = getattr(d, "filenavigator", None)
            assert nav is not None, (
                f"DAQ system {d.name!r} has no filenavigator in {source_type}."
            )
            nav_class = getattr(nav, "NDI_FILENAVIGATOR_CLASS", "")
            assert nav_class == RHD_SERIES_CLASS, (
                f"DAQ system {d.name!r} should use {RHD_SERIES_CLASS} in "
                f"{source_type}, got {nav_class!r}."
            )

    def test_blank_session_rayolab_summary(self, source_type):
        """Verify the on-disk session summary matches the live summary."""
        artifact_dir, session = self._open_session(source_type)

        summary_path = artifact_dir / "sessionSummary.json"
        if not summary_path.is_file():
            pytest.skip(
                f"sessionSummary.json not found in {source_type} artifact dir; "
                f"skipping summary comparison."
            )

        expected_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        actual_summary = sessionSummary(session)

        sort_daq_systems_by_name(actual_summary)
        sort_daq_systems_by_name(expected_summary)

        report = compareSessionSummary(
            actual_summary,
            expected_summary,
            excludeFiles=["sessionSummary.json", "jsonDocuments"],
        )
        assert len(report) == 0, (
            f"Session summary mismatch against {source_type} generated "
            f"artifacts:\n" + "\n".join(report)
        )
