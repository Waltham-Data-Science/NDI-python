"""ndi.gui against MATLAB's +ndi/+gui/.

PySide6 is an extra, and CI does not install it, so every Qt path in this
package is unexercised. What can be tested is the plain-Python underneath --
which is where the defects covered here live: a query built with an operator
that does not exist, a document row read out of a schema field that no longer
exists, and the connection state machine that governs the Experiment View.

The last test in the file is a guard rather than a port: a mechanical rename
of class names leaked into user-visible strings ("ndi_database View",
"Neuroscience ndi_gui_Data Interface"), and nothing would have caught it.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from ndi.document import ndi_document
from ndi.gui.data import document_columns
from ndi.gui.gui_v2 import all_documents_query, icon_for, probe_daq_pairs
from ndi.gui.lab import ACTIVE_TERMINAL_COLORS, set_activation

SUBJECT = (0.2, 0.4, 1.0)
PROBE = (0.0, 0.6, 0.0)
DAQ = (1.0, 0.6, 0.0)


def icon(color, active=1, elem=None):
    return SimpleNamespace(c=color, active=active, elem=elem)


class TestAllDocumentsQuery:
    """The Database View came up empty on every session."""

    def test_the_query_can_be_built(self):
        # 'regex' is not an ndi_query operator; ndi_query raised ValueError,
        # the call sat inside a bare `except Exception`, and the view showed
        # no documents at all.
        assert all_documents_query() is not None

    def test_it_is_the_operator_matlab_uses(self):
        assert all_documents_query().search_structure[0]["operation"] == "regexp"

    def test_it_matches_every_id(self):
        s = all_documents_query().search_structure[0]
        assert s["field"] == "base.id"
        assert s["param1"] == "(.*)"


class TestDocumentColumns:
    """MATLAB reads name/id/type/datestamp out of the LEGACY schema field."""

    def test_a_modern_document_fills_every_column(self):
        doc = ndi_document("subject")
        doc._set_nested_property("base.name", "my subject")
        name, doc_id, doc_type, datestamp = document_columns(doc.document_properties)
        assert name == "my subject"
        assert doc_id == doc.id
        assert doc_type == "subject"
        assert datestamp

    def test_a_modern_document_used_to_come_out_blank(self):
        # base.name/id/datestamp are not at the top level, and there is no
        # 'ndi_document' field to fall back to, so all four read ''.
        props = ndi_document("subject").document_properties
        assert "ndi_document" not in props
        assert all(k not in props for k in ("name", "id", "type", "datestamp"))

    def test_the_legacy_field_is_still_read_first(self):
        props = {
            "ndi_document": {"name": "n", "id": "i", "type": "t", "datestamp": "d"},
            "base": {"name": "ignored"},
        }
        assert document_columns(props) == ("n", "i", "t", "d")

    def test_the_type_column_falls_back_to_the_class_name(self):
        props = {"base": {"id": "x"}, "document_class": {"class_name": "stimulus"}}
        assert document_columns(props)[2] == "stimulus"

    def test_nothing_at_all_gives_four_empty_strings(self):
        assert document_columns({}) == ("", "", "", "")

    def test_a_non_dict_properties_object_does_not_raise(self):
        assert document_columns(object()) == ("", "", "", "")

    def test_every_column_is_a_string(self):
        props = {"base": {"id": 12345, "name": None}}
        assert all(isinstance(v, str) for v in document_columns(props))


class TestProbeDaqPairs:
    def test_a_probe_is_paired_with_its_first_epochs_device(self):
        probe = SimpleNamespace(getchanneldevinfo=lambda n: {"daqsystem": "DAQ1"})
        assert probe_daq_pairs([probe]) == [(probe, "DAQ1")]

    def test_a_probe_with_no_epochs_is_skipped(self):
        def boom(n):
            raise IndexError("no epochs")

        assert probe_daq_pairs([SimpleNamespace(getchanneldevinfo=boom)]) == []

    def test_a_probe_whose_epoch_names_no_device_is_skipped(self):
        probe = SimpleNamespace(getchanneldevinfo=lambda n: {"daqsystem": None})
        assert probe_daq_pairs([probe]) == []

    def test_several_probes_keep_their_order(self):
        a = SimpleNamespace(getchanneldevinfo=lambda n: {"daqsystem": "A"})
        b = SimpleNamespace(getchanneldevinfo=lambda n: {"daqsystem": "B"})
        assert probe_daq_pairs([a, b]) == [(a, "A"), (b, "B")]


class TestIconFor:
    """MATLAB's findobj(list, 'elem', X)."""

    def test_it_finds_by_identity(self):
        probe = object()
        found = icon(PROBE, elem=probe)
        assert icon_for([icon(PROBE, elem=object()), found], probe) is found

    def test_a_subject_icon_holds_a_one_element_document_list(self):
        doc = SimpleNamespace(id="sid-1")
        subject_icon = icon(SUBJECT, elem=[doc])
        assert icon_for([subject_icon], "sid-1") is subject_icon
        assert icon_for([subject_icon], doc) is subject_icon

    def test_an_unknown_element_gives_none(self):
        assert icon_for([icon(PROBE, elem=object())], object()) is None

    def test_none_gives_none(self):
        assert icon_for([icon(PROBE, elem=object())], None) is None


class TestSetActivation:
    """MATLAB's Lab.symbol, which had no Python counterpart at all."""

    def test_clicking_a_subject_offers_only_the_probes(self):
        s1, s2 = icon(SUBJECT), icon(SUBJECT)
        p1 = icon(PROBE)
        d1 = icon(DAQ, active=0)
        set_activation([s1, s2], [p1], [d1], s1)
        assert s1.active == 3  # the source
        assert s2.active == 0  # other subjects are not targets
        assert p1.active == 2  # probes are
        assert d1.active == 0  # DAQs are not

    def test_clicking_the_same_subject_again_puts_it_back(self):
        s1, p1 = icon(SUBJECT), icon(PROBE)
        set_activation([s1], [p1], [], s1)
        set_activation([s1], [p1], [], s1)
        assert s1.active == 1
        assert p1.active == 1

    def test_clicking_a_probe_offers_only_the_daqs(self):
        s1, p1, p2, d1 = icon(SUBJECT), icon(PROBE), icon(PROBE), icon(DAQ, active=0)
        set_activation([s1], [p1, p2], [d1], p1)
        assert p1.active == 3
        assert p2.active == 0
        assert s1.active == 0
        assert d1.active == 2

    def test_clicking_the_same_probe_again_puts_it_back(self):
        s1, p1, d1 = icon(SUBJECT), icon(PROBE), icon(DAQ)
        set_activation([s1], [p1], [d1], p1)
        set_activation([s1], [p1], [d1], p1)
        assert s1.active == 1
        assert p1.active == 1
        assert d1.active == 0  # DAQs are never a connection SOURCE

    def test_clicking_a_daq_resets_everything(self):
        s1, p1, d1 = icon(SUBJECT, active=0), icon(PROBE, active=2), icon(DAQ, active=3)
        set_activation([s1], [p1], [d1], d1)
        assert s1.active == 1
        assert p1.active == 1
        assert d1.active == 0

    def test_the_terminal_colours_are_matlabs(self):
        # white / green / red for active 1 / 2 / 3.
        assert ACTIVE_TERMINAL_COLORS == {
            1: (1.0, 1.0, 1.0),
            2: (0.0, 1.0, 0.0),
            3: (1.0, 0.0, 0.0),
        }


# ---------------------------------------------------------------------------
# Guard: internal identifiers must not appear in user-visible text
# ---------------------------------------------------------------------------

#: Prefixes a mechanical class rename introduced into display strings.
_INTERNAL_MARKERS = (
    "ndi_gui_",
    "ndi_database",
    "ndi_document",
    "ndi_session",
    "ndi_cache",
    "ndi_epoch",
)

#: Calls whose string arguments end up in front of a user.
_DISPLAY_CALLS = {
    "setWindowTitle",
    "setText",
    "addTab",
    "setToolTip",
    "QLabel",
    "QPushButton",
    "setPlaceholderText",
}

GUI_ROOT = Path(__file__).resolve().parent.parent / "src" / "ndi" / "gui"


def _display_strings(path: Path):
    """Yield (lineno, text) for every string literal handed to a display call."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name not in _DISPLAY_CALLS:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                yield node.lineno, arg.value


@pytest.mark.parametrize(
    "source", sorted(GUI_ROOT.rglob("*.py")), ids=lambda p: str(p.relative_to(GUI_ROOT))
)
def test_no_internal_identifier_reaches_the_user(source):
    """A rename of Data -> ndi_gui_Data must not reach a window title.

    MATLAB's window is 'Neuroscience Data Interface' and its tabs are
    'Experiment View' and 'Database View'. A mechanical rename turned those
    into 'Neuroscience ndi_gui_Data Interface' and 'ndi_database View', and
    the same rename put 'ndi_cache', 'ndi_database' and 'ndi_document
    Properties' on three panel headings in ndi.gui.gui.
    """
    offenders = [
        f"{source.name}:{lineno}: {text!r}"
        for lineno, text in _display_strings(source)
        if any(marker in text for marker in _INTERNAL_MARKERS)
    ]
    assert not offenders, "internal identifiers in user-visible text:\n  " + "\n  ".join(offenders)
