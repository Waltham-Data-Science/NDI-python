"""Generate symmetry artifacts for a blank vhlab NDI session.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+session/blankSessionVhlab.m

This test creates a blank NDI session configured with the vhlab DAQ
systems (from ``ndi_common/daq_systems/vhlab/``), then persists the
session database, a ``sessionSummary.json`` manifest, and individual JSON
representations of every document into:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/session/blankSessionVhlab/
             testBlankSessionVhlab/

The artifacts are left on disk so that the MATLAB ``readArtifacts`` suite
(and the Python ``read_artifacts`` suite) can load and verify them.
"""

import json
import shutil

import pytest

from ndi.query import ndi_query
from ndi.session.dir import ndi_session_dir
from ndi.util import sessionSummary
from tests.symmetry.conftest import PYTHON_ARTIFACTS
import ndi.setup

ARTIFACT_DIR = (
    PYTHON_ARTIFACTS / "session" / "blankSessionVhlab" / "testBlankSessionVhlab"
)


class TestBlankSessionVhlab:
    """Mirror of ndi.symmetry.makeArtifacts.session.blankSessionVhlab."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """Create a blank session with vhlab DAQ systems."""
        session_dir = tmp_path / "exp1"
        session_dir.mkdir()

        session = ndi_session_dir("exp1", session_dir)
        session.database_clear("yes")
        session.cache.clear()

        ndi.setup.lab(session, "vhlab")

        self.session = session

    def test_blank_session_vhlab(self):
        """Export the blank vhlab session to the shared symmetry artifact directory."""
        artifact_dir = ARTIFACT_DIR

        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)

        # Re-open the session to ensure all internal documents are flushed.
        session_path = self.session.path
        self.session = ndi_session_dir("exp1", session_path)

        summary = sessionSummary(self.session)
        summary_json = json.dumps(summary, indent=2, allow_nan=True)

        shutil.copytree(str(session_path), str(artifact_dir))

        # Write individual JSON documents.
        json_docs_dir = artifact_dir / "jsonDocuments"
        json_docs_dir.mkdir(exist_ok=True)

        docs = self.session.database_search(ndi_query("base.id").match("(.*)"))
        for doc in docs:
            props = doc.document_properties
            doc_path = json_docs_dir / f"{doc.id}.json"
            doc_path.write_text(json.dumps(props, indent=2, allow_nan=True), encoding="utf-8")

        # Write sessionSummary.json
        summary_path = artifact_dir / "sessionSummary.json"
        summary_path.write_text(summary_json, encoding="utf-8")

        assert artifact_dir.exists()
        assert summary_path.exists()
        assert json_docs_dir.exists()
