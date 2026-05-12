"""Generate symmetry artifacts for a blank rayolab NDI session.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+session/blankSessionRayolab.m

Builds a blank NDI session configured with the rayolab DAQ systems
(rayo_intanSeries + rayo_stim, both using the rhd_series file navigator),
then copies the entire session tree plus a sessionSummary.json manifest
and per-document JSON dumps to the shared symmetry artifact directory at::

    <tempdir>/NDI/symmetryTest/pythonArtifacts/session/blankSessionRayolab/
             testBlankSessionRayolab/

Artifacts are left on disk so the MATLAB readArtifacts suite and the
python read_artifacts suite can verify cross-language parity.
"""

import json
import shutil

import pytest

import ndi.setup
from ndi.query import ndi_query
from ndi.session.dir import ndi_session_dir
from ndi.util import sessionSummary
from tests.symmetry.conftest import PYTHON_ARTIFACTS

ARTIFACT_DIR = PYTHON_ARTIFACTS / "session" / "blankSessionRayolab" / "testBlankSessionRayolab"


class TestBlankSessionRayolab:
    """Mirror of ndi.symmetry.makeArtifacts.session.blankSessionRayolab."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """Create a blank session with rayolab DAQ systems."""
        session_dir = tmp_path / "exp1"
        session_dir.mkdir()

        session = ndi_session_dir("exp1", session_dir)
        session.cache.clear()

        # ndi.setup.rayolab(session) mutates the session in place,
        # adding the rayo_intanSeries and rayo_stim DAQ systems.
        ndi.setup.rayolab(session)

        self.session = session

    def test_blank_session_rayolab(self):
        """Export the blank rayolab session to the symmetry artifact dir."""
        artifact_dir = ARTIFACT_DIR
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)

        # Re-open the session to capture any auto-generated documents.
        session_path = self.session.path
        self.session = ndi_session_dir("exp1", session_path)

        summary = sessionSummary(self.session)
        summary_json = json.dumps(summary, indent=2, allow_nan=True)

        # Copy the entire session tree into the artifact dir, matching the
        # matlab side's copyfile(SessionPath, artifactDir).
        shutil.copytree(str(session_path), str(artifact_dir))

        # Per-document JSON dumps so the matlab readArtifacts side can
        # cross-check individual documents if desired.
        json_docs_dir = artifact_dir / "jsonDocuments"
        json_docs_dir.mkdir(exist_ok=True)

        docs = self.session.database_search(ndi_query("base.id").match("(.*)"))
        for doc in docs:
            props = doc.document_properties
            doc_path = json_docs_dir / f"{doc.id}.json"
            doc_path.write_text(
                json.dumps(props, indent=2, allow_nan=True),
                encoding="utf-8",
            )

        summary_path = artifact_dir / "sessionSummary.json"
        summary_path.write_text(summary_json, encoding="utf-8")

        assert artifact_dir.exists()
        assert summary_path.exists()
        assert json_docs_dir.exists()
