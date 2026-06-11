"""PR6 core document/database + ndi_common parity (§3.4-1/2/3, §3.6)."""

from __future__ import annotations

import pytest

from ndi.document import ndi_document


def _doc_with_depends(depends_on):
    return ndi_document(
        {
            "document_class": {"class_name": "x", "superclasses": []},
            "base": {"id": "doc1"},
            "depends_on": depends_on,
        }
    )


class TestDependencyValueN:
    """§3.4-1: numbered lookup, un-numbered fallback, empty-placeholder skip."""

    def test_numbered(self):
        d = _doc_with_depends([{"name": "elem_1", "value": "a"}, {"name": "elem_2", "value": "b"}])
        assert d.dependency_value_n("elem") == ["a", "b"]

    def test_unnumbered_fallback(self):
        d = _doc_with_depends([{"name": "elem", "value": "solo"}])
        assert d.dependency_value_n("elem") == ["solo"]

    def test_numbered_takes_priority_over_unnumbered(self):
        d = _doc_with_depends([{"name": "elem", "value": "solo"}, {"name": "elem_1", "value": "a"}])
        # the numbered series wins; the un-numbered fallback only applies when
        # there is no elem_1
        assert d.dependency_value_n("elem") == ["a"]

    def test_empty_placeholder_skipped(self):
        d = _doc_with_depends([{"name": "elem", "value": ""}])
        assert d.dependency_value_n("elem", error_if_not_found=False) == []

    def test_missing_raises(self):
        d = _doc_with_depends([{"name": "other", "value": "x"}])
        with pytest.raises(KeyError):
            d.dependency_value_n("elem")


class TestAddDuplicateFile:
    """§3.4-2: document '+' must error on a duplicate file name, not dedup."""

    def _doc_with_files(self, doc_id, files):
        return ndi_document(
            {
                "document_class": {"class_name": "x", "superclasses": []},
                "base": {"id": doc_id},
                "files": {"file_list": list(files)},
            }
        )

    def test_disjoint_files_merge_in_order(self):
        a = self._doc_with_files("a", ["f1.ext", "f2.ext"])
        b = self._doc_with_files("b", ["f3.ext"])
        merged = a + b
        assert merged._document_properties["files"]["file_list"] == ["f1.ext", "f2.ext", "f3.ext"]

    def test_duplicate_file_name_raises(self):
        a = self._doc_with_files("a", ["shared.ext", "f1.ext"])
        b = self._doc_with_files("b", ["shared.ext"])
        with pytest.raises(ValueError, match="duplicate file name"):
            _ = a + b


class TestNdiCommonDefinitions:
    """§3.4-3: the newly-copied definitions load; ontologyTableRow has depends_on."""

    @pytest.mark.parametrize(
        "doc_type,class_name",
        [
            ("apps/kilosort/kilosort_clusters", "kilosort_clusters"),
            ("data/filter", "filter"),
            ("data/pyraview", "pyraview"),
            ("treatment/treatment_transfer", "treatment_transfer"),
        ],
    )
    def test_new_definition_loads(self, doc_type, class_name):
        d = ndi_document.read_blank_definition(doc_type)
        assert d["document_class"]["class_name"] == class_name

    def test_ontologytablerow_has_document_id_dependency(self):
        d = ndi_document.read_blank_definition("data/ontologyTableRow")
        names = [dep.get("name") for dep in d.get("depends_on", [])]
        assert "document_id" in names


class TestDefinitionCaching:
    """§3.6: read_blank_definition is memoized but returns independent copies."""

    def test_cached_after_first_read(self):
        ndi_document._DEFINITION_CACHE.pop("data/filter", None)
        ndi_document.read_blank_definition("data/filter")
        assert "data/filter" in ndi_document._DEFINITION_CACHE

    def test_returns_independent_copies(self):
        a = ndi_document.read_blank_definition("data/filter")
        a["__scribble__"] = 123  # mutate the returned dict
        b = ndi_document.read_blank_definition("data/filter")
        # the cache (and a fresh read) must be unaffected by the mutation
        assert "__scribble__" not in b
