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
from ndi.util import compareDatasetSummary, datasetSummary
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
        """Verify dataset summary matches datasetSummary.json."""
        artifact_dir, dataset = self._open_dataset(source_type)

        summary_path = artifact_dir / "datasetSummary.json"
        if not summary_path.exists():
            pytest.skip(f"datasetSummary.json not found in {source_type} artifact directory.")

        expected = json.loads(summary_path.read_text(encoding="utf-8"))
        actual = datasetSummary(dataset)

        report = compareDatasetSummary(
            actual,
            expected,
            excludeFiles=["datasetSummary.json", "jsonDocuments"],
        )

        assert len(report) == 0, (
            f"Dataset summary mismatch in {source_type}:\n" + "\n".join(report)
        )

    def test_build_dataset_documents(self, source_type):
        """Verify that every exported JSON document can be loaded from session DBs.

        Mirrors MATLAB which queries each session's database individually
        (not the dataset's database).
        """
        artifact_dir, dataset = self._open_dataset(source_type)

        json_docs_dir = artifact_dir / "jsonDocuments"
        if not json_docs_dir.exists():
            pytest.skip(f"jsonDocuments directory not found in {source_type}.")

        json_files = list(json_docs_dir.glob("**/*.json"))

        # Collect docs from each session's database, matching MATLAB's approach
        actual_docs = []
        _refs, session_ids, *_ = dataset.session_list()
        for sid in session_ids:
            sess = dataset.open_session(sid)
            actual_docs.extend(sess.database_search(Query("base.id").match("(.*)")))

        assert len(actual_docs) == len(json_files), (
            f"Number of documents across sessions ({len(actual_docs)}) does not match "
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
                    ) == expected_doc.get("document_class", {}).get(
                        "class_name"
                    ), f"Document class mismatch for id: {expected_id} in {source_type}"
                    break
            assert (
                found
            ), f"Document from {source_type} artifact not found in dataset: {expected_id}"
