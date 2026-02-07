"""
Shared fixtures for MATLAB unit test ports.

These fixtures mirror the MATLAB base test classes:
- build_session     → ndi.unittest.session.buildSession
- session_with_docs → ndi.unittest.session.buildSession.withDocsAndFiles()
- build_dataset     → ndi.unittest.dataset.buildDataset.sessionWithIngestedDocsAndFiles()
"""

import os

import pytest

from ndi.dataset import Dataset
from ndi.document import Document
from ndi.session.dir import DirSession

# ---------------------------------------------------------------------------
# Marker for tests requiring live NDI Cloud credentials
# ---------------------------------------------------------------------------
requires_cloud = pytest.mark.skipif(
    not os.environ.get("NDI_CLOUD_USERNAME"),
    reason="NDI_CLOUD_USERNAME not set — skipping live cloud test",
)


# ---------------------------------------------------------------------------
# session_with_docs_and_files
# Mirrors: ndi.unittest.session.buildSession.withDocsAndFiles()
# Creates a DirSession with 5 demoNDI documents, each with a file attachment.
# ---------------------------------------------------------------------------


def _add_doc_with_file(session: DirSession, doc_number: int) -> None:
    """Add a demoNDI document with a file attachment to the session.

    Mirrors: ndi.unittest.session.buildSession.addDocsWithFiles()
    """
    docname = f"doc_{doc_number}"
    filepath = session.path / docname

    # Write file content
    filepath.write_text(docname)

    # Create document — merge demoNDI schema onto a session doc
    doc = Document("demoNDI")
    props = doc.document_properties
    props["base"]["name"] = docname
    props["demoNDI"]["value"] = doc_number
    props["base"]["session_id"] = session.id()
    doc = Document(props)

    # Attach file
    doc = doc.add_file("filename1.ext", str(filepath))

    session.database_add(doc)


@pytest.fixture
def session_with_docs(tmp_path):
    """Create a DirSession with 5 demoNDI documents + file attachments.

    Mirrors: ndi.unittest.session.buildSession.withDocsAndFiles()

    Yields (session, session_dir) so tests can inspect the directory.
    """
    session_dir = tmp_path / "exp_demo"
    session_dir.mkdir()
    session = DirSession("exp_demo", session_dir)

    for i in range(1, 6):
        _add_doc_with_file(session, i)

    yield session, session_dir

    # Cleanup handled by tmp_path


@pytest.fixture
def build_dataset(tmp_path):
    """Create a Dataset with an ingested session containing 5 demoNDI docs.

    Mirrors: ndi.unittest.dataset.buildDataset.sessionWithIngestedDocsAndFiles()

    Yields (dataset, session) tuple.
    """
    # Create the session first
    session_dir = tmp_path / "session_src"
    session_dir.mkdir()
    session = DirSession("exp_demo", session_dir)

    for i in range(1, 6):
        _add_doc_with_file(session, i)

    # Create the dataset
    dataset_dir = tmp_path / "ds_demo"
    dataset_dir.mkdir()
    dataset = Dataset(dataset_dir, "ds_demo")

    # Ingest the session into the dataset
    dataset.add_ingested_session(session)

    yield dataset, session

    # Cleanup handled by tmp_path
