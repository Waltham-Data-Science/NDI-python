"""Generate symmetry artifacts for a downloaded ingested dataset.

Python equivalent of:
    tests/+ndi/+symmetry/+makeArtifacts/+dataset/downloadIngested.m

This test downloads a pre-built dataset archive (.tgz) from a public
GitHub repository, extracts it, opens the dataset, and exports
artifacts (session summaries, document counts) to:

    <tempdir>/NDI/symmetryTest/pythonArtifacts/dataset/downloadIngested/
             testDownloadIngestedArtifacts/

The artifacts are left on disk so that the MATLAB ``readArtifacts`` suite
(and the Python ``read_artifacts`` suite) can load and verify them.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from ndi.dataset import Dataset
from ndi.query import Query
from ndi.util import sessionSummary
from tests.symmetry.conftest import PYTHON_ARTIFACTS

ARTIFACT_DIR = PYTHON_ARTIFACTS / "dataset" / "downloadIngested" / "testDownloadIngestedArtifacts"

DATASET_ID = "69a8705aa9ab25373cdc6563"
TGZ_FILENAME = f"{DATASET_ID}.tgz"
TGZ_URL = f"https://github.com/Waltham-Data-Science/file-passing/raw/refs/heads/main/{TGZ_FILENAME}"


def _find_tgz() -> Path | None:
    """Locate the pre-downloaded .tgz archive.

    The CI workflow downloads it to /tmp before tests run.
    Falls back to downloading via curl for local development.
    """
    tgz_path = Path(tempfile.gettempdir()) / TGZ_FILENAME
    if tgz_path.is_file():
        return tgz_path
    return None


def _download_tgz() -> Path:
    """Download the dataset archive via curl."""
    tgz_path = Path(tempfile.gettempdir()) / TGZ_FILENAME
    result = subprocess.run(
        ["curl", "-L", "-o", str(tgz_path), TGZ_URL],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to download dataset archive: {result.stderr}")
    return tgz_path


class TestDownloadIngested:
    """Mirror of ndi.symmetry.makeArtifacts.dataset.downloadIngested."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        """Locate or download the dataset .tgz archive."""
        tgz_path = _find_tgz()
        if tgz_path is None:
            tgz_path = _download_tgz()
        self.tgz_path = tgz_path

    def test_download_ingested_artifacts(self):
        """Extract dataset, build summaries, and export artifacts."""
        artifact_dir = ARTIFACT_DIR

        # Clear previous artifacts
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Extract the archive into the artifact directory
        shutil.unpack_archive(str(self.tgz_path), str(artifact_dir))

        # Remove macOS resource fork files (._*) that may be in the archive;
        # MATLAB does not see these, so they cause file-list mismatches.
        for dot_underscore in artifact_dir.rglob("._*"):
            dot_underscore.unlink()

        # The extracted directory is the dataset
        dataset_path = artifact_dir / DATASET_ID
        assert dataset_path.is_dir(), f"Expected extracted directory {DATASET_ID} not found."

        # Open the dataset
        dataset = Dataset(dataset_path)

        # Get session list
        ref_list, id_list, *_ = dataset.session_list()
        num_sessions = len(ref_list)

        # Build session summaries for each session
        session_summaries = []
        for sid in id_list:
            sess = dataset.open_session(sid)
            session_summaries.append(sessionSummary(sess))

        # Record document counts per session
        document_counts = []
        for sid in id_list:
            sess = dataset.open_session(sid)
            docs = sess.database_search(Query("base.id").match("(.*)"))
            document_counts.append({"sessionId": sid, "count": len(docs)})

        # Build the dataset summary
        dataset_summary = {
            "numSessions": num_sessions,
            "references": ref_list,
            "sessionIds": id_list,
            "sessionSummaries": session_summaries,
            "documentCounts": document_counts,
        }

        # Write datasetSummary.json
        summary_json = json.dumps(dataset_summary, indent=2, allow_nan=True)
        summary_path = artifact_dir / "datasetSummary.json"
        summary_path.write_text(summary_json, encoding="utf-8")

        # Verify artifacts were created
        assert artifact_dir.exists()
        assert summary_path.exists()
        assert dataset_path.is_dir()
