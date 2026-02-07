"""
Tests for Phase 11 Batch 11D: Database Utilities + Ingestion.

Tests dependency traversal, batch retrieval, graph construction,
and file ingestion/expulsion system.
"""

from unittest.mock import MagicMock

from ndi.database_fun import (
    docs2graph,
    docs_from_ids,
    find_ingested_docs,
    findallantecedents,
    findalldependencies,
    finddocs_missing_dependencies,
)
from ndi.database_ingestion import (
    expell,
    expell_plan,
    ingest,
    ingest_plan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _doc(doc_id, depends_on=None, file_info=None, file_uid=""):
    d = MagicMock()
    props = {
        "base": {"id": doc_id, "session_id": "sess-1"},
        "depends_on": depends_on or [],
    }
    if file_info or file_uid:
        if file_uid:
            props["file_uid"] = file_uid
        if file_info:
            props["files"] = {"file_info": file_info}
    d.document_properties = props
    return d


# ===========================================================================
# Dependency traversal
# ===========================================================================


class TestFindAllAntecedents:
    def test_basic(self):
        doc_a = _doc("a", depends_on=[{"name": "dep", "value": "b"}])
        doc_b = _doc("b")
        session = MagicMock()
        session.database_search.return_value = [doc_b]
        result = findallantecedents(session, doc_a)
        assert any(d.document_properties["base"]["id"] == "b" for d in result)

    def test_no_deps(self):
        doc = _doc("a")
        session = MagicMock()
        result = findallantecedents(session, doc)
        assert result == []

    def test_circular_protection(self):
        doc_a = _doc("a", depends_on=[{"name": "d", "value": "b"}])
        doc_b = _doc("b", depends_on=[{"name": "d", "value": "a"}])
        session = MagicMock()
        session.database_search.return_value = [doc_b]
        result = findallantecedents(session, doc_a)
        # Should not infinite loop
        assert isinstance(result, list)


class TestFindAllDependencies:
    def test_basic(self):
        doc_a = _doc("a")
        doc_b = _doc("b", depends_on=[{"name": "dep", "value": "a"}])
        session = MagicMock()
        session.database_search.return_value = [doc_b]
        result = findalldependencies(session, doc_a)
        assert len(result) >= 1

    def test_no_dependents(self):
        doc = _doc("a")
        session = MagicMock()
        session.database_search.return_value = []
        result = findalldependencies(session, doc)
        assert result == []


# ===========================================================================
# Batch retrieval
# ===========================================================================


class TestDocsFromIds:
    def test_basic(self):
        doc1 = _doc("d1")
        doc2 = _doc("d2")
        session = MagicMock()
        session.database_search.return_value = [doc1, doc2]
        result = docs_from_ids(session, ["d1", "d2"])
        assert len(result) == 2
        assert result[0] is not None
        assert result[1] is not None

    def test_partial_missing(self):
        doc1 = _doc("d1")
        session = MagicMock()
        session.database_search.return_value = [doc1]
        result = docs_from_ids(session, ["d1", "d2", "d3"])
        assert len(result) == 3
        assert result[0] is not None
        assert result[1] is None
        assert result[2] is None

    def test_empty_ids(self):
        session = MagicMock()
        assert docs_from_ids(session, []) == []

    def test_preserves_order(self):
        doc_a = _doc("a")
        doc_b = _doc("b")
        session = MagicMock()
        session.database_search.return_value = [doc_b, doc_a]  # reversed
        result = docs_from_ids(session, ["a", "b"])
        assert result[0].document_properties["base"]["id"] == "a"
        assert result[1].document_properties["base"]["id"] == "b"


# ===========================================================================
# Graph construction
# ===========================================================================


class TestDocs2Graph:
    def test_basic_graph(self):
        doc_a = _doc("a", depends_on=[{"name": "dep", "value": "b"}])
        doc_b = _doc("b")
        adj, nodes = docs2graph([doc_a, doc_b])
        assert "a" in nodes
        assert "b" in nodes
        assert "b" in adj["a"]  # a depends on b
        assert adj["b"] == []  # b depends on nothing

    def test_empty(self):
        adj, nodes = docs2graph([])
        assert adj == {}
        assert nodes == []

    def test_no_edges(self):
        adj, nodes = docs2graph([_doc("x"), _doc("y")])
        assert adj["x"] == []
        assert adj["y"] == []

    def test_external_dep_excluded(self):
        """Dependencies referencing docs not in the list are excluded."""
        doc_a = _doc("a", depends_on=[{"name": "dep", "value": "external"}])
        adj, nodes = docs2graph([doc_a])
        assert adj["a"] == []


# ===========================================================================
# Find ingested docs
# ===========================================================================


class TestFindIngestedDocs:
    def test_returns_results(self):
        session = MagicMock()
        session.database_search.return_value = [_doc("i1")]
        result = find_ingested_docs(session)
        assert len(result) == 1

    def test_empty(self):
        session = MagicMock()
        session.database_search.return_value = []
        result = find_ingested_docs(session)
        assert result == []


# ===========================================================================
# Missing dependencies
# ===========================================================================


class TestFindDocsMissingDependencies:
    def test_finds_missing(self):
        doc_a = _doc("a", depends_on=[{"name": "dep", "value": "nonexistent"}])
        doc_b = _doc("b")
        session = MagicMock()
        session.database_search.return_value = [doc_a, doc_b]
        result = finddocs_missing_dependencies(session)
        ids = [d.document_properties["base"]["id"] for d in result]
        assert "a" in ids

    def test_no_missing(self):
        doc_a = _doc("a", depends_on=[{"name": "dep", "value": "b"}])
        doc_b = _doc("b")
        session = MagicMock()
        session.database_search.return_value = [doc_a, doc_b]
        result = finddocs_missing_dependencies(session)
        assert result == []

    def test_filter_by_name(self):
        doc = _doc(
            "a",
            depends_on=[
                {"name": "subject_id", "value": "nonexistent"},
                {"name": "element_id", "value": "also_missing"},
            ],
        )
        session = MagicMock()
        session.database_search.return_value = [doc]
        # Only check 'element_id'
        result = finddocs_missing_dependencies(session, "element_id")
        assert len(result) == 1


# ===========================================================================
# Ingestion plan
# ===========================================================================


class TestIngestPlan:
    def test_basic_plan(self):
        doc = _doc(
            "d1",
            file_info=[
                {
                    "locations": [
                        {
                            "location": "/data/file.bin",
                            "uid": "uid-123",
                            "ingest": True,
                            "delete_original": True,
                        }
                    ],
                }
            ],
        )
        src, dst, delete = ingest_plan(doc, "/db/files")
        assert src == ["/data/file.bin"]
        assert dst == ["/db/files/uid-123"]
        assert delete == ["/data/file.bin"]

    def test_no_ingest_flag(self):
        doc = _doc(
            "d1",
            file_info=[
                {
                    "locations": [
                        {
                            "location": "/data/file.bin",
                            "uid": "uid-123",
                            "ingest": False,
                            "delete_original": False,
                        }
                    ],
                }
            ],
        )
        src, dst, delete = ingest_plan(doc, "/db/files")
        assert src == []
        assert dst == []
        assert delete == []

    def test_no_files(self):
        doc = _doc("d1")
        src, dst, delete = ingest_plan(doc, "/db/files")
        assert src == []


# ===========================================================================
# Ingestion execution
# ===========================================================================


class TestIngest:
    def test_copy_files(self, tmp_path):
        src = tmp_path / "source.bin"
        src.write_bytes(b"test data")
        dst = tmp_path / "db" / "uid-123"

        ok, msg = ingest([str(src)], [str(dst)], [])
        assert ok is True
        assert msg == ""
        assert dst.read_bytes() == b"test data"

    def test_copy_and_delete(self, tmp_path):
        src = tmp_path / "source.bin"
        src.write_bytes(b"data")
        dst = tmp_path / "dest.bin"

        ok, msg = ingest([str(src)], [str(dst)], [str(src)])
        assert ok is True
        assert not src.exists()  # deleted
        assert dst.exists()  # copied

    def test_copy_failure(self, tmp_path):
        ok, msg = ingest(["/nonexistent/file.bin"], [str(tmp_path / "x")], [])
        assert ok is False
        assert "Copying" in msg


# ===========================================================================
# Expulsion
# ===========================================================================


class TestExpellPlan:
    def test_basic(self):
        doc = _doc(
            "d1",
            file_info=[
                {
                    "locations": [
                        {
                            "uid": "uid-abc",
                            "ingest": True,
                        }
                    ],
                }
            ],
        )
        result = expell_plan(doc, "/db/files")
        assert result == ["/db/files/uid-abc"]

    def test_no_ingested(self):
        doc = _doc(
            "d1",
            file_info=[
                {
                    "locations": [{"uid": "x", "ingest": False}],
                }
            ],
        )
        assert expell_plan(doc, "/db/files") == []


class TestExpell:
    def test_delete_files(self, tmp_path):
        f = tmp_path / "uid-abc"
        f.write_bytes(b"data")
        ok, msg = expell([str(f)])
        assert ok is True
        assert not f.exists()

    def test_empty_list(self):
        ok, msg = expell([])
        assert ok is True

    def test_missing_file_ok(self, tmp_path):
        ok, msg = expell([str(tmp_path / "nonexistent")])
        assert ok is True  # missing_ok=True


# ===========================================================================
# Imports
# ===========================================================================


class TestImports:
    def test_database_fun_imports(self):
        from ndi.database_fun import (
            findallantecedents,
        )

        assert callable(findallantecedents)

    def test_ingestion_imports(self):
        from ndi.database_ingestion import (
            ingest_plan,
        )

        assert callable(ingest_plan)
