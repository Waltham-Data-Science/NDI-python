"""``ndi.fun.doc_table`` against ``+ndi/+fun/+docTable/``.

WHAT WAS WRONG. ``docCellArray2Table`` did not build the table MATLAB builds.

MATLAB does not flatten anything itself -- it is
``cellfun(@(doc) doc.to_table(), ...)`` followed by ``ndi.fun.table.vstack``,
and ``ndi.document/to_table`` drops ``depends_on`` and ``files``, gives each
dependency its own ``depends_on_NAME`` column, and flattens the rest with dot
notation **to any depth**.

The port flattened ``document_properties`` inline, one level deep, keeping
both of the fields MATLAB removes. On one document::

    port      base.id  base.name  depends_on  element.type  files.file_list
    MATLAB    base.id  base.name  depends_on_subject_id     element.type.nested

-- a raw ``depends_on`` column and a ``files.*`` column that should not be
there, no ``depends_on_*`` column that should, and a nested value left
unflattened. Python's own ``ndi_document.to_table`` was already a faithful
port of the MATLAB method; this function simply never called it.
"""

from __future__ import annotations

from typing import Any

import pytest

pd = pytest.importorskip("pandas")

from ndi.fun.doc_table import docCellArray2Table  # noqa: E402


class FakeDoc:
    """A document that exposes properties but no usable ``to_table``."""

    def __init__(self, props: dict[str, Any]):
        self.document_properties = props


PROPS = {
    "base": {"id": "1", "name": "n"},
    "element": {"type": {"nested": "deep"}},
    "depends_on": [{"name": "subject_id", "value": "abc"}],
    "files": {"file_list": ["f1"]},
}


class TestDocCellArray2Table:
    """MATLAB counterpart: ``+ndi/+fun/+docTable/docCellArray2Table.m``."""

    def test_depends_on_becomes_a_named_column(self):
        """MATLAB: "Each dependency has a 'depends_on_NAME' variable name"."""
        cols = docCellArray2Table([FakeDoc(PROPS)]).columns
        assert "depends_on_subject_id" in cols
        assert docCellArray2Table([FakeDoc(PROPS)])["depends_on_subject_id"][0] == "abc"

    def test_the_raw_depends_on_field_is_dropped(self):
        assert "depends_on" not in docCellArray2Table([FakeDoc(PROPS)]).columns

    def test_the_files_field_is_dropped(self):
        """``to_table`` removes ``files`` before flattening."""
        cols = docCellArray2Table([FakeDoc(PROPS)]).columns
        assert not any(c == "files" or c.startswith("files.") for c in cols)

    def test_nesting_is_flattened_to_any_depth(self):
        """The port stopped after one level, leaving a dict in the cell."""
        cols = docCellArray2Table([FakeDoc(PROPS)]).columns
        assert "element.type.nested" in cols
        assert "element.type" not in cols

    def test_the_whole_column_set_matches(self):
        assert sorted(docCellArray2Table([FakeDoc(PROPS)]).columns) == [
            "base.id",
            "base.name",
            "depends_on_subject_id",
            "element.type.nested",
        ]

    def test_a_documents_own_to_table_is_preferred(self):
        """MATLAB calls doc.to_table(); so does this when it gives a frame."""

        class WithTable(FakeDoc):
            def to_table(self):
                return pd.DataFrame([{"from_to_table": True}])

        assert list(docCellArray2Table([WithTable(PROPS)]).columns) == ["from_to_table"]

    def test_an_unusable_to_table_falls_back_to_the_properties(self):
        class Broken(FakeDoc):
            def to_table(self):
                raise RuntimeError("no pandas here")

        assert "base.id" in docCellArray2Table([Broken(PROPS)]).columns

    def test_documents_with_different_fields_are_unioned(self):
        """MATLAB combines with ndi.fun.table.vstack, "specifically designed
        to handle the case where different tables might have different sets
        of columns"."""
        a = FakeDoc({"base": {"id": "1"}, "only_a": 1})
        b = FakeDoc({"base": {"id": "2"}, "only_b": 2})
        out = docCellArray2Table([a, b])
        assert len(out) == 2
        assert {"base.id", "only_a", "only_b"} <= set(out.columns)

    def test_one_row_per_document(self):
        out = docCellArray2Table([FakeDoc(PROPS), FakeDoc(PROPS)])
        assert len(out) == 2

    def test_an_empty_list_gives_an_empty_table(self):
        """MATLAB returns table() for an empty cell array."""
        assert len(docCellArray2Table([])) == 0
