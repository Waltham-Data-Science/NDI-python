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
from ndi.util import compareDatasetSummary, datasetSummary
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
        subdirs = [p for p in artifact_dir.iterdir() if p.is_dir() and p.name != "jsonDocuments"]
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
        """Verify dataset summary matches datasetSummary.json."""
        _artifact_dir, dataset, expected = self._open_dataset(source_type)

        actual = datasetSummary(dataset)

        # Filter macOS resource fork files (._*) from file lists;
        # these may be present in archives but MATLAB does not list them.
        def _filter_dot_underscore(files: list[str]) -> list[str]:
            return [f for f in files if not f.split("/")[-1].startswith("._")]

        for ss in actual.get("sessionSummaries", []):
            for key in ("files", "filesInDotNDI"):
                if key in ss:
                    ss[key] = _filter_dot_underscore(ss[key])

        for ss in expected.get("sessionSummaries", []):
            for key in ("files", "filesInDotNDI"):
                if key in ss:
                    ss[key] = _filter_dot_underscore(ss[key])

        report = compareDatasetSummary(
            actual,
            expected,
            excludeFiles=["datasetSummary.json", "jsonDocuments"],
            excludeFields=["documentCounts"],
        )

        assert len(report) == 0, f"Dataset summary mismatch in {source_type}:\n" + "\n".join(report)

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
