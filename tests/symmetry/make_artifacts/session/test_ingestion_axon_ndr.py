"""Generate symmetry artifacts for an ingested Axon NDR session.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+session/ingestionAxonNDR.m

This test creates an NDI session with a real Axon .abf data file using
the NDR (Neuroscience Data Reader) wrapper reader, ingests the session,
deletes raw data files (keeping only the .ndi database), and exports the
resulting artifacts to:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/session/ingestionAxonNDR/
             testIngestionAxonNDRArtifacts/

Note: The MATLAB test uses ``Artifacts`` (American spelling) in the
artifact directory name; we match that exactly so both languages write
to the same artifact directory path.

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
from tests.symmetry.make_artifacts.session._ingestion_helpers import (
    delete_raw_files,
    setup_axon_session,
)

ARTIFACT_DIR = PYTHON_ARTIFACTS / "session" / "ingestionAxonNDR" / "testIngestionAxonNDRArtifacts"


def _have_axon_data() -> bool:
    try:
        from tests.symmetry.make_artifacts.session._ingestion_helpers import (
            _find_axon_abf,
        )

        return _find_axon_abf() is not None
    except Exception:
        return False


@pytest.mark.skipif(not _have_axon_data(), reason="Axon example data (.abf) not found")
class TestIngestionAxonNDR:
    """Mirror of ndi.symmetry.makeArtifacts.session.ingestionAxonNDR."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """Build an Axon NDR session in a temporary directory.

        Mirrors the MATLAB ``buildSessionNDRAxon`` setup with real .abf
        data and the NDR wrapper reader.
        """
        session_dir = tmp_path / "exp1"
        session_dir.mkdir()

        session = ndi_session_dir("exp1", session_dir)
        session.database_clear("yes")
        session.cache.clear()

        # Copy Axon data file and create epochprobemap
        setup_axon_session(session_dir)

        # Add DAQ system via documents (filenavigator + daqreader + daqsystem)
        fn_doc = session.newdocument(
            "daq/filenavigator",
            **{
                "base.name": "unknown",
                "filenavigator.ndi_filenavigator_class": "ndi.file.navigator",
                "filenavigator.fileparameters": "{ '#.abf', '#.epochprobemap.ndi' }",
                "filenavigator.epochprobemap_class": "ndi.epoch.epochprobemap_daqsystem",
                "filenavigator.epochprobemap_fileparameters": "{ '(.*?)epochprobemap.ndi' }",
            },
        )
        session.database_add(fn_doc)

        dr_doc = session.newdocument(
            "daq/daqreader_ndr",
            **{
                "base.name": "axon_ndr_reader",
                "daqreader.ndi_daqreader_class": "ndi.daq.reader.mfdaq.ndr",
            },
        )
        session.database_add(dr_doc)

        daq_doc = session.newdocument(
            "daq/daqsystem",
            **{
                "base.name": "axon1",
                "daqsystem.ndi_daqsystem_class": "ndi.daq.system.mfdaq",
            },
        )
        daq_doc = daq_doc.set_dependency_value(
            "filenavigator_id", fn_doc.id, error_if_not_found=False
        )
        daq_doc = daq_doc.set_dependency_value("daqreader_id", dr_doc.id, error_if_not_found=False)
        session.database_add(daq_doc)

        # Add subject (note: Axon uses "anteateri27" — matches MATLAB buildSessionNDRAxon)
        subject = ndi_subject("anteateri27@nosuchlab.org", "")
        session.database_add(subject.newdocument())

        # Add subjectmeasurement document
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

    def test_ingestion_axon_ndr_artefacts(self):
        """Ingest via NDR reader, strip raw files, and export artifacts."""
        artifact_dir = ARTIFACT_DIR

        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)

        # Call getprobes() BEFORE ingestion to generate internal documents.
        self.session.getprobes()

        # Ingest the session
        success, msg = self.session.ingest()
        assert success, f"Ingestion failed: {msg}"

        # Delete raw data files (keep only .ndi database)
        delete_raw_files(self.session.path)

        # Clear cache and re-open the session
        self.session.cache.clear()
        session_path = self.session.path
        self.session = ndi_session_dir("exp1", session_path)

        # Create session summary
        summary = sessionSummary(self.session)
        summary_json = json.dumps(summary, indent=2, allow_nan=True)

        # Copy session to persistent artifact directory
        shutil.copytree(str(session_path), str(artifact_dir))

        # Write individual JSON documents
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
