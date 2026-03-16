"""Generate symmetry artifacts for a basic NDI session.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+session/buildSession.m

This test creates an NDI ndi_session_dir with a subject and a subjectmeasurement
document, then persists the session database, a ``sessionSummary.json``
manifest, and individual JSON representations of every document into:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/session/buildSession/
             testBuildSessionArtifacts/

The artifacts are left on disk so that the MATLAB ``readArtifacts`` suite
(and the Python ``read_artifacts`` suite) can load and verify them.
"""

import json
import shutil

import pytest

from ndi.query import ndi_query
from ndi.session.dir import ndi_session_dir
from ndi.subject import ndi_subject
from ndi.util import sessionSummary
from tests.symmetry.conftest import PYTHON_ARTIFACTS

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

        session = ndi_session_dir("exp1", session_dir)
        session.database_clear("yes")
        session.cache.clear()

        # Add a subject
        subject = ndi_subject("anteater27@nosuchlab.org", "")
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

        # Add DAQ system documents (filenavigator, daqreader, daqsystem).
        # MATLAB's buildSession creates an Intan DAQ system with actual
        # data files.  We create the same document structure without raw
        # data files so the database search / load round-trip is tested.
        fn_doc = session.newdocument(
            "daq/filenavigator",
            **{
                "base.name": "unknown",
                "filenavigator.ndi_filenavigator_class": "ndi.file.navigator",
                "filenavigator.fileparameters": "{ '#.rhd' }",
                "filenavigator.epochprobemap_class": "ndi.epoch.epochprobemap_daqsystem",
                "filenavigator.epochprobemap_fileparameters": "{ '#.epochprobemap.ndi' }",
            },
        )
        session.database_add(fn_doc)

        dr_doc = session.newdocument(
            "daq/daqreader",
            **{
                "base.name": "intan_reader",
                "daqreader.ndi_daqreader_class": "ndi.daq.reader.mfdaq.intan",
            },
        )
        session.database_add(dr_doc)

        daq_doc = session.newdocument(
            "daq/daqsystem",
            **{
                "base.name": "intan1",
                "daqsystem.ndi_daqsystem_class": "ndi.daq.system.mfdaq",
            },
        )
        daq_doc = daq_doc.set_dependency_value(
            "filenavigator_id", fn_doc.id, error_if_not_found=False
        )
        daq_doc = daq_doc.set_dependency_value("daqreader_id", dr_doc.id, error_if_not_found=False)
        session.database_add(daq_doc)

        self.session = session
        # No teardown — artifacts must persist for readArtifacts.

    # -- tests ---------------------------------------------------------------

    def test_build_session_artifacts(self):
        """Export the session to the shared symmetry artifact directory."""
        artifact_dir = ARTIFACT_DIR

        # Clear previous artifacts
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)

        # Call getprobes() BEFORE copying to generate any internal documents.
        self.session.getprobes()

        # Re-open the session to ensure all internal documents are flushed.
        session_path = self.session.path
        self.session = ndi_session_dir("exp1", session_path)

        # Create comprehensive session summary
        summary = sessionSummary(self.session)
        summary_json = json.dumps(summary, indent=2, allow_nan=True)

        # Copy the entire session directory to the persistent artifact dir.
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

        # Verify artifacts were created
        assert artifact_dir.exists()
        assert summary_path.exists()
        assert json_docs_dir.exists()
        assert len(list(json_docs_dir.glob("*.json"))) > 0
