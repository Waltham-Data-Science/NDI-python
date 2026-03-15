"""Read and verify symmetry artifacts for a basic NDI session.

Python equivalent of:
    tests/+ndi/+symmetry/+readArtifacts/+session/buildSession.m

This test loads artifacts produced by *either* the MATLAB or the Python
``makeArtifacts`` suite and verifies that the Python NDI stack can:

1. Open the copied session database.
2. Load every document whose JSON was exported to ``jsonDocuments/``.
3. Reconstruct probes that match ``probes.json``.

The test is parameterized over ``source_type`` so that a single test class
covers both ``matlabArtifacts`` and ``pythonArtifacts``.
"""

import json

import pytest

from ndi.query import Query
from ndi.session.dir import DirSession
from tests.symmetry.conftest import SOURCE_TYPES, SYMMETRY_BASE


@pytest.fixture(params=SOURCE_TYPES)
def source_type(request):
    """Parameterize over matlabArtifacts / pythonArtifacts."""
    return request.param


class TestBuildSession:
    """Mirror of ndi.symmetry.readArtifacts.session.buildSession."""

    def _artifact_dir(self, source_type: str):
        return (
            SYMMETRY_BASE / source_type / "session" / "buildSession" / "testBuildSessionArtifacts"
        )

    def _open_session(self, source_type):
        artifact_dir = self._artifact_dir(source_type)
        if not artifact_dir.exists():
            pytest.skip(
                f"Artifact directory from {source_type} does not exist. "
                f"Run the corresponding makeArtifacts suite first."
            )
        return artifact_dir, DirSession("exp1", artifact_dir)

    # -- tests (documents first, then probes) --------------------------------

    def test_build_session_documents(self, source_type):
        """Verify that every exported JSON document can be loaded from the session DB."""
        artifact_dir, session = self._open_session(source_type)

        json_docs_dir = artifact_dir / "jsonDocuments"
        if not json_docs_dir.exists():
            pytest.skip(f"jsonDocuments directory not found in {source_type}.")

        json_files = list(json_docs_dir.glob("*.json"))

        actual_docs = session.database_search(Query("base.id").match("(.*)"))

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
                        f"Document class mismatch for id: {expected_id} " f"in {source_type}"
                    )
                    break
            assert found, (
                f"Document from {source_type} artifact not found in session: " f"{expected_id}"
            )

    def test_build_session_probes(self, source_type):
        """Verify that probes reconstructed from the session match probes.json."""
        artifact_dir, session = self._open_session(source_type)

        probes_json_path = artifact_dir / "probes.json"
        if not probes_json_path.exists():
            pytest.skip(f"probes.json not found in {source_type} artifact directory.")

        expected_probes = json.loads(probes_json_path.read_text(encoding="utf-8"))
        actual_probes = session.getprobes()

        assert len(actual_probes) == len(expected_probes), (
            f"Number of actual probes ({len(actual_probes)}) does not match "
            f"{source_type} generated artifacts ({len(expected_probes)})."
        )

        for expected in expected_probes:
            found = False
            for actual in actual_probes:
                if (
                    actual.name == expected["name"]
                    and actual.reference == expected["reference"]
                    and actual.type == expected["type"]
                ):
                    found = True
                    assert getattr(actual, "subject_id", "") == expected.get(
                        "subject_id", ""
                    ), (
                        f"Subject ID mismatch for probe {expected['name']} " f"in {source_type}"
                    )
                    break
            assert found, (
                f"Probe from {source_type} artifact not found in session: "
                f"{expected['name']}"
            )
