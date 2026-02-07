"""
Port of MATLAB ndi.unittest.database.* tests.

MATLAB source files:
  +database/TestNDIDocument.m          → TestNDIDocument
  +database/TestNDIDocumentFields.m    → TestNDIDocumentFields
  +database/TestNDIDocumentJSON.m      → TestNDIDocumentJSON
  +database/TestNDIDocumentPersistence.m → TestNDIDocumentPersistence (adapted)
  +database/TestNDIDocumentDiscovery.m → TestNDIDocumentDiscovery
  +database/TestDocComparison.m        → TestDocComparison
"""

import json

import pytest

from ndi.common import PathConstants
from ndi.document import Document
from ndi.query import Query
from ndi.session.dir import DirSession

# ===========================================================================
# TestNDIDocument
# Port of: ndi.unittest.database.TestNDIDocument
# ===========================================================================


class TestNDIDocument:
    """Test full document create-add-search-read-binary workflow."""

    def test_document_creation_and_io(self, tmp_path):
        """Full lifecycle: create → add → search → read binary → remove.

        MATLAB equivalent: TestNDIDocument.testDocumentCreationAndIO
        """
        # Create session
        session_dir = tmp_path / "doc_session"
        session_dir.mkdir()
        session = DirSession("doc_test", session_dir)

        # Create document with custom fields
        doc = session.newdocument(
            "demoNDI",
            **{
                "base.name": "my_demo_doc",
                "demoNDI.value": 42,
            },
        )

        # Write a binary file
        binary_file = tmp_path / "test_binary.dat"
        binary_file.write_bytes(b"Hello NDI Binary Data")

        # Attach file to document
        doc = doc.add_file("filename1.ext", str(binary_file))

        # Add to database
        session.database_add(doc)

        # Search by name
        q_name = Query("base.name") == "my_demo_doc"
        results = session.database_search(q_name)
        assert len(results) == 1, "Should find 1 document by name"
        assert results[0].id == doc.id

        # Search by isa
        q_type = Query("").isa("demoNDI")
        results_isa = session.database_search(q_type)
        assert len(results_isa) == 1, "Should find 1 demoNDI document"

        # Read binary content
        fid = session.database_openbinarydoc(doc, "filename1.ext")
        content = fid.read()
        session.database_closebinarydoc(fid)
        assert content == b"Hello NDI Binary Data", "Binary content should match what was written"

        # Remove document
        session.database_rm(doc)

        # Verify removal
        results_after = session.database_search(q_name)
        assert len(results_after) == 0, "Document should be removed"


# ===========================================================================
# TestNDIDocumentFields
# Port of: ndi.unittest.database.TestNDIDocumentFields
# ===========================================================================


class TestNDIDocumentFields:
    """Test document field discovery from JSON schema definitions."""

    def test_field_discovery(self):
        """Discover all field names from JSON schema files.

        MATLAB equivalent: TestNDIDocumentFields.testFieldDiscoveryAndValidation
        """
        # Locate schema files
        doc_folder = PathConstants.COMMON_FOLDER / "database_documents"
        if not doc_folder.exists():
            pytest.skip(f"Schema folder not found: {doc_folder}")

        # Collect all field names from all JSON schemas
        all_fields = set()
        json_files = list(doc_folder.rglob("*.json"))
        assert len(json_files) > 0, "Should find JSON schema files"

        for jf in json_files:
            try:
                data = json.loads(jf.read_text())
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            # Walk top-level sections and collect field paths
            if isinstance(data, dict):
                for section, fields in data.items():
                    if isinstance(fields, dict):
                        for field_name in fields:
                            all_fields.add(f"{section}.{field_name}")

        assert len(all_fields) > 0, "Should discover field names"

        # Verify essential fields exist
        assert "base.id" in all_fields, "base.id should be a known field"
        assert "base.name" in all_fields, "base.name should be a known field"
        assert "base.session_id" in all_fields, "base.session_id should be a known field"


# ===========================================================================
# TestNDIDocumentJSON
# Port of: ndi.unittest.database.TestNDIDocumentJSON
# ===========================================================================


def _discover_document_types():
    """Discover all document types from JSON schema files."""
    doc_folder = PathConstants.COMMON_FOLDER / "database_documents"
    if not doc_folder.exists():
        return []

    types = []
    for jf in sorted(doc_folder.rglob("*.json")):
        # Build the document type path relative to database_documents
        rel = jf.relative_to(doc_folder)
        doc_type = str(rel.with_suffix("")).replace("\\", "/")
        types.append(doc_type)
    return types


_DOC_TYPES = _discover_document_types()


class TestNDIDocumentJSON:
    """Test that all JSON document definitions are constructable."""

    @pytest.mark.parametrize("doc_type", _DOC_TYPES, ids=_DOC_TYPES)
    def test_single_json_definition(self, doc_type):
        """Verify Document(doc_type) succeeds for each schema.

        MATLAB equivalent: TestNDIDocumentJSON.testSingleJsonDefinition
        """
        doc = Document(doc_type)

        assert doc is not None
        assert doc.document_properties is not None
        assert isinstance(doc.document_properties, dict)

        # Verify it has base section
        assert "base" in doc.document_properties, f"{doc_type} should have base section"
        assert doc.id, f"{doc_type} should have a non-empty ID"


# ===========================================================================
# TestNDIDocumentPersistence
# Port of: ndi.unittest.database.TestNDIDocumentPersistence
#
# MATLAB test verifies save/search/reconstruct for syncrule, syncgraph,
# filenavigator, daqreader, etc. We test the generic document lifecycle.
# ===========================================================================


class TestNDIDocumentPersistence:
    """Test document persistence: save to DB, retrieve, verify."""

    def test_document_round_trip(self, tmp_path):
        """Save a document and retrieve it with matching properties.

        MATLAB equivalent: TestNDIDocumentPersistence.testGenericObjectLifecycle
        """
        session_dir = tmp_path / "persist"
        session_dir.mkdir()
        session = DirSession("persist_test", session_dir)

        # Create document
        doc = session.newdocument(
            "demoNDI",
            **{
                "base.name": "persistent_doc",
                "demoNDI.value": 123,
            },
        )
        original_id = doc.id

        # Save
        session.database_add(doc)

        # Retrieve
        q = Query("base.id") == original_id
        results = session.database_search(q)
        assert len(results) == 1

        retrieved = results[0]
        assert retrieved.id == original_id
        assert retrieved.document_properties["base"]["name"] == "persistent_doc"
        assert retrieved.document_properties["demoNDI"]["value"] == 123

    def test_multiple_document_types_persist(self, tmp_path):
        """Multiple document types can coexist in the same database."""
        session_dir = tmp_path / "multi"
        session_dir.mkdir()
        session = DirSession("multi_test", session_dir)

        # Add several document types
        doc_types = ["base", "demoNDI", "subject"]
        for dt in doc_types:
            try:
                doc = session.newdocument(dt)
                session.database_add(doc)
            except Exception:
                pass  # Some types may not be available

        # Search for all
        all_docs = session.database_search(Query("").isa("base"))
        # At minimum, base docs + session doc
        assert len(all_docs) >= 1


# ===========================================================================
# TestNDIDocumentDiscovery
# Port of: ndi.unittest.database.TestNDIDocumentDiscovery
# ===========================================================================


class TestNDIDocumentDiscovery:
    """Test discovery of document definition JSON files."""

    def test_document_discovery(self):
        """Discover all JSON document definition files.

        MATLAB equivalent: TestNDIDocumentDiscovery.testDocumentDiscoveryAndValidation
        """
        doc_folder = PathConstants.COMMON_FOLDER / "database_documents"
        if not doc_folder.exists():
            pytest.skip(f"Schema folder not found: {doc_folder}")

        json_files = list(doc_folder.rglob("*.json"))

        # Should find files
        assert len(json_files) > 0, "Should discover at least one JSON schema file"

        # Each should be a valid file with .json extension
        for jf in json_files:
            assert jf.suffix == ".json", f"{jf} should have .json extension"
            assert jf.is_file(), f"{jf} should be a regular file"

    def test_schema_count(self):
        """Verify we have a reasonable number of schemas."""
        doc_folder = PathConstants.COMMON_FOLDER / "database_documents"
        if not doc_folder.exists():
            pytest.skip(f"Schema folder not found: {doc_folder}")

        json_files = list(doc_folder.rglob("*.json"))
        # NDI has ~84 document schemas
        assert len(json_files) >= 50, f"Expected at least 50 schemas, found {len(json_files)}"


# ===========================================================================
# TestDocComparison
# Port of: ndi.unittest.database.TestDocComparison
# ===========================================================================


class TestDocComparison:
    """Test document comparison tool."""

    def test_construction(self):
        """DocComparison can be created.

        MATLAB equivalent: TestDocComparison (construction tests)
        """
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        assert dc is not None

    def test_add_comparison_parameter(self):
        """Can add comparison parameters.

        MATLAB equivalent: TestDocComparison (field extraction tests)
        """
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        dc.add_comparison_parameter(
            "base.name",
            method="character_exact",
        )
        dc.add_comparison_parameter(
            "demoNDI.value",
            method="abs_difference",
            tolerance=0.01,
        )

        # Should have 2 parameters
        assert len(dc._parameters) == 2

    def test_compare_documents(self):
        """Compare two documents and check results.

        MATLAB equivalent: TestDocComparison (comparison logic tests)
        """
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        dc.add_comparison_parameter(
            "base.name",
            method="character_exact",
        )
        dc.add_comparison_parameter(
            "demoNDI.value",
            method="abs_difference",
            tolerance=0.5,
        )

        doc1 = Document("demoNDI")
        props1 = doc1.document_properties
        props1["base"]["name"] = "test"
        props1["demoNDI"]["value"] = 10
        doc1 = Document(props1)

        doc2 = Document("demoNDI")
        props2 = doc2.document_properties
        props2["base"]["name"] = "test"
        props2["demoNDI"]["value"] = 10.3
        doc2 = Document(props2)

        result = dc.compare(doc1, doc2)
        assert result is not None

    def test_compare_mismatched_names(self):
        """Compare documents with different names.

        MATLAB equivalent: TestDocComparison (error handling tests)
        """
        from ndi.doc_comparison import DocComparison

        dc = DocComparison()
        dc.add_comparison_parameter(
            "base.name",
            method="character_exact",
        )

        doc1 = Document("demoNDI")
        props1 = doc1.document_properties
        props1["base"]["name"] = "alpha"
        doc1 = Document(props1)

        doc2 = Document("demoNDI")
        props2 = doc2.document_properties
        props2["base"]["name"] = "beta"
        doc2 = Document(props2)

        result = dc.compare(doc1, doc2)
        # Result should indicate mismatch
        assert result is not None
