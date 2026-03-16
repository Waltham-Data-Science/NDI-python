"""Generate symmetry artifacts for an NDI dataset with an ingested session.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+dataset/buildDataset.m

This test creates an NDI Dataset containing an ingested DirSession with
5 demoNDI documents (each with a file attachment), then persists the
dataset database, a ``datasetSummary.json`` manifest, and individual JSON
representations of every document into:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/dataset/buildDataset/
             testBuildDatasetArtifacts/

The artifacts are left on disk so that the MATLAB ``readArtifacts`` suite
(and the Python ``read_artifacts`` suite) can load and verify them.
"""

import json
import shutil

import pytest

from ndi.dataset import Dataset
from ndi.document import Document
from ndi.query import Query
from ndi.session.dir import DirSession
from ndi.util import sessionSummary
from tests.symmetry.conftest import PYTHON_ARTIFACTS

ARTIFACT_DIR = PYTHON_ARTIFACTS / "dataset" / "buildDataset" / "testBuildDatasetArtifacts"


def _add_doc_with_file(session: DirSession, doc_number: int) -> None:
    """Add a demoNDI document with a file attachment to the session."""
    docname = f"doc_{doc_number}"
    filepath = session.path / docname
    filepath.write_text(docname)

    doc = Document("demoNDI")
    props = doc.document_properties
    props["base"]["name"] = docname
    props["demoNDI"]["value"] = doc_number
    props["base"]["session_id"] = session.id()
    doc = Document(props)
    doc = doc.add_file("filename1.ext", str(filepath))
    session.database_add(doc)


def _dataset_summary(dataset: Dataset) -> dict:
    """Create a summary structure for a dataset.

    Mirrors MATLAB's ``ndi.symmetry.makeArtifacts.dataset.buildDataset``
    which writes: numSessions, references, sessionIds, sessionSummaries.
    """
    refs, session_ids, *_ = dataset.session_list()
    num_sessions = len(refs)

    # Build a session summary for each session in the dataset
    session_summaries = []
    for sid in session_ids:
        sess = dataset.open_session(sid)
        session_summaries.append(sessionSummary(sess))

    return {
        "numSessions": num_sessions,
        "references": refs,
        "sessionIds": session_ids,
        "sessionSummaries": session_summaries,
    }


class TestBuildDataset:
    """Mirror of ndi.symmetry.makeArtifacts.dataset.buildDataset."""

    # -- setup ----------------------------------------------------------------

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """Build a dataset with an ingested session in a temporary directory.

        Mirrors the MATLAB ``buildDatasetSetup`` method.
        """
        # Create a session with 5 demoNDI documents + file attachments
        session_dir = tmp_path / "session_src"
        session_dir.mkdir()
        session = DirSession("exp_demo", session_dir)

        for i in range(1, 6):
            _add_doc_with_file(session, i)

        # Create the dataset and ingest the session
        dataset_dir = tmp_path / "ds_demo"
        dataset_dir.mkdir()
        dataset = Dataset(dataset_dir, "ds_demo")
        dataset.add_ingested_session(session)

        self.dataset = dataset
        self.session = session

    # -- tests ----------------------------------------------------------------

    def test_build_dataset_artifacts(self):
        """Export the dataset to the shared symmetry artifact directory."""
        artifact_dir = ARTIFACT_DIR

        # Clear previous artifacts
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)

        # Copy the entire dataset directory to the persistent artifact dir.
        shutil.copytree(str(self.dataset.getpath()), str(artifact_dir))

        # Write individual JSON documents.
        json_docs_dir = artifact_dir / "jsonDocuments"
        json_docs_dir.mkdir(exist_ok=True)

        docs = self.dataset.database_search(Query("base.id").match("(.*)"))
        for doc in docs:
            props = doc.document_properties
            doc_path = json_docs_dir / f"{doc.id}.json"
            doc_path.write_text(json.dumps(props, indent=2, allow_nan=True), encoding="utf-8")

        # Write datasetSummary.json
        summary = _dataset_summary(self.dataset)
        summary_json = json.dumps(summary, indent=2, allow_nan=True)
        summary_path = artifact_dir / "datasetSummary.json"
        summary_path.write_text(summary_json, encoding="utf-8")

        # Verify artifacts were created
        assert artifact_dir.exists()
        assert summary_path.exists()
        assert json_docs_dir.exists()
        assert len(list(json_docs_dir.glob("*.json"))) > 0
