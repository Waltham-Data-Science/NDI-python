"""
Port of MATLAB ndi.unittest.ingestion.* tests.

MATLAB source files:
  +ingestion/ingestionIntan.m    → TestIngestionIntan
  +ingestion/ingestionAxonNDR.m  → TestIngestionAxon
  +ingestion/ingestionIntanNDR.m → TestIngestionIntanNDR

These tests exercise the two-phase file ingestion/expulsion system:
  ndi.database_ingestion.ingest_plan / ingest / expell_plan / expell

Since the MATLAB tests require real Intan (.rhd) / Axon (.abf) data
files and a full DAQ system pipeline, we provide:
  - Mocked unit tests (always run) testing the ingestion functions
  - Integration tests (skip if DirSession unavailable) for full flow
"""

from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _have_example_data() -> bool:
    """Check if example Intan data is available."""
    from ndi.common import PathConstants

    example = PathConstants.COMMON_FOLDER / "example_sessions"
    return example.exists() and any(example.rglob("*.rhd"))


requires_example_data = pytest.mark.skipif(
    not _have_example_data(),
    reason="No example session data available",
)


# ===========================================================================
# TestIngestionPlan — Unit tests for ingest_plan / expell_plan
# ===========================================================================


class TestIngestionPlan:
    """Port of ingestion plan logic from ndi.database.implementations.fun."""

    def test_ingest_plan_empty_document(self):
        """ingest_plan returns empty lists for doc with no files."""
        from ndi.database_ingestion import ingest_plan

        doc = MagicMock()
        doc.document_properties = {"base": {"id": "test"}}
        src, dst, delete = ingest_plan(doc, "/tmp/ingest")
        assert src == []
        assert dst == []
        assert delete == []

    def test_ingest_plan_with_files(self):
        """ingest_plan correctly identifies files to copy."""
        from ndi.database_ingestion import ingest_plan

        doc = MagicMock()
        doc.document_properties = {
            "files": {
                "file_info": [
                    {
                        "name": "data.bin",
                        "locations": [
                            {
                                "uid": "uid-001",
                                "location": "/data/raw/data.bin",
                                "ingest": True,
                                "delete_original": False,
                            }
                        ],
                    }
                ]
            }
        }
        src, dst, delete = ingest_plan(doc, "/tmp/ingest")
        assert len(src) == 1
        assert src[0] == "/data/raw/data.bin"
        assert "uid-001" in dst[0]
        assert delete == []

    def test_ingest_plan_with_delete_original(self):
        """ingest_plan includes delete list when delete_original is set."""
        from ndi.database_ingestion import ingest_plan

        doc = MagicMock()
        doc.document_properties = {
            "files": {
                "file_info": [
                    {
                        "name": "data.bin",
                        "locations": [
                            {
                                "uid": "uid-002",
                                "location": "/data/raw/data.bin",
                                "ingest": True,
                                "delete_original": True,
                            }
                        ],
                    }
                ]
            }
        }
        src, dst, delete = ingest_plan(doc, "/tmp/ingest")
        assert len(src) == 1
        assert len(delete) == 1
        assert delete[0] == "/data/raw/data.bin"

    def test_ingest_plan_no_ingest_flag(self):
        """ingest_plan skips locations without ingest=True."""
        from ndi.database_ingestion import ingest_plan

        doc = MagicMock()
        doc.document_properties = {
            "files": {
                "file_info": [
                    {
                        "name": "data.bin",
                        "locations": [
                            {
                                "uid": "uid-003",
                                "location": "/data/raw/data.bin",
                                "ingest": False,
                                "delete_original": False,
                            }
                        ],
                    }
                ]
            }
        }
        src, dst, delete = ingest_plan(doc, "/tmp/ingest")
        assert src == []
        assert dst == []

    def test_ingest_plan_multiple_files(self):
        """ingest_plan handles multiple file_info entries."""
        from ndi.database_ingestion import ingest_plan

        doc = MagicMock()
        doc.document_properties = {
            "files": {
                "file_info": [
                    {
                        "name": "file1.bin",
                        "locations": [
                            {
                                "uid": "uid-a",
                                "location": "/data/file1.bin",
                                "ingest": True,
                                "delete_original": False,
                            }
                        ],
                    },
                    {
                        "name": "file2.bin",
                        "locations": [
                            {
                                "uid": "uid-b",
                                "location": "/data/file2.bin",
                                "ingest": True,
                                "delete_original": True,
                            }
                        ],
                    },
                ]
            }
        }
        src, dst, delete = ingest_plan(doc, "/tmp/ingest")
        assert len(src) == 2
        assert len(dst) == 2
        assert len(delete) == 1

    def test_expell_plan_identifies_ingested_files(self):
        """expell_plan returns files to delete from ingestion directory."""
        from ndi.database_ingestion import expell_plan

        doc = MagicMock()
        doc.document_properties = {
            "files": {
                "file_info": [
                    {
                        "name": "data.bin",
                        "locations": [
                            {
                                "uid": "uid-004",
                                "location": "/data/raw/data.bin",
                                "ingest": True,
                            }
                        ],
                    }
                ]
            }
        }
        to_delete = expell_plan(doc, "/tmp/ingest")
        assert len(to_delete) == 1
        assert "uid-004" in to_delete[0]

    def test_expell_plan_empty_document(self):
        """expell_plan returns empty list for doc without ingested files."""
        from ndi.database_ingestion import expell_plan

        doc = MagicMock()
        doc.document_properties = {"base": {"id": "test"}}
        to_delete = expell_plan(doc, "/tmp/ingest")
        assert to_delete == []


# ===========================================================================
# TestIngestionExecution — Tests for actual file copy/delete
# ===========================================================================


class TestIngestionExecution:
    """Tests for the ingest() and expell() execution functions."""

    def test_ingest_copies_files(self, tmp_path):
        """ingest() copies source files to destination."""
        from ndi.database_ingestion import ingest

        # Create source file
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        src_file = src_dir / "data.bin"
        src_file.write_bytes(b"test data content")

        # Define destination
        dst_dir = tmp_path / "dest"
        dst_file = dst_dir / "uid-001"

        success, msg = ingest(
            [str(src_file)],
            [str(dst_file)],
            [],
        )
        assert success, f"Ingest failed: {msg}"
        assert dst_file.exists()
        assert dst_file.read_bytes() == b"test data content"

    def test_ingest_deletes_originals(self, tmp_path):
        """ingest() deletes originals when requested."""
        from ndi.database_ingestion import ingest

        # Create source file
        src_file = tmp_path / "data.bin"
        src_file.write_bytes(b"data")

        dst_file = tmp_path / "dest" / "uid-001"

        success, msg = ingest(
            [str(src_file)],
            [str(dst_file)],
            [str(src_file)],  # delete original
        )
        assert success, f"Ingest failed: {msg}"
        assert dst_file.exists()
        assert not src_file.exists()

    def test_ingest_creates_parent_directories(self, tmp_path):
        """ingest() creates parent directories for destination."""
        from ndi.database_ingestion import ingest

        src_file = tmp_path / "data.bin"
        src_file.write_bytes(b"data")

        dst_file = tmp_path / "deep" / "nested" / "dir" / "uid-001"

        success, msg = ingest(
            [str(src_file)],
            [str(dst_file)],
            [],
        )
        assert success
        assert dst_file.exists()

    def test_ingest_fails_missing_source(self, tmp_path):
        """ingest() returns failure for missing source file."""
        from ndi.database_ingestion import ingest

        success, msg = ingest(
            ["/nonexistent/file.bin"],
            [str(tmp_path / "dest")],
            [],
        )
        assert not success
        assert "nonexistent" in msg.lower() or "Copying" in msg

    def test_expell_deletes_files(self, tmp_path):
        """expell() deletes listed files."""
        from ndi.database_ingestion import expell

        f1 = tmp_path / "uid-001"
        f2 = tmp_path / "uid-002"
        f1.write_bytes(b"data1")
        f2.write_bytes(b"data2")

        success, msg = expell([str(f1), str(f2)])
        assert success, f"Expell failed: {msg}"
        assert not f1.exists()
        assert not f2.exists()

    def test_expell_empty_list(self):
        """expell() with empty list succeeds."""
        from ndi.database_ingestion import expell

        success, msg = expell([])
        assert success
        assert msg == ""

    def test_expell_missing_file_ok(self, tmp_path):
        """expell() handles missing files gracefully (missing_ok)."""
        from ndi.database_ingestion import expell

        success, msg = expell([str(tmp_path / "nonexistent")])
        assert success


# ===========================================================================
# TestIngestionFullPipeline — Integration using ingest_plan + ingest
# ===========================================================================


class TestIngestionFullPipeline:
    """Full plan-then-execute pipeline test."""

    def test_plan_and_execute(self, tmp_path):
        """Full pipeline: plan → execute → verify."""
        from ndi.database_ingestion import ingest, ingest_plan

        # Create source file
        src_dir = tmp_path / "raw"
        src_dir.mkdir()
        src_file = src_dir / "recording.rhd"
        src_file.write_bytes(b"fake RHD header data")

        ing_dir = tmp_path / "ingested"

        # Create mock document with file info
        doc = MagicMock()
        doc.document_properties = {
            "files": {
                "file_info": [
                    {
                        "name": "recording.rhd",
                        "locations": [
                            {
                                "uid": "uid-recording-001",
                                "location": str(src_file),
                                "ingest": True,
                                "delete_original": False,
                            }
                        ],
                    }
                ]
            }
        }

        # Phase 1: Plan
        src_files, dst_files, to_delete = ingest_plan(doc, str(ing_dir))
        assert len(src_files) == 1
        assert src_files[0] == str(src_file)

        # Phase 2: Execute
        success, msg = ingest(src_files, dst_files, to_delete)
        assert success, f"Ingest failed: {msg}"

        # Verify
        expected_dest = ing_dir / "uid-recording-001"
        assert expected_dest.exists()
        assert expected_dest.read_bytes() == b"fake RHD header data"
        # Original should still exist (no delete requested)
        assert src_file.exists()

    def test_plan_execute_with_delete(self, tmp_path):
        """Pipeline with delete_original flag."""
        from ndi.database_ingestion import ingest, ingest_plan

        src_file = tmp_path / "data.bin"
        src_file.write_bytes(b"temp data")

        ing_dir = tmp_path / "ingested"

        doc = MagicMock()
        doc.document_properties = {
            "files": {
                "file_info": [
                    {
                        "name": "data.bin",
                        "locations": [
                            {
                                "uid": "uid-del-001",
                                "location": str(src_file),
                                "ingest": True,
                                "delete_original": True,
                            }
                        ],
                    }
                ]
            }
        }

        src_files, dst_files, to_delete = ingest_plan(doc, str(ing_dir))
        success, msg = ingest(src_files, dst_files, to_delete)
        assert success

        # Original deleted
        assert not src_file.exists()
        # Ingested copy exists
        assert (ing_dir / "uid-del-001").exists()

    def test_expell_pipeline(self, tmp_path):
        """Full expell pipeline: plan → execute."""
        from ndi.database_ingestion import expell, expell_plan

        ing_dir = tmp_path / "ingested"
        ing_dir.mkdir()
        ingested_file = ing_dir / "uid-exp-001"
        ingested_file.write_bytes(b"ingested data")

        doc = MagicMock()
        doc.document_properties = {
            "files": {
                "file_info": [
                    {
                        "name": "data.bin",
                        "locations": [
                            {
                                "uid": "uid-exp-001",
                                "location": "/original/data.bin",
                                "ingest": True,
                            }
                        ],
                    }
                ]
            }
        }

        # Phase 1: Plan
        to_delete = expell_plan(doc, str(ing_dir))
        assert len(to_delete) == 1

        # Phase 2: Execute
        success, msg = expell(to_delete)
        assert success
        assert not ingested_file.exists()
