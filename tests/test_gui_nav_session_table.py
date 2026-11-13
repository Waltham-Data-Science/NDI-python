"""ndi.gui.nav.session_table against MATLAB's sessionTable.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/sessionTable.m`` (tests:
``tests/+ndi/+unittest/+gui/+nav/sessionTable_test.m``)

The helpers are plain Python and run everywhere; the window test builds it
under the offscreen platform and skips without PySide6.
"""

from __future__ import annotations

import math
import os

import pytest

pd = pytest.importorskip("pandas")

import ndi.fun.doc_table as doc_table  # noqa: E402
import ndi.gui.nav.session_table as st  # noqa: E402


class TestKinds:
    def test_table_kinds_order_and_functions(self):
        kinds = st.table_kinds()
        assert [k["Kind"] for k in kinds] == [
            "element",
            "epoch",
            "probe",
            "subject",
            "treatment",
        ]
        labels = [k["Label"] for k in kinds]
        assert labels == [
            "Elements...",
            "Epochs...",
            "Probes...",
            "Subjects...",
            "Treatments...",
        ]
        assert sorted(labels) == labels
        for k in kinds:
            assert callable(getattr(doc_table, k["python_function"]))
            assert k["VariableName"].isidentifier()

    def test_kind_info(self):
        info = st.kind_info("Subject")
        assert info["Kind"] == "subject"
        assert info["Title"] == "Subject table"
        with pytest.raises(ValueError, match="Unknown session table kind"):
            st.kind_info("nope")


class TestFormatting:
    def test_summary_text(self):
        assert st.summary_text("Probe table", pd.DataFrame()) == "Probe table (0 rows)"
        assert st.summary_text("Probe table", pd.DataFrame({"a": [1]})) == "Probe table (1 row)"
        assert st.summary_text("Probe table", pd.DataFrame({"a": [1, 2]})) == "Probe table (2 rows)"

    def test_cell_text(self):
        f = st.cell_text
        assert f("abc") == "abc"
        assert f("") == ""
        assert f(["a", "b"]) == "a, b"
        assert f(3) == "3"
        assert f(3.0) == "3"
        assert f(math.nan) == ""
        assert f(None) == ""
        assert f([1, 2]) == "[1 2]"
        assert f(True) == "true"
        assert f([]) == ""
        assert f(["a", 2, ""]) == "a, 2"
        assert f({"a": 1}) == "<struct>"

    def test_table_cells(self):
        T = pd.DataFrame({"Name": ["s1", "s2"], "Value": [1, math.nan], "Pair": [[1, 2], [3, 4]]})
        names, rows = st.table_cells(T)
        assert names == ["Name", "Value", "Pair"]
        assert rows == [["s1", "1", "[1 2]"], ["s2", "", "[3 4]"]]

    def test_table_cells_empty(self):
        assert st.table_cells(pd.DataFrame()) == ([], [])


class TestComputeAndActions:
    def test_compute_table_keeps_the_first_output(self, monkeypatch):
        df = pd.DataFrame({"a": [1]})
        monkeypatch.setattr(doc_table, "treatment", lambda s: (df, ["id"], ["dep"]))
        assert st.compute_table(object(), "treatment") is df

    def test_compute_table_non_frame_is_empty(self, monkeypatch):
        monkeypatch.setattr(doc_table, "element", lambda s: None)
        assert st.compute_table(object(), "element").empty

    def test_assign_and_export(self, monkeypatch, tmp_path):
        import __main__

        df = pd.DataFrame({"Name": ["s1"], "Value": [2.0]})
        monkeypatch.setattr(doc_table, "subject", lambda s: df)
        window = st.SessionTable(object(), "subject", build=False)
        assert window.table is df

        monkeypatch.delattr(__main__, "subjectTableTest", raising=False)
        assert window.assign_to_workspace("subjectTableTest") == "subjectTableTest"
        assert __main__.__dict__["subjectTableTest"] is df
        del __main__.__dict__["subjectTableTest"]
        assert window.assign_to_workspace("1bad") is None

        out = tmp_path / "subjects.csv"
        assert window.export_csv(str(out)) == str(out)
        assert out.read_text().splitlines() == ["Name,Value", "s1,2"]


def test_window_shows_the_table(monkeypatch):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")

    df = pd.DataFrame({"probe_name": ["ctx", "lgn"], "probe_reference": [1, 2]})
    monkeypatch.setattr(doc_table, "probe", lambda s: df)

    class S:
        reference = "exp1"

    window = st.SessionTable(S(), "probe")
    assert window.figure.windowTitle() == "Probe table: exp1"
    assert window.ui_table.rowCount() == 2
    assert window.ui_table.columnCount() == 2
    assert window.ui_table.item(1, 0).text() == "lgn"
