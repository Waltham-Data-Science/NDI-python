"""Generate symmetry artifacts for an ingested Intan session.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+session/ingestionIntan.m

This test creates an NDI session with a real Intan .rhd data file,
ingests the session, deletes raw data files (keeping only the .ndi
database), and exports the resulting artifacts to:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/session/ingestionIntan/
             testIngestionIntanArtifacts/

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
    setup_intan_session,
)

ARTIFACT_DIR = PYTHON_ARTIFACTS / "session" / "ingestionIntan" / "testIngestionIntanArtifacts"


def _have_intan_data() -> bool:
    try:
        from tests.symmetry.make_artifacts.session._ingestion_helpers import (
            _find_intan_rhd,
        )

        return _find_intan_rhd() is not None
    except Exception:
        return False


@pytest.mark.skipif(not _have_intan_data(), reason="Intan example data (.rhd) not found")
class TestIngestionIntan:
    """Mirror of ndi.symmetry.makeArtifacts.session.ingestionIntan."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """Build an Intan session in a temporary directory.

        Mirrors the MATLAB ``buildSession`` setup with real .rhd data
        and the native Intan DAQ reader.
        """
        session_dir = tmp_path / "exp1"
        session_dir.mkdir()

        session = ndi_session_dir("exp1", session_dir)
        session.cache.clear()

        # Copy Intan data file and create epochprobemap
        setup_intan_session(session_dir, reader_class="intan")

        # Add DAQ system via documents (filenavigator + daqreader + daqsystem)
        fn_doc = session.newdocument(
            "daq/filenavigator",
            **{
                "base.name": "unknown",
                "filenavigator.ndi_filenavigator_class": "ndi.file.navigator",
                "filenavigator.fileparameters": "{ '#.rhd', '#.epochprobemap.ndi' }",
                "filenavigator.epochprobemap_class": "ndi.epoch.epochprobemap_daqsystem",
                "filenavigator.epochprobemap_fileparameters": "{ '(.*?)epochprobemap.ndi' }",
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

        # Add subject
        subject = ndi_subject("anteater27@nosuchlab.org", "")
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

    def test_ingestion_intan_artifacts(self):
        """Ingest, strip raw files, and export artifacts."""
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

        # Copy session to persistent artifact directory
        shutil.copytree(str(self.session.path), str(artifact_dir))

        # Write individual JSON documents into the artifact directory
        json_docs_dir = artifact_dir / "jsonDocuments"
        json_docs_dir.mkdir(exist_ok=True)

        # Re-open session from the artifact directory so the summary
        # reflects the final directory contents (including jsonDocuments/)
        # that MATLAB will see when it opens the same artifacts.
        artifact_session = ndi_session_dir("exp1", artifact_dir)

        docs = artifact_session.database_search(ndi_query("base.id").match("(.*)"))
        for doc in docs:
            props = doc.document_properties
            doc_path = json_docs_dir / f"{doc.id}.json"
            doc_path.write_text(json.dumps(props, indent=2, allow_nan=True), encoding="utf-8")

        # Write a placeholder sessionSummary.json BEFORE computing the
        # summary so that the file list includes it (matching what MATLAB
        # will see when it opens the artifacts and computes its own summary).
        summary_path = artifact_dir / "sessionSummary.json"
        summary_path.write_text("{}", encoding="utf-8")

        # Generate session summary from the artifact session
        summary = sessionSummary(artifact_session)
        summary_json = json.dumps(summary, indent=2, allow_nan=True)
        summary_path.write_text(summary_json, encoding="utf-8")

        # Verify artifacts were created
        assert artifact_dir.exists()
        assert summary_path.exists()
        assert json_docs_dir.exists()
        assert len(list(json_docs_dir.glob("*.json"))) > 0
