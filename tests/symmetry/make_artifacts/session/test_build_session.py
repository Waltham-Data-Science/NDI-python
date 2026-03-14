"""Generate symmetry artifacts for a basic NDI session.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+session/buildSession.m

This test creates an NDI DirSession with a subject and a subjectmeasurement
document, then persists the session database, a ``probes.json`` manifest,
and individual JSON representations of every document into:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/session/buildSession/
             testBuildSessionArtifacts/

The artifacts are left on disk so that the MATLAB ``readArtifacts`` suite
(and the Python ``read_artifacts`` suite) can load and verify them.
"""

import json
import shutil
from pathlib import Path

import pytest

from tests.symmetry.conftest import PYTHON_ARTIFACTS

from ndi.document import Document
from ndi.query import Query
from ndi.session.dir import DirSession
from ndi.subject import Subject

ARTIFACT_DIR = PYTHON_ARTIFACTS / "session" / "buildSession" / "testBuildSessionArtifacts"


class TestBuildSession:
    """Mirror of ndi.symmetry.makeArtifacts.session.buildSession."""

    # -- setup / teardown ----------------------------------------------------

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """Build an example session in a temporary directory.

        Mirrors the MATLAB ``buildSessionSetup`` method.  Because Python
        does not ship the Intan example binary, the session is built
        without raw acquisition files — only structured NDI documents.
        """
        session_dir = tmp_path / "exp1"
        session_dir.mkdir()

        session = DirSession("exp1", session_dir)
        session.database_clear("yes")
        session.cache.clear()

        # Add a subject
        subject = Subject("anteater27@nosuchlab.org", "")
        session.database_add(subject.newdocument())

        # Add a subjectmeasurement document
        doc = session.newdocument(
            "subjectmeasurement",
            **{
                "base.name": "Animal statistics",
                "subjectmeasurement.measurement": "age",
                "subjectmeasurement.value": 30,
                "subjectmeasurement.datestamp": "2017-03-17T19:53:57.066Z",
            },
        )
        doc = doc.set_dependency_value("subject_id", subject.id, error_if_not_found=False)
        session.database_add(doc)

        self.session = session
        # No teardown — artifacts must persist for readArtifacts.

    # -- tests ---------------------------------------------------------------

    def test_build_session_artifacts(self):
        """Export the session to the shared symmetry artifact directory."""
        artifact_dir = ARTIFACT_DIR

        # Clear previous artifacts
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)

        # Gather probe information *before* copying the session so that
        # any internally-generated documents are captured.
        probes = self.session.getprobes()
        probe_dicts = []
        for p in probes:
            probe_dicts.append(
                {
                    "name": p.name,
                    "reference": p.reference,
                    "type": p.type,
                    "subject_id": getattr(p, "subject_id", ""),
                }
            )

        # Re-open the session to ensure all internal documents are flushed.
        session_path = self.session.path
        self.session = DirSession("exp1", session_path)

        # Copy the entire session directory to the persistent artifact dir.
        shutil.copytree(str(session_path), str(artifact_dir))

        # Write individual JSON documents.
        json_docs_dir = artifact_dir / "jsonDocuments"
        json_docs_dir.mkdir(exist_ok=True)

        docs = self.session.database_search(Query("base.id").match("(.*)"))
        for doc in docs:
            props = doc.document_properties
            doc_path = json_docs_dir / f"{doc.id}.json"
            doc_path.write_text(json.dumps(props, indent=2, allow_nan=True), encoding="utf-8")

        # Write probes.json
        probes_path = artifact_dir / "probes.json"
        probes_path.write_text(json.dumps(probe_dicts, indent=2, allow_nan=True), encoding="utf-8")

        # Verify artifacts were created
        assert artifact_dir.exists()
        assert probes_path.exists()
        assert json_docs_dir.exists()
        assert len(list(json_docs_dir.glob("*.json"))) > 0
