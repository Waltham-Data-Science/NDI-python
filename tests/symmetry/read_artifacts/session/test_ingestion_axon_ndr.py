"""Read and verify symmetry artifacts for an ingested Axon NDR session.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+session/ingestionAxonNDR.m

This test loads artifacts produced by *either* the MATLAB or the Python
``makeArtifacts`` suite and verifies that the Python NDI stack can:

1. Open the ingested session database (raw files have been removed).
2. Generate a live session summary that matches the stored ``sessionSummary.json``.
3. Load every document whose JSON was exported to ``jsonDocuments/``.

Note: The MATLAB test uses British spelling ``Artefacts`` in the test
method / artifact directory name; we match that exactly.

The test is parameterized over ``source_type`` so that a single test class
covers both ``matlabArtifacts`` and ``pythonArtifacts``.
"""

import json

import pytest

from ndi.query import ndi_query
from ndi.session.dir import ndi_session_dir
from ndi.util import compareSessionSummary, sessionSummary
from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE


@pytest.fixture(params=SOURCE_TYPES)
def source_type(request):
    """Parameterize over matlabArtifacts / pythonArtifacts."""
    return request.param


class TestIngestionAxonNDR:
    """Mirror of ndi.symmetry.readArtifacts.session.ingestionAxonNDR."""

    def _artifact_dir(self, source_type: str):
        return (
            SYMMETRY_BASE
            / source_type
            / "session"
            / "ingestionAxonNDR"
            / "testIngestionAxonNDRArtefacts"
        )

    def _open_session(self, source_type):
        artifact_dir = self._artifact_dir(source_type)
        if not artifact_dir.exists():
            pytest.skip(
                f"Artifact directory from {source_type} does not exist. "
                f"Run the corresponding makeArtifacts suite first."
            )
        return artifact_dir, ndi_session_dir("exp1", artifact_dir)

    def test_ingestion_axon_ndr_summary(self, source_type):
        """Verify that the live session summary matches sessionSummary.json."""
        artifact_dir, session = self._open_session(source_type)

        summary_path = artifact_dir / "sessionSummary.json"
        if not summary_path.exists():
            pytest.skip(f"sessionSummary.json not found in {source_type} artifact directory.")

        expected_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        actual_summary = sessionSummary(session)

        exclude_fields = ["epochNodes_filenavigator", "epochNodes_daqsystem"]

        def _filter_epochid(files: list[str]) -> list[str]:
            return [f for f in files if not f.endswith(".epochid.ndi")]

        actual_summary["files"] = _filter_epochid(actual_summary.get("files", []))
        expected_summary["files"] = _filter_epochid(expected_summary.get("files", []))

        report = compareSessionSummary(
            actual_summary,
            expected_summary,
            excludeFiles=["sessionSummary.json", "jsonDocuments"],
            excludeFields=exclude_fields,
        )

        assert len(report) == 0, (
            f"ndi_session summary mismatch against {source_type} generated artifacts:\n"
            + "\n".join(report)
        )

    def test_ingestion_axon_ndr_documents(self, source_type):
        """Verify that every exported JSON document can be loaded from the session DB."""
        artifact_dir, session = self._open_session(source_type)

        json_docs_dir = artifact_dir / "jsonDocuments"
        if not json_docs_dir.exists():
            pytest.skip(f"jsonDocuments directory not found in {source_type}.")

        json_files = list(json_docs_dir.glob("*.json"))

        actual_docs = session.database_search(ndi_query("base.id").match("(.*)"))

        assert len(actual_docs) == len(json_files), (
            f"Number of documents in session ({len(actual_docs)}) does not match "
            f"{source_type} JSON artifacts ({len(json_files)})."
        )

        for jf in json_files:
            expected_doc = json.loads(jf.read_text(encoding="utf-8"))
            expected_id = expected_doc.get("base", {}).get("id", "")

            found = False
            for actual in actual_docs:
                if actual.id == expected_id:
                    found = True
                    actual_props = actual.document_properties
                    assert actual_props.get("document_class", {}).get(
                        "class_name"
                    ) == expected_doc.get("document_class", {}).get("class_name"), (
                        f"ndi_document class mismatch for id: {expected_id} " f"in {source_type}"
                    )
                    break
            assert found, (
                f"ndi_document from {source_type} artifact not found in session: " f"{expected_id}"
            )
