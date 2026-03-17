"""Read and verify symmetry artifacts for an NDI dataset with ingested session.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+dataset/buildDataset.m

This test loads artifacts produced by *either* the MATLAB or the Python
``makeArtifacts`` suite and verifies that the Python NDI stack can:

1. Open the copied dataset database.
2. Verify the session list matches ``datasetSummary.json``.
3. Compare session summaries for each session in the dataset.
4. Load every document whose JSON was exported to ``jsonDocuments/``.

The MATLAB ``datasetSummary.json`` contains:
    numSessions, references, sessionIds, sessionSummaries

The test is parameterized over ``source_type`` so that a single test class
covers both ``matlabArtifacts`` and ``pythonArtifacts``.
"""

import json

import pytest

from ndi.dataset import Dataset
from ndi.query import Query
from ndi.util import compareSessionSummary, sessionSummary
from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE


@pytest.fixture(params=SOURCE_TYPES)
def source_type(request):
    """Parameterize over matlabArtifacts / pythonArtifacts."""
    return request.param


class TestBuildDataset:
    """Mirror of ndi.symmetry.readArtifacts.dataset.buildDataset."""

    def _artifact_dir(self, source_type: str):
        return (
            SYMMETRY_BASE / source_type / "dataset" / "buildDataset" / "testBuildDatasetArtifacts"
        )

    def _open_dataset(self, source_type):
        artifact_dir = self._artifact_dir(source_type)
        if not artifact_dir.exists():
            pytest.skip(
                f"Artifact directory from {source_type} does not exist. "
                f"Run the corresponding makeArtifacts suite first."
            )
        return artifact_dir, Dataset(artifact_dir)

    # -- tests ----------------------------------------------------------------

    def test_build_dataset_summary(self, source_type):
        """Verify session counts, references, and IDs match datasetSummary.json."""
        artifact_dir, dataset = self._open_dataset(source_type)

        summary_path = artifact_dir / "datasetSummary.json"
        if not summary_path.exists():
            pytest.skip(f"datasetSummary.json not found in {source_type} artifact directory.")

        expected = json.loads(summary_path.read_text(encoding="utf-8"))

        # Verify session list
        refs, session_ids, *_ = dataset.session_list()
        num_sessions = len(refs)

        expected_num = expected.get("numSessions", 0)
        expected_ids = expected.get("sessionIds", [])
        expected_refs = expected.get("references", [])

        assert num_sessions == expected_num, (
            f"Session count mismatch in {source_type}: "
            f"got {num_sessions}, expected {expected_num}"
        )

        for exp_id in expected_ids:
            assert exp_id in session_ids, (
                f"Expected session ID {exp_id!r} not found in dataset " f"from {source_type}"
            )

        for exp_ref in expected_refs:
            assert exp_ref in refs, (
                f"Expected session reference {exp_ref!r} not found in dataset "
                f"from {source_type}"
            )

    def test_build_dataset_session_summaries(self, source_type):
        """Compare per-session summaries against those stored in datasetSummary.json."""
        artifact_dir, dataset = self._open_dataset(source_type)

        summary_path = artifact_dir / "datasetSummary.json"
        if not summary_path.exists():
            pytest.skip(f"datasetSummary.json not found in {source_type} artifact directory.")

        expected = json.loads(summary_path.read_text(encoding="utf-8"))
        expected_summaries = expected.get("sessionSummaries", [])
        expected_ids = expected.get("sessionIds", [])

        if not expected_summaries:
            pytest.skip(f"No sessionSummaries in {source_type} datasetSummary.json.")

        for i, sid in enumerate(expected_ids):
            if i >= len(expected_summaries):
                break

            sess = dataset.open_session(sid)
            if sess is None:
                pytest.fail(f"Could not open session {sid} from {source_type} dataset.")

            actual_summary = sessionSummary(sess)
            expected_summary = expected_summaries[i]

            report = compareSessionSummary(
                actual_summary,
                expected_summary,
                excludeFiles=["datasetSummary.json", "jsonDocuments"],
            )

            assert len(report) == 0, (
                f"Session summary mismatch for session {sid} "
                f"in {source_type} dataset:\n" + "\n".join(report)
            )

    def test_build_dataset_documents(self, source_type):
        """Verify that every exported JSON document can be loaded from the dataset DB."""
        artifact_dir, dataset = self._open_dataset(source_type)

        json_docs_dir = artifact_dir / "jsonDocuments"
        if not json_docs_dir.exists():
            pytest.skip(f"jsonDocuments directory not found in {source_type}.")

        json_files = list(json_docs_dir.glob("*.json"))

        actual_docs = dataset.database_search(Query("base.id").match("(.*)"))

        assert len(actual_docs) == len(json_files), (
            f"Number of documents in dataset ({len(actual_docs)}) does not match "
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
                        f"Document class mismatch for id: {expected_id} " f"in {source_type}"
                    )
                    break
            assert found, (
                f"Document from {source_type} artifact not found in dataset: " f"{expected_id}"
            )
