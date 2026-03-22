"""Tests for ndi.document module."""

import json

import pytest

from ndi import ndi_document, ndi_ido
from ndi.common import timestamp


class TestDocumentCreation:
    """Test ndi_document creation."""

    def test_create_document_with_dict(self):
        """Test creating document from a dictionary."""
        props = {
            "base": {
                "id": "test_id_123",
                "datestamp": "2024-01-01T00:00:00.000Z",
                "name": "test_doc",
                "session_id": "",
            },
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc = ndi_document(props)
        assert doc.id == "test_id_123"
        assert doc.document_properties["base"]["name"] == "test_doc"

    def test_create_document_without_id_in_dict(self):
        """Test creating document from dict without ID - ID should be empty.

        Note: ID generation only happens when creating from a schema type (string).
        When loading from a dict, the document uses whatever is provided.
        """
        props = {
            "base": {"name": "test_doc", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc = ndi_document(props)
        # ID should be empty since none was provided in the dict
        assert doc.id == ""

    def test_create_document_with_ido_generates_id(self):
        """Test that using ndi_ido directly generates a valid ID."""
        ido = ndi_ido()
        props = {
            "base": {"id": ido.id, "datestamp": timestamp(), "name": "test_doc", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc = ndi_document(props)
        # ID should match the ndi_ido we created
        assert doc.id == ido.id
        assert len(doc.id) > 0

    def test_create_document_from_another(self):
        """Test creating document from another ndi_document."""
        props = {
            "base": {
                "id": "original_id",
                "datestamp": timestamp(),
                "name": "original",
                "session_id": "",
            },
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc1 = ndi_document(props)
        doc2 = ndi_document(doc1)

        # Should be a copy with same properties
        assert doc2.id == doc1.id
        assert doc2.document_properties["base"]["name"] == "original"

        # But modifying one shouldn't affect the other
        doc2._document_properties["base"]["name"] = "modified"
        assert doc1.document_properties["base"]["name"] == "original"


class TestDocumentProperties:
    """Test ndi_document property access."""

    def test_id_property(self):
        """Test id property."""
        props = {
            "base": {"id": "my_id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc = ndi_document(props)
        assert doc.id == "my_id"

    def test_session_id_property(self):
        """Test session_id property."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": "sess_123"},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc = ndi_document(props)
        assert doc.session_id == "sess_123"

    def test_set_session_id(self):
        """Test set_session_id method."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc = ndi_document(props)
        doc = doc.set_session_id("new_session")
        assert doc.session_id == "new_session"

    def test_set_session_id_chaining(self):
        """Test that set_session_id returns self for chaining."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc = ndi_document(props)
        result = doc.set_session_id("sess")
        assert result is doc


class TestDocumentClass:
    """Test document class methods."""

    def test_doc_class(self):
        """Test doc_class method."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "ndi_element", "superclasses": []},
        }
        doc = ndi_document(props)
        assert doc.doc_class() == "ndi_element"

    def test_doc_isa_true(self):
        """Test doc_isa returns True for matching class."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "ndi_element", "superclasses": []},
        }
        doc = ndi_document(props)
        assert doc.doc_isa("ndi_element")

    def test_doc_isa_false(self):
        """Test doc_isa returns False for non-matching class."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "ndi_element", "superclasses": []},
        }
        doc = ndi_document(props)
        assert not doc.doc_isa("ndi_probe")


class TestDocumentDependencies:
    """Test dependency management."""

    def test_dependency_empty(self):
        """Test dependency returns empty for doc without dependencies."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc = ndi_document(props)
        names, deps = doc.dependency()
        assert names == []
        assert deps == []

    def test_dependency_with_deps(self):
        """Test dependency returns correct values."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "depends_on": [
                {"name": "session_id", "value": "sess_123"},
                {"name": "element_id", "value": "elem_456"},
            ],
        }
        doc = ndi_document(props)
        names, deps = doc.dependency()
        assert "session_id" in names
        assert "element_id" in names
        assert len(deps) == 2

    def test_depends_on_bare_dict_normalized_to_list(self):
        """Test that a bare dict depends_on (MATLAB-style) is normalized to a list."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "depends_on": {"name": "element_id", "value": "abc123"},
        }
        doc = ndi_document(props)
        # Should be normalized to a list
        assert isinstance(doc.document_properties["depends_on"], list)
        assert len(doc.document_properties["depends_on"]) == 1
        assert doc.dependency_value("element_id") == "abc123"

    def test_file_info_bare_dict_normalized_to_list(self):
        """Test that a bare dict file_info (MATLAB-style) is normalized to a list."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "files": {
                "file_info": {
                    "name": "data.bin",
                    "locations": {"location": "/tmp/data.bin"},
                }
            },
        }
        doc = ndi_document(props)
        fi = doc.document_properties["files"]["file_info"]
        assert isinstance(fi, list)
        assert len(fi) == 1
        assert fi[0]["name"] == "data.bin"

    def test_dependency_value(self):
        """Test dependency_value returns correct value."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "depends_on": [{"name": "session_id", "value": "sess_123"}],
        }
        doc = ndi_document(props)
        assert doc.dependency_value("session_id") == "sess_123"

    def test_dependency_value_not_found(self):
        """Test dependency_value raises error when not found."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "depends_on": [],
        }
        doc = ndi_document(props)
        with pytest.raises(KeyError):
            doc.dependency_value("nonexistent")

    def test_dependency_value_not_found_no_error(self):
        """Test dependency_value returns None when error_if_not_found=False."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "depends_on": [],
        }
        doc = ndi_document(props)
        result = doc.dependency_value("nonexistent", error_if_not_found=False)
        assert result is None

    def test_set_dependency_value(self):
        """Test set_dependency_value updates existing dependency."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "depends_on": [{"name": "session_id", "value": "old_value"}],
        }
        doc = ndi_document(props)
        doc = doc.set_dependency_value("session_id", "new_value")
        assert doc.dependency_value("session_id") == "new_value"

    def test_set_dependency_value_add_new(self):
        """Test set_dependency_value adds new dependency when error_if_not_found=False."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "depends_on": [],
        }
        doc = ndi_document(props)
        doc = doc.set_dependency_value("new_dep", "new_value", error_if_not_found=False)
        assert doc.dependency_value("new_dep") == "new_value"

    def test_dependency_value_n(self):
        """Test dependency_value_n returns numbered dependencies."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "depends_on": [
                {"name": "element_1", "value": "elem_a"},
                {"name": "element_2", "value": "elem_b"},
                {"name": "element_3", "value": "elem_c"},
            ],
        }
        doc = ndi_document(props)
        values = doc.dependency_value_n("element")
        assert values == ["elem_a", "elem_b", "elem_c"]

    def test_add_dependency_value_n(self):
        """Test add_dependency_value_n adds numbered dependency."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "depends_on": [{"name": "element_1", "value": "elem_a"}],
        }
        doc = ndi_document(props)
        doc = doc.add_dependency_value_n("element", "elem_b")
        values = doc.dependency_value_n("element")
        assert values == ["elem_a", "elem_b"]


class TestDocumentFiles:
    """Test file management."""

    def test_has_files_false(self):
        """Test has_files returns False when no files."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "files": {"file_list": [], "file_info": []},
        }
        doc = ndi_document(props)
        assert not doc.has_files()

    def test_has_files_true(self):
        """Test has_files returns True when files exist."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "files": {
                "file_list": ["data.bin"],
                "file_info": [{"name": "data.bin", "locations": []}],
            },
        }
        doc = ndi_document(props)
        assert doc.has_files()

    def test_current_file_list_empty(self):
        """Test current_file_list returns empty list."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "files": {"file_list": ["allowed.bin"], "file_info": []},
        }
        doc = ndi_document(props)
        assert doc.current_file_list() == []

    def test_add_file(self):
        """Test add_file adds file info."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "files": {"file_list": ["data.bin"], "file_info": []},
        }
        doc = ndi_document(props)
        doc = doc.add_file("data.bin", "/path/to/data.bin")
        assert "data.bin" in doc.current_file_list()

    def test_add_file_not_in_list(self):
        """Test add_file raises error for file not in file_list."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
            "files": {"file_list": ["allowed.bin"], "file_info": []},
        }
        doc = ndi_document(props)
        with pytest.raises(ValueError):
            doc.add_file("not_allowed.bin", "/path/to/file")

    def test_add_file_no_files_field(self):
        """Test add_file raises error when document has no files field."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc = ndi_document(props)
        with pytest.raises(ValueError):
            doc.add_file("data.bin", "/path/to/data.bin")


class TestDocumentEquality:
    """Test document equality."""

    def test_eq_same_id(self):
        """Test documents with same ID are equal."""
        props1 = {
            "base": {"id": "same_id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        props2 = {
            "base": {"id": "same_id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "other", "superclasses": []},
        }
        doc1 = ndi_document(props1)
        doc2 = ndi_document(props2)
        assert doc1 == doc2

    def test_eq_different_id(self):
        """Test documents with different IDs are not equal."""
        props1 = {
            "base": {"id": "id1", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        props2 = {
            "base": {"id": "id2", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc1 = ndi_document(props1)
        doc2 = ndi_document(props2)
        assert doc1 != doc2

    def test_eq_non_document(self):
        """Test document is not equal to non-document."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc = ndi_document(props)
        assert doc != "not a document"
        assert doc != 123


class TestDocumentConversion:
    """Test document conversion methods."""

    def test_to_dict(self):
        """Test to_dict returns copy of properties."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc = ndi_document(props)
        d = doc.to_dict()
        assert d == props
        # Modifying returned dict shouldn't affect document
        d["base"]["id"] = "modified"
        assert doc.id == "id"

    def test_to_json(self):
        """Test to_json returns valid JSON string."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc = ndi_document(props)
        json_str = doc.to_json()
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["base"]["id"] == "id"

    def test_setproperties(self):
        """Test setproperties updates multiple properties."""
        props = {
            "base": {"id": "id", "datestamp": "", "session_id": "", "name": "old"},
            "document_class": {"class_name": "base", "superclasses": []},
        }
        doc = ndi_document(props)
        doc = doc.setproperties(**{"base.name": "new_name", "base.session_id": "sess"})
        assert doc.document_properties["base"]["name"] == "new_name"
        assert doc.session_id == "sess"


class TestDocumentStaticMethods:
    """Test static methods."""

    def test_find_doc_by_id_found(self):
        """Test find_doc_by_id finds document."""
        docs = [
            ndi_document(
                {
                    "base": {"id": "id1", "datestamp": "", "session_id": ""},
                    "document_class": {"class_name": "base", "superclasses": []},
                }
            ),
            ndi_document(
                {
                    "base": {"id": "id2", "datestamp": "", "session_id": ""},
                    "document_class": {"class_name": "base", "superclasses": []},
                }
            ),
            ndi_document(
                {
                    "base": {"id": "id3", "datestamp": "", "session_id": ""},
                    "document_class": {"class_name": "base", "superclasses": []},
                }
            ),
        ]
        found, idx = ndi_document.find_doc_by_id(docs, "id2")
        assert found is not None
        assert found.id == "id2"
        assert idx == 1

    def test_find_doc_by_id_not_found(self):
        """Test find_doc_by_id returns None when not found."""
        docs = [
            ndi_document(
                {
                    "base": {"id": "id1", "datestamp": "", "session_id": ""},
                    "document_class": {"class_name": "base", "superclasses": []},
                }
            ),
        ]
        found, idx = ndi_document.find_doc_by_id(docs, "nonexistent")
        assert found is None
        assert idx is None

    def test_find_newest(self):
        """Test find_newest finds most recent document."""
        docs = [
            ndi_document(
                {
                    "base": {
                        "id": "id1",
                        "datestamp": "2024-01-01T00:00:00.000Z",
                        "session_id": "",
                    },
                    "document_class": {"class_name": "base", "superclasses": []},
                }
            ),
            ndi_document(
                {
                    "base": {
                        "id": "id2",
                        "datestamp": "2024-01-03T00:00:00.000Z",
                        "session_id": "",
                    },
                    "document_class": {"class_name": "base", "superclasses": []},
                }
            ),
            ndi_document(
                {
                    "base": {
                        "id": "id3",
                        "datestamp": "2024-01-02T00:00:00.000Z",
                        "session_id": "",
                    },
                    "document_class": {"class_name": "base", "superclasses": []},
                }
            ),
        ]
        newest, idx, ts = ndi_document.find_newest(docs)
        assert newest.id == "id2"  # Jan 3 is newest
        assert idx == 1

    def test_find_newest_empty_raises(self):
        """Test find_newest raises error for empty array."""
        with pytest.raises(ValueError):
            ndi_document.find_newest([])


class TestDocumentRepr:
    """Test string representation."""

    def test_repr(self):
        """Test repr shows class and ID."""
        props = {
            "base": {"id": "my_id", "datestamp": "", "session_id": ""},
            "document_class": {"class_name": "ndi_element", "superclasses": []},
        }
        doc = ndi_document(props)
        r = repr(doc)
        assert "ndi_document" in r
        assert "ndi_element" in r
        assert "my_id" in r
