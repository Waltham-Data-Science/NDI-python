"""
Port of MATLAB ndi.unittest.fun.* tests.

MATLAB source files:
  +doc/TestAllTypes.m          -> TestAllTypes
  +doc/TestFindFuid.m          -> TestFindFuid
  +doc/testDiff.m              -> TestDocDiff
  +session/diffTest.m          -> TestSessionDiff
  +dataset/diffTest.m          -> TestDatasetDiff
  +table/TestVStack.m          -> TestVStack

Python modules under test:
  ndi.fun.doc   — all_types, find_fuid, diff
  ndi.fun.session — diff
  ndi.fun.dataset — diff
  ndi.fun.table — vstack
"""

import copy

import numpy as np
import pandas as pd

from ndi.dataset import Dataset
from ndi.document import Document
from ndi.fun.dataset import diff as dataset_diff
from ndi.fun.doc import all_types, find_fuid
from ndi.fun.doc import diff as doc_diff
from ndi.fun.session import diff as session_diff
from ndi.fun.table import vstack
from ndi.query import Query
from ndi.session.dir import DirSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_demo_doc(name: str = "test", value: int = 42, session_id: str = "") -> Document:
    """Create a demoNDI document with given name and value."""
    doc = Document("demoNDI")
    props = doc.document_properties
    props["base"]["name"] = name
    props["demoNDI"]["value"] = value
    if session_id:
        props["base"]["session_id"] = session_id
    return Document(props)


def _make_session_with_docs(tmp_path, ref, doc_specs):
    """Create a DirSession and add documents from a list of (name, value) tuples.

    Returns (session, list_of_added_docs).
    """
    session_dir = tmp_path / ref
    session_dir.mkdir(parents=True, exist_ok=True)
    session = DirSession(ref, session_dir)

    added = []
    for name, value in doc_specs:
        doc = _make_demo_doc(name, value, session.id())
        session.database_add(doc)
        # Re-fetch from DB so we have the stored version
        results = session.database_search(Query("base.id") == doc.document_properties["base"]["id"])
        added.append(results[0] if results else doc)

    return session, added


# ===========================================================================
# TestAllTypes
# Port of: ndi.unittest.fun.+doc.TestAllTypes
# ===========================================================================


class TestAllTypes:
    """Port of ndi.unittest.fun.doc.TestAllTypes."""

    def test_all_types_returns_nonempty_list(self):
        """all_types() returns a non-empty list.

        MATLAB equivalent: TestAllTypes.testNonEmptyList
        """
        types = all_types()
        assert isinstance(types, list)
        assert len(types) > 0

    def test_all_types_contains_strings(self):
        """all_types() returns list of strings.

        MATLAB equivalent: TestAllTypes.testContainsStrings
        """
        types = all_types()
        for t in types:
            assert isinstance(t, str)
            assert len(t) > 0

    def test_all_types_contains_known_types(self):
        """all_types() should include well-known document types.

        MATLAB equivalent: TestAllTypes.testContainsKnownTypes
        """
        types = all_types()
        # 'base' and 'demoNDI' are always expected to exist
        assert "base" in types, "base should be in all_types()"
        assert "demoNDI" in types, "demoNDI should be in all_types()"

    def test_all_types_sorted(self):
        """all_types() returns a sorted list.

        MATLAB equivalent: TestAllTypes.testSorted
        """
        types = all_types()
        assert types == sorted(types)


# ===========================================================================
# TestFindFuid
# Port of: ndi.unittest.fun.+doc.TestFindFuid
# ===========================================================================


class TestFindFuid:
    """Port of ndi.unittest.fun.doc.TestFindFuid."""

    def test_find_known_fuid(self, tmp_path):
        """find_fuid locates a document by its file UID.

        MATLAB equivalent: TestFindFuid.testFindKnownFuid
        """
        session_dir = tmp_path / "fuid_sess"
        session_dir.mkdir()
        session = DirSession("fuid_test", session_dir)

        # Create a document with a file attachment
        filepath = session_dir / "testfile.dat"
        filepath.write_text("test content")

        doc = _make_demo_doc("fuid_doc", 1, session.id())
        doc = doc.add_file("filename1.ext", str(filepath))

        # Extract the generated file UID before adding to database
        fuid = doc.document_properties["files"]["file_info"][0]["locations"][0]["uid"]
        assert fuid, "File UID should be non-empty"

        session.database_add(doc)

        # Now search for it
        found_doc, found_name = find_fuid(session, fuid)

        assert found_doc is not None, "Should find the document by FUID"
        assert found_name == "filename1.ext", f"File name should be filename1.ext, got {found_name}"

    def test_find_fuid_not_found(self, tmp_path):
        """find_fuid returns (None, '') for nonexistent FUID.

        MATLAB equivalent: TestFindFuid.testFuidNotFound
        """
        session_dir = tmp_path / "fuid_sess2"
        session_dir.mkdir()
        session = DirSession("fuid_test2", session_dir)

        # Add a document (so the database is not empty)
        doc = _make_demo_doc("some_doc", 99, session.id())
        session.database_add(doc)

        found_doc, found_name = find_fuid(session, "nonexistent_uid_12345")

        assert found_doc is None
        assert found_name == ""

    def test_find_fuid_in_populated_session(self, tmp_path):
        """find_fuid searches among multiple documents correctly.

        MATLAB equivalent: TestFindFuid.testFindInSession
        """
        session_dir = tmp_path / "fuid_sess3"
        session_dir.mkdir()
        session = DirSession("fuid_test3", session_dir)

        # Create multiple docs with files
        target_fuid = None
        for i in range(1, 4):
            filepath = session_dir / f"file_{i}.dat"
            filepath.write_text(f"content_{i}")

            doc = _make_demo_doc(f"doc_{i}", i, session.id())
            doc = doc.add_file("filename1.ext", str(filepath))

            if i == 2:
                # Remember the FUID of the second doc
                target_fuid = doc.document_properties["files"]["file_info"][0]["locations"][0][
                    "uid"
                ]

            session.database_add(doc)

        assert target_fuid is not None

        found_doc, found_name = find_fuid(session, target_fuid)

        assert found_doc is not None
        assert found_name == "filename1.ext"
        assert found_doc.document_properties["base"]["name"] == "doc_2"


# ===========================================================================
# TestDocDiff
# Port of: ndi.unittest.fun.+doc.testDiff
# ===========================================================================


class TestDocDiff:
    """Port of ndi.unittest.fun.doc.testDiff."""

    def test_identical_docs(self):
        """Two copies of the same document should be equal.

        MATLAB equivalent: testDiff.testIdenticalDocs
        """
        doc1 = _make_demo_doc("same_doc", 42)
        # Create a copy with same properties (same id, same everything)
        doc2 = Document(copy.deepcopy(doc1.document_properties))

        result = doc_diff(doc1, doc2)

        assert result["equal"] is True
        assert len(result["details"]) == 0

    def test_property_mismatch(self):
        """Two documents with different property values should differ.

        MATLAB equivalent: testDiff.testPropertyMismatch
        """
        doc1 = _make_demo_doc("doc_a", 10)
        doc2 = Document(copy.deepcopy(doc1.document_properties))
        doc2.document_properties["demoNDI"]["value"] = 99

        result = doc_diff(doc1, doc2)

        assert result["equal"] is False
        assert len(result["details"]) > 0
        # Should mention the differing field
        details_text = " ".join(result["details"])
        assert "demoNDI" in details_text or "value" in details_text

    def test_ignore_fields(self):
        """Excluding fields from comparison makes otherwise different docs equal.

        MATLAB equivalent: testDiff.testIgnoreFields
        """
        doc1 = _make_demo_doc("doc_a", 10)
        doc2 = Document(copy.deepcopy(doc1.document_properties))
        doc2.document_properties["demoNDI"]["value"] = 99

        result = doc_diff(doc1, doc2, exclude_fields=["demoNDI.value"])

        assert result["equal"] is True
        assert len(result["details"]) == 0

    def test_different_ids(self):
        """Two documents with different base.id should differ.

        MATLAB equivalent: testDiff.testDifferentIds
        """
        doc1 = _make_demo_doc("doc_a", 10)
        doc2 = _make_demo_doc("doc_a", 10)
        # doc1 and doc2 have different auto-generated IDs

        result = doc_diff(doc1, doc2)

        assert result["equal"] is False
        details_text = " ".join(result["details"])
        assert "base" in details_text

    def test_different_ids_excluded(self):
        """Excluding base.id makes two otherwise-identical docs equal.

        MATLAB equivalent: testDiff.testDifferentIds (with exclusion)
        """
        doc1 = _make_demo_doc("doc_a", 10)
        doc2 = _make_demo_doc("doc_a", 10)

        result = doc_diff(
            doc1,
            doc2,
            exclude_fields=["base.id", "base.datestamp"],
        )

        assert result["equal"] is True

    def test_dependencies_order_independence(self):
        """Dependencies comparison is order-independent.

        MATLAB equivalent: testDiff.testDependenciesOrderIndependence
        """
        doc1 = _make_demo_doc("doc_dep", 1)
        doc2 = Document(copy.deepcopy(doc1.document_properties))

        # Add depends_on in different orders
        dep_a = {"name": "dep_a", "value": "id_aaa"}
        dep_b = {"name": "dep_b", "value": "id_bbb"}

        doc1.document_properties.setdefault("depends_on", [dep_a, dep_b])
        doc2.document_properties.setdefault("depends_on", [dep_b, dep_a])

        # The diff function checks lists ending with 'depends_on' in an
        # order-independent way
        result = doc_diff(doc1, doc2)

        assert result["equal"] is True

    def test_file_lists_order_independence(self):
        """File info comparison is order-independent.

        MATLAB equivalent: testDiff.testFileListsOrderIndependence
        """
        doc1 = _make_demo_doc("doc_files", 1)
        doc2 = Document(copy.deepcopy(doc1.document_properties))

        fi_a = {"name": "file_a.dat", "locations": []}
        fi_b = {"name": "file_b.dat", "locations": []}

        # Set file_info in different orders
        doc1.document_properties.setdefault("files", {})["file_info"] = [fi_a, fi_b]
        doc2.document_properties.setdefault("files", {})["file_info"] = [fi_b, fi_a]

        result = doc_diff(doc1, doc2, compare_files=True)

        assert result["equal"] is True


# ===========================================================================
# TestSessionDiff
# Port of: ndi.unittest.fun.+session.diffTest
# ===========================================================================


class TestSessionDiff:
    """Port of ndi.unittest.fun.session.diffTest."""

    def test_identical_sessions(self, tmp_path):
        """Two sessions with the same documents should be equal.

        MATLAB equivalent: diffTest.testIdenticalSessions

        We create two sessions from the same session path (reopened).
        """
        session_dir = tmp_path / "identical_sess"
        session_dir.mkdir()
        session = DirSession("identical", session_dir)

        for i in range(1, 4):
            doc = _make_demo_doc(f"doc_{i}", i, session.id())
            session.database_add(doc)

        # Reopen same session (same path -> same data)
        session2 = DirSession("identical", session_dir)

        result = session_diff(session, session2)

        assert result["equal"] is True
        assert len(result["only_in_s1"]) == 0
        assert len(result["only_in_s2"]) == 0
        # 3 demo docs + 1 auto-created session document
        assert result["common_count"] == 4
        assert len(result["mismatches"]) == 0

    def test_docs_only_in_s1(self, tmp_path):
        """Session 1 has extra docs that Session 2 does not.

        MATLAB equivalent: diffTest.testDocsInAOnly
        """
        s1_dir = tmp_path / "sess_a"
        s1_dir.mkdir()
        session1 = DirSession("sess_a", s1_dir)

        s2_dir = tmp_path / "sess_b"
        s2_dir.mkdir()
        session2 = DirSession("sess_b", s2_dir)

        # Add 3 docs to session1, 0 to session2
        for i in range(1, 4):
            doc = _make_demo_doc(f"doc_{i}", i, session1.id())
            session1.database_add(doc)

        result = session_diff(session1, session2)

        assert result["equal"] is False
        # 3 demo docs + 1 auto-created session doc in session1
        assert len(result["only_in_s1"]) == 4
        # session2 has its own auto-created session doc
        assert len(result["only_in_s2"]) == 1
        assert result["common_count"] == 0

    def test_docs_only_in_s2(self, tmp_path):
        """Session 2 has extra docs that Session 1 does not.

        MATLAB equivalent: diffTest.testDocsInBOnly
        """
        s1_dir = tmp_path / "sess_a"
        s1_dir.mkdir()
        session1 = DirSession("sess_a", s1_dir)

        s2_dir = tmp_path / "sess_b"
        s2_dir.mkdir()
        session2 = DirSession("sess_b", s2_dir)

        # Add 2 docs to session2, 0 to session1
        for i in range(1, 3):
            doc = _make_demo_doc(f"doc_{i}", i, session2.id())
            session2.database_add(doc)

        result = session_diff(session1, session2)

        assert result["equal"] is False
        # session1 has its own auto-created session doc
        assert len(result["only_in_s1"]) == 1
        # 2 demo docs + 1 auto-created session doc in session2
        assert len(result["only_in_s2"]) == 3
        assert result["common_count"] == 0

    def test_mismatched_docs(self, tmp_path):
        """Sessions share the same doc IDs but with different property values.

        MATLAB equivalent: diffTest.testMismatchedDocs
        """
        s1_dir = tmp_path / "sess_a"
        s1_dir.mkdir()
        session1 = DirSession("sess_a", s1_dir)

        s2_dir = tmp_path / "sess_b"
        s2_dir.mkdir()
        session2 = DirSession("sess_b", s2_dir)

        # Create a document with a known ID
        doc = _make_demo_doc("shared_doc", 10, session1.id())
        doc_id = doc.document_properties["base"]["id"]
        session1.database_add(doc)

        # Create a copy with same ID but different value
        doc2_props = copy.deepcopy(doc.document_properties)
        doc2_props["demoNDI"]["value"] = 99
        doc2_props["base"]["session_id"] = session2.id()
        doc2 = Document(doc2_props)
        session2.database_add(doc2)

        result = session_diff(session1, session2)

        assert result["equal"] is False
        assert result["common_count"] == 1
        assert len(result["mismatches"]) == 1
        assert result["mismatches"][0]["doc_id"] == doc_id


# ===========================================================================
# TestDatasetDiff
# Port of: ndi.unittest.fun.+dataset.diffTest
# ===========================================================================


class TestDatasetDiff:
    """Port of ndi.unittest.fun.dataset.diffTest."""

    def test_identical_datasets(self, tmp_path):
        """Two datasets from the same path should be equal.

        MATLAB equivalent: diffTest.testIdenticalDatasets
        """
        # Create source session
        sess_dir = tmp_path / "src_sess"
        sess_dir.mkdir()
        session = DirSession("src", sess_dir)
        for i in range(1, 3):
            doc = _make_demo_doc(f"doc_{i}", i, session.id())
            session.database_add(doc)

        # Create dataset and ingest
        ds_dir = tmp_path / "ds1"
        ds_dir.mkdir()
        dataset1 = Dataset(ds_dir, "ds1")
        dataset1.add_ingested_session(session)

        # Reopen the same dataset
        dataset2 = Dataset(ds_dir, "ds1")

        result = dataset_diff(dataset1, dataset2)

        assert result["equal"] is True
        assert result["session_diff"]["equal"] is True

    def test_docs_only_in_dataset1(self, tmp_path):
        """Dataset 1 has extra docs that Dataset 2 does not.

        MATLAB equivalent: diffTest.testDocsInAOnly
        """
        # Dataset 1 with docs
        sess1_dir = tmp_path / "sess1"
        sess1_dir.mkdir()
        session1 = DirSession("sess1", sess1_dir)
        for i in range(1, 4):
            doc = _make_demo_doc(f"doc_{i}", i, session1.id())
            session1.database_add(doc)

        ds1_dir = tmp_path / "ds1"
        ds1_dir.mkdir()
        dataset1 = Dataset(ds1_dir, "ds1")
        dataset1.add_ingested_session(session1)

        # Dataset 2 empty
        ds2_dir = tmp_path / "ds2"
        ds2_dir.mkdir()
        dataset2 = Dataset(ds2_dir, "ds2")

        result = dataset_diff(dataset1, dataset2)

        assert result["equal"] is False
        sd = result["session_diff"]
        # Dataset 1 has documents that dataset 2 does not
        assert len(sd["only_in_s1"]) > 0 or len(sd["mismatches"]) > 0

    def test_docs_only_in_dataset2(self, tmp_path):
        """Dataset 2 has extra docs that Dataset 1 does not.

        MATLAB equivalent: diffTest.testDocsInBOnly
        """
        # Dataset 1 empty
        ds1_dir = tmp_path / "ds1"
        ds1_dir.mkdir()
        dataset1 = Dataset(ds1_dir, "ds1")

        # Dataset 2 with docs
        sess2_dir = tmp_path / "sess2"
        sess2_dir.mkdir()
        session2 = DirSession("sess2", sess2_dir)
        for i in range(1, 4):
            doc = _make_demo_doc(f"doc_{i}", i, session2.id())
            session2.database_add(doc)

        ds2_dir = tmp_path / "ds2"
        ds2_dir.mkdir()
        dataset2 = Dataset(ds2_dir, "ds2")
        dataset2.add_ingested_session(session2)

        result = dataset_diff(dataset1, dataset2)

        assert result["equal"] is False
        sd = result["session_diff"]
        assert len(sd["only_in_s2"]) > 0 or len(sd["mismatches"]) > 0

    def test_mismatched_datasets(self, tmp_path):
        """Datasets with same doc IDs but different properties.

        MATLAB equivalent: diffTest.testMismatchedDocs
        """
        # Create a document
        doc = _make_demo_doc("shared", 10)
        doc.document_properties["base"]["id"]

        # Dataset 1
        sess1_dir = tmp_path / "sess1"
        sess1_dir.mkdir()
        session1 = DirSession("sess1", sess1_dir)
        doc1_props = copy.deepcopy(doc.document_properties)
        doc1_props["base"]["session_id"] = session1.id()
        session1.database_add(Document(doc1_props))

        ds1_dir = tmp_path / "ds1"
        ds1_dir.mkdir()
        dataset1 = Dataset(ds1_dir, "ds1")
        dataset1.add_ingested_session(session1)

        # Dataset 2 — same doc ID but different value
        sess2_dir = tmp_path / "sess2"
        sess2_dir.mkdir()
        session2 = DirSession("sess2", sess2_dir)
        doc2_props = copy.deepcopy(doc.document_properties)
        doc2_props["demoNDI"]["value"] = 99
        doc2_props["base"]["session_id"] = session2.id()
        session2.database_add(Document(doc2_props))

        ds2_dir = tmp_path / "ds2"
        ds2_dir.mkdir()
        dataset2 = Dataset(ds2_dir, "ds2")
        dataset2.add_ingested_session(session2)

        result = dataset_diff(dataset1, dataset2)

        assert result["equal"] is False


# ===========================================================================
# TestVStack
# Port of: ndi.unittest.fun.+table.TestVStack
# ===========================================================================


class TestVStack:
    """Port of ndi.unittest.fun.table.TestVStack.

    MATLAB uses table vertcat; Python uses pandas DataFrame + vstack.
    """

    def test_basic_stacking(self):
        """Two DataFrames with the same columns stack vertically.

        MATLAB equivalent: TestVStack.testBasicStacking
        """
        df1 = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        df2 = pd.DataFrame({"a": [5, 6], "b": [7, 8]})

        result = vstack([df1, df2])

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 4
        assert list(result.columns) == ["a", "b"]
        assert list(result["a"]) == [1, 2, 5, 6]
        assert list(result["b"]) == [3, 4, 7, 8]

    def test_no_common_columns(self):
        """Two DataFrames with completely different columns.

        MATLAB equivalent: TestVStack.testNoCommonColumns
        The result should have the union of columns with NaN fill.
        """
        df1 = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        df2 = pd.DataFrame({"c": [5, 6], "d": [7, 8]})

        result = vstack([df1, df2])

        assert len(result) == 4
        assert set(result.columns) == {"a", "b", "c", "d"}

        # First two rows should have NaN in c, d
        assert pd.isna(result.iloc[0]["c"])
        assert pd.isna(result.iloc[0]["d"])

        # Last two rows should have NaN in a, b
        assert pd.isna(result.iloc[2]["a"])
        assert pd.isna(result.iloc[2]["b"])

    def test_all_common_columns(self):
        """DataFrames with identical column sets.

        MATLAB equivalent: TestVStack.testAllCommonColumns
        """
        df1 = pd.DataFrame({"x": [1.0], "y": [2.0], "z": [3.0]})
        df2 = pd.DataFrame({"x": [4.0], "y": [5.0], "z": [6.0]})
        df3 = pd.DataFrame({"x": [7.0], "y": [8.0], "z": [9.0]})

        result = vstack([df1, df2, df3])

        assert len(result) == 3
        assert list(result.columns) == ["x", "y", "z"]
        np.testing.assert_array_equal(result["x"].values, [1.0, 4.0, 7.0])
        np.testing.assert_array_equal(result["y"].values, [2.0, 5.0, 8.0])
        np.testing.assert_array_equal(result["z"].values, [3.0, 6.0, 9.0])

    def test_single_table(self):
        """Stacking a single DataFrame returns an identical DataFrame.

        MATLAB equivalent: TestVStack.testSingleTable
        """
        df = pd.DataFrame({"col1": [10, 20, 30], "col2": ["a", "b", "c"]})

        result = vstack([df])

        assert len(result) == 3
        assert list(result.columns) == ["col1", "col2"]
        assert list(result["col1"]) == [10, 20, 30]
        assert list(result["col2"]) == ["a", "b", "c"]

    def test_empty_tables(self):
        """Stacking empty DataFrames returns an empty DataFrame.

        MATLAB equivalent: TestVStack.testEmptyTables
        """
        result = vstack([])

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_mixed_column_overlap(self):
        """DataFrames with partial column overlap.

        MATLAB equivalent: TestVStack.testMixedColumns (extended)
        """
        df1 = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        df2 = pd.DataFrame({"b": [5, 6], "c": [7, 8]})

        result = vstack([df1, df2])

        assert len(result) == 4
        assert set(result.columns) == {"a", "b", "c"}
        # Column b should have all values
        assert list(result["b"]) == [3, 4, 5, 6]
        # Column a should have NaN in last two rows
        assert pd.isna(result.iloc[2]["a"])
        assert pd.isna(result.iloc[3]["a"])
        # Column c should have NaN in first two rows
        assert pd.isna(result.iloc[0]["c"])
        assert pd.isna(result.iloc[1]["c"])

    def test_vstack_preserves_dtypes(self):
        """Stacking preserves numeric dtypes where possible.

        MATLAB equivalent: TestVStack.testPreservesDtypes
        """
        df1 = pd.DataFrame({"x": np.array([1.0, 2.0])})
        df2 = pd.DataFrame({"x": np.array([3.0, 4.0])})

        result = vstack([df1, df2])

        assert result["x"].dtype == np.float64
        np.testing.assert_array_equal(result["x"].values, [1.0, 2.0, 3.0, 4.0])

    def test_vstack_reset_index(self):
        """Stacking resets the index to 0..N-1.

        MATLAB equivalent: rows are re-indexed after vstack
        """
        df1 = pd.DataFrame({"a": [10, 20]}, index=[5, 6])
        df2 = pd.DataFrame({"a": [30, 40]}, index=[7, 8])

        result = vstack([df1, df2])

        assert list(result.index) == [0, 1, 2, 3]
        assert list(result["a"]) == [10, 20, 30, 40]

    def test_empty_df_with_columns_stacked_with_data(self):
        """Stacking an empty DF (with columns) and a populated DF.

        MATLAB equivalent: TestVStack.testEmptyWithNonEmpty
        """
        df_empty = pd.DataFrame({"a": pd.Series(dtype="float64"), "b": pd.Series(dtype="float64")})
        df_data = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})

        result = vstack([df_empty, df_data])

        assert len(result) == 2
        assert list(result["a"]) == [1.0, 2.0]
