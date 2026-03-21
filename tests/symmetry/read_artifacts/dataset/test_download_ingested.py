"""Read and verify symmetry artifacts for a downloaded ingested dataset.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+dataset/downloadIngested.m

This test loads artifacts produced by *either* the MATLAB or the Python
``makeArtifacts`` suite and verifies that the Python NDI stack can:

1. Open the downloaded dataset from the artifact directory.
2. Verify the session list matches ``datasetSummary.json``.
3. Compare session summaries for each session in the dataset.
4. Verify document counts per session when available.

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


class TestDownloadIngested:
    """Mirror of ndi.symmetry.readArtifacts.dataset.downloadIngested."""

    def _artifact_dir(self, source_type: str):
        return (
            SYMMETRY_BASE
            / source_type
            / "dataset"
            / "downloadIngested"
            / "testDownloadIngestedArtifacts"
        )

    def _open_dataset(self, source_type):
        artifact_dir = self._artifact_dir(source_type)
        if not artifact_dir.exists():
            pytest.skip(
                f"Artifact directory from {source_type} does not exist. "
                f"Run the corresponding makeArtifacts suite first."
            )

        summary_path = artifact_dir / "datasetSummary.json"
        if not summary_path.exists():
            pytest.skip(f"datasetSummary.json not found in {source_type} artifact directory.")

        # Find the single dataset subdirectory (name may differ from archive)
        subdirs = [
            p for p in artifact_dir.iterdir()
            if p.is_dir() and p.name != "jsonDocuments"
        ]
        if len(subdirs) != 1:
            pytest.skip(
                f"Expected exactly one dataset directory in {source_type} artifacts, "
                f"found {len(subdirs)}."
            )
        dataset_path = subdirs[0]

        expected = json.loads(summary_path.read_text(encoding="utf-8"))
        dataset = Dataset(dataset_path)
        return artifact_dir, dataset, expected

    # -- tests ----------------------------------------------------------------

    def test_download_ingested_summary(self, source_type):
        """Verify session counts, references, and IDs match datasetSummary.json."""
        _artifact_dir, dataset, expected = self._open_dataset(source_type)

        # Get session list from the dataset
        ref_list, id_list, *_ = dataset.session_list()
        num_sessions = len(ref_list)

        # Verify number of sessions
        expected_num = expected.get("numSessions", 0)
        assert num_sessions == expected_num, (
            f"Session count mismatch in {source_type}: "
            f"got {num_sessions}, expected {expected_num}"
        )

        # Verify references
        expected_refs = expected.get("references", [])
        assert sorted(ref_list) == sorted(
            expected_refs
        ), f"Session references mismatch against {source_type} generated artifacts."

        # Verify session IDs
        expected_ids = expected.get("sessionIds", [])
        assert sorted(id_list) == sorted(
            expected_ids
        ), f"Session IDs mismatch against {source_type} generated artifacts."

    def test_download_ingested_session_summaries(self, source_type):
        """Compare per-session summaries against datasetSummary.json."""
        _artifact_dir, dataset, expected = self._open_dataset(source_type)

        expected_summaries = expected.get("sessionSummaries", [])
        _ref_list, id_list, *_ = dataset.session_list()

        if not expected_summaries:
            pytest.skip(f"No sessionSummaries in {source_type} datasetSummary.json.")

        for sid in id_list:
            sess = dataset.open_session(sid)
            if sess is None:
                pytest.fail(f"Could not open session {sid} from {source_type} dataset.")

            actual_summary = sessionSummary(sess)

            # Filter macOS resource fork files (._*) from file lists;
            # these may be present in archives but MATLAB does not list them.
            def _filter_dot_underscore(files: list[str]) -> list[str]:
                return [f for f in files if not f.split("/")[-1].startswith("._")]

            for key in ("files", "filesInDotNDI"):
                if key in actual_summary:
                    actual_summary[key] = _filter_dot_underscore(actual_summary[key])

            # Find the expected summary with the matching sessionId
            match = None
            for es in expected_summaries:
                if es.get("sessionId") == sid:
                    match = es
                    break

            assert match is not None, (
                f"No expected session summary found for session ID " f"{sid} in {source_type}"
            )

            report = compareSessionSummary(
                actual_summary,
                match,
                excludeFiles=["datasetSummary.json", "jsonDocuments"],
            )

            assert len(report) == 0, (
                f"Session summary mismatch for session {sid} "
                f"in {source_type} dataset:\n" + "\n".join(report)
            )

    def test_download_ingested_document_counts(self, source_type):
        """Verify document counts per session match expected values."""
        _artifact_dir, dataset, expected = self._open_dataset(source_type)

        expected_doc_counts = expected.get("documentCounts")
        if not expected_doc_counts:
            pytest.skip(f"No documentCounts in {source_type} datasetSummary.json.")

        _ref_list, id_list, *_ = dataset.session_list()

        for sid in id_list:
            sess = dataset.open_session(sid)
            docs = sess.database_search(Query("base.id").match("(.*)"))
            actual_count = len(docs)

            # Find expected count for this session
            expected_count = None
            for dc in expected_doc_counts:
                if dc.get("sessionId") == sid:
                    expected_count = dc.get("count")
                    break

            if expected_count is not None:
                assert actual_count == expected_count, (
                    f"Document count mismatch for session {sid} "
                    f"against {source_type} generated artifacts: "
                    f"got {actual_count}, expected {expected_count}"
                )
