"""ndi.document against MATLAB's +ndi/document.m.

Covers the three things the Python class did not do: abbreviate ``to_table``
column names, keep nested fields that happen to be named ``files`` or
``depends_on``, expand a struct-array property into one column per sub-field,
and answer ``get_fuid``.
"""

import json
import warnings

import pytest

from ndi.common import ndi_common_PathConstants
from ndi.document import ndi_document

pd = pytest.importorskip("pandas")


def columns(doc):
    return list(doc.to_table().columns)


class TestToTableAbbreviations:
    """MATLAB shortens column names through ndi_document2table_abbreviations.json."""

    def test_the_abbreviation_file_ships_here(self):
        path = ndi_common_PathConstants.COMMON_FOLDER / "config"
        path = path / "ndi_document2table_abbreviations.json"
        assert path.is_file(), f"{path} is what MATLAB's to_table reads"

    def test_the_pairs_are_read_in_file_order(self):
        path = (
            ndi_common_PathConstants.COMMON_FOLDER
            / "config"
            / "ndi_document2table_abbreviations.json"
        )
        on_disk = [(p[0], p[1]) for p in json.load(open(path))]
        assert ndi_document._table_abbreviations() == on_disk

    def test_a_long_name_is_abbreviated(self):
        doc = ndi_document({"base": {"id": "x"}, "orientation_direction_tuning": {"a": 1}})
        assert "oridir.a" in columns(doc)
        assert "orientation_direction_tuning.a" not in columns(doc)

    def test_replacements_apply_in_order_not_longest_first(self):
        # 'orientation_direction_tuning' -> 'oridir' comes before
        # 'orientation' -> 'ori', so the long name never gets chewed into
        # 'ori_direction_tuning'.
        doc = ndi_document({"base": {"id": "x"}, "orientation_direction_tuning": {"b": 1}})
        assert "oridir.b" in columns(doc)

    def test_several_pairs_hit_one_name(self):
        doc = ndi_document(
            {
                "base": {"id": "x"},
                "tuning_curve": {"spatial_frequency": {"significance": 2}},
            }
        )
        assert "TC.SF.sig" in columns(doc)

    def test_dependency_columns_are_not_abbreviated(self):
        # MATLAB builds the depends_on_ columns BEFORE flattenstruct2table,
        # so the abbreviation pass never sees them.
        doc = ndi_document(
            {
                "base": {"id": "x"},
                "depends_on": [{"name": "orientation_direction_tuning", "value": "v"}],
            }
        )
        assert "depends_on_orientation_direction_tuning" in columns(doc)

    def test_a_name_with_no_pair_is_untouched(self):
        doc = ndi_document({"base": {"id": "x"}, "unremarkable": {"field": 1}})
        assert "unremarkable.field" in columns(doc)


class TestToTableRemovesOnlyTheTopLevel:
    """rmfield reaches the top level; the old flatten skipped every depth."""

    def test_a_nested_files_field_survives(self):
        doc = ndi_document({"base": {"id": "x"}, "nested": {"files": {"count": 3}}})
        assert "nested.files.count" in columns(doc)

    def test_a_nested_depends_on_field_survives(self):
        doc = ndi_document({"base": {"id": "x"}, "nested": {"depends_on": {"who": "me"}}})
        assert "nested.depends_on.who" in columns(doc)

    def test_the_top_level_files_is_still_removed(self):
        doc = ndi_document({"base": {"id": "x"}, "files": {"file_list": ["a"]}})
        assert not [c for c in columns(doc) if c.startswith("files")]

    def test_the_top_level_depends_on_becomes_its_own_columns(self):
        doc = ndi_document(
            {"base": {"id": "x"}, "depends_on": [{"name": "subject_id", "value": "s1"}]}
        )
        cols = columns(doc)
        assert "depends_on_subject_id" in cols
        assert not [c for c in cols if c.startswith("depends_on.")]


class TestToTableStructArrays:
    """flattenstruct2table's struct-array case: one column per sub-field."""

    def test_a_multi_element_record_list_expands(self):
        doc = ndi_document(
            {
                "base": {"id": "x"},
                "rows": [{"a": 1, "b": "p"}, {"a": 2, "b": "q"}],
            }
        )
        cols = columns(doc)
        assert "rows.a" in cols and "rows.b" in cols
        assert "rows" not in cols

    def test_the_expanded_column_holds_every_value(self):
        doc = ndi_document({"base": {"id": "x"}, "rows": [{"a": 1}, {"a": 2}, {"a": 3}]})
        assert doc.to_table()["rows.a"].iloc[0] == [1, 2, 3]

    def test_a_one_element_list_is_a_scalar_struct(self):
        # MATLAB's jsondecode turns a 1-element array of objects into a 1x1
        # struct, which flattenstruct2table recurses into normally.
        doc = ndi_document({"base": {"id": "x"}, "rows": [{"a": 7}]})
        assert doc.to_table()["rows.a"].iloc[0] == 7

    def test_a_list_of_scalars_stays_one_column(self):
        # A cell array of chars is not a struct, so MATLAB leaves it alone.
        doc = ndi_document({"base": {"id": "x"}, "tags": ["a", "b"]})
        assert doc.to_table()["tags"].iloc[0] == ["a", "b"]

    def test_superclasses_expand_like_matlab(self):
        doc = ndi_document("subject")
        assert "document_class.superclasses.definition" in columns(doc)

    def test_an_empty_list_is_left_alone(self):
        doc = ndi_document({"base": {"id": "x"}, "rows": []})
        assert doc.to_table()["rows"].iloc[0] == []


class TestGetFuid:
    """MATLAB's get_fuid; findFuid and the session/dataset diffs need it."""

    def test_the_method_exists(self):
        assert callable(getattr(ndi_document, "get_fuid", None))

    def test_a_document_with_no_files_returns_empty(self):
        assert ndi_document("base").get_fuid("anything") == ""

    def test_a_declared_but_unadded_file_returns_empty(self):
        assert ndi_document("demoNDI").get_fuid("filename1.ext") == ""

    def test_an_undeclared_name_returns_empty(self):
        doc = ndi_document("demoNDI")
        doc.add_file("filename1.ext", "/tmp/whatever.bin")
        assert doc.get_fuid("not_declared") == ""

    def test_it_returns_the_uid_of_the_added_file(self):
        doc = ndi_document("demoNDI")
        doc.add_file("filename1.ext", "/tmp/whatever.bin")
        expected = doc.document_properties["files"]["file_info"][0]["locations"][0]["uid"]
        assert doc.get_fuid("filename1.ext") == expected

    def test_it_returns_the_first_location_when_there_are_several(self):
        doc = ndi_document("demoNDI")
        doc.add_file("filename1.ext", "/tmp/whatever.bin")
        first = doc.get_fuid("filename1.ext")
        doc.add_file("filename1.ext", "https://example.com/whatever.bin")
        assert doc.get_fuid("filename1.ext") == first

    def test_it_round_trips_against_findFuid(self):
        from ndi.fun.doc import findFuid

        doc = ndi_document("demoNDI")
        doc.add_file("filename1.ext", "/tmp/whatever.bin")
        uid = doc.get_fuid("filename1.ext")

        class _Session:
            def database_search(self, query):
                return [doc]

        found_doc, found_name = findFuid(_Session(), uid)
        assert found_doc is doc
        assert found_name == "filename1.ext"


class TestDocUniqueId:
    """MATLAB keeps the deprecated alias and warns; so does this."""

    def test_it_returns_the_id(self):
        doc = ndi_document("base")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            assert doc.doc_unique_id() == doc.id

    def test_it_warns(self):
        doc = ndi_document("base")
        with pytest.warns(DeprecationWarning):
            doc.doc_unique_id()
