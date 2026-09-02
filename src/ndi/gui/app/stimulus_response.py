"""ndi.gui.app.stimulus_response - compute stimulus responses for elements.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/stimulusResponse.m``

A window over ``ndi.app.stimulus.tuning_response.stimulus_responses``. Pick a
stimulator probe, pick the element types to compute on, press the button: for
each element of those types the app computes the responses to that
stimulator's presentations and stores them in the session database.

Responses need the stimuli decoded and their control stimuli labeled first,
which is what :class:`ndi.gui.app.stimulus_decoder.stimulusDecoder` does.
Without the ``stimulus_presentation`` and ``control_stimulus_ids`` documents
there is nothing to compute against, and each element simply produces
nothing. The two apps are the two halves of the pipeline, in that order.

TWO SEARCHES, NOT TWO PER ELEMENT
The expensive thing here is the database, not the arithmetic, so both paths
ask it once for everything rather than once per element:

* "Replace existing responses" runs ONE search -- an OR over every chosen
  element -- removes the stimulus_response documents it finds along with
  their scalar-parameter documents, and then recomputes for every element;
* left unticked, ONE search lists the elements that already have a response
  for this stimulator, and only the elements missing from that list are
  computed.

Either way ``stimulus_responses`` is called with ``reset=False``: the replace
path has already removed the old documents, and the skip path is only ever
handed elements that have none. Passing reset would re-do that work, and on
the skip path would silently discard responses the user asked to keep.

WHAT THE WIDGETS HOLD AND WHAT THE OBJECT HOLDS
The selection lives on the object -- ``probe_index``, ``element_types``,
``replace`` -- and the widgets write into it. So the whole run path can be
driven, and tested, with no display attached, which matters for an app whose
interesting behaviour is which elements it decides to compute and which
documents it decides to delete.

AN ELEMENT THAT REACHES AN UNPORTED PATH SAYS SO
``stimulus_responses`` is ported, but an element can still reach something
that is not -- a reader for a format nobody has written yet, say. A
NotImplementedError from any depth is counted as that element's failure, as
MATLAB counts any failure, and the summary names the unported computation
rather than leaving a user to read "0 computed" and guess why. See
:func:`summary_message`.

PROGRESS DOCKS IN MATLAB AND DOES NOT HERE
MATLAB's ProgressBarWindow docks into an open navigator's Progress pane. The
ported component opens its own window instead (see
``ndi.gui.component.ProgressBarWindow``); that divergence is the component's,
not this app's, and this app will dock the day the component does.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from typing import Any, NamedTuple

from ...fun.utils import identifier
from .session_app import SessionApp

__all__ = [
    "stimulusResponse",
    "ELEMENT_TYPES",
    "RunResult",
    "elements_to_compute",
    "probe_labels",
    "response_query",
    "summary_message",
    "NOTHING_SELECTED",
    "NO_ELEMENTS",
    "NOTHING_TO_DO",
    "NO_STIMULATORS",
    "WINDOW_TAG",
    "DEFAULT_POSITION",
]

#: The element types offered in the listbox. MATLAB's private ElementTypes
#: constant: spiking elements only for now, and a type is added here as it
#: becomes supported.
ELEMENT_TYPES: tuple[str, ...] = ("spikes",)

#: Object name on the window, so an open app can be found again -- the
#: reading of MATLAB's figure 'Tag'.
WINDOW_TAG = "ndi.gui.app.stimulusResponse"

#: Default geometry ``(x, y, width, height)``, as MATLAB has it.
DEFAULT_POSITION = (100, 100, 640, 460)

#: Shown when Run is pressed with no stimulator or no element type.
NOTHING_SELECTED = "Choose a stimulator probe and at least one element type."

#: Shown when the session holds no elements of the chosen type(s).
NO_ELEMENTS = "No elements of the selected type(s) were found in this session."

#: Shown when every element already has a response and Replace is unticked.
NOTHING_TO_DO = (
    'Every element of the selected type(s) already has a stimulus response. Tick "Replace '
    'existing responses" to rebuild them.'
)

#: The dropdown's sole entry when the session has no stimulator probes.
NO_STIMULATORS = "(no stimulator probes)"

#: Appended when the failures were the unported computation rather than the
#: data. See the module docstring.
UNPORTED_NOTE = (
    " Those failures were a step that is not ported yet, not the data:"
    " something the computation reached raised NotImplementedError."
)


class RunResult(NamedTuple):
    """What one press of "Compute responses" did.

    MATLAB returns nothing and says this in a dialog. Returning it as well
    costs nothing and is what lets the decision logic -- how many elements
    were computed, skipped, failed -- be checked without reading a dialog off
    a screen.
    """

    computed: int
    skipped: int
    failed: int
    message: str


def probe_labels(stimulators: Sequence[Any]) -> list[str]:
    """The dropdown labels for STIMULATORS, one per probe.

    ``elementstring()`` ("name | reference") is what the rest of the GUI
    names elements by (see ``ndi.gui.nav.session_info``), so a probe reads
    the same here as it does there. A probe whose label cannot be read falls
    back to its repr rather than to "", which would leave a user choosing
    between blank rows.
    """
    labels = []
    for probe in stimulators:
        try:
            labels.append(str(probe.elementstring()))
        except Exception:  # noqa: BLE001 - a probe that will not name itself
            labels.append(repr(probe))
    return labels


def response_query(stimulator_id: str, element_ids: Sequence[str]) -> Any:
    """Query for the stimulus_response documents of STIMULATOR_ID and ELEMENT_IDS.

    One query, built as an OR over the elements and ANDed onto the
    stimulator, so the caller makes a single database search for the whole
    set rather than one per element.

    With no element ids the query is the stimulator's responses alone --
    MATLAB's behaviour when the element list is empty, and what
    :meth:`stimulusResponse.existing_response_element_ids` asks for.
    """
    from ...query import ndi_query

    base = ndi_query("", "isa", "stimulus_response", "") & ndi_query(
        "", "depends_on", "stimulator_id", str(stimulator_id)
    )
    element_q = None
    for element_id in element_ids:
        one = ndi_query("", "depends_on", "element_id", str(element_id))
        element_q = one if element_q is None else element_q | one
    return base if element_q is None else base & element_q


def elements_to_compute(elements: Sequence[Any], existing_ids: Sequence[str]) -> list[bool]:
    """Which of ELEMENTS still need responses, given EXISTING_IDS.

    True for an element whose id is not among the ids that already have a
    stimulus_response document for the chosen stimulator. An element whose id
    cannot be read is computed rather than skipped: skipping it would leave a
    gap no message mentions, while computing it produces at worst a
    duplicate the user can see.
    """
    known = {str(existing) for existing in existing_ids}
    todo = []
    for element in elements:
        try:
            element_id = str(identifier(element))
        except Exception:  # noqa: BLE001 - an element that will not identify itself
            element_id = ""
        todo.append(element_id not in known)
    return todo


def summary_message(computed: int, skipped: int, failed: int, *, unported: bool = False) -> str:
    """What the user is told when the run finishes.

    MATLAB's two sentences, plus a third when the failures were the unported
    computation. A user who sees "0 computed, 3 failed" and is pointed at the
    command window learns nothing there in this port -- the warnings all say
    NotImplementedError -- so the reason is said here instead.
    """
    message = f"Computed responses for {computed} element(s); skipped {skipped} already done."
    if failed > 0:
        message += f" {failed} element(s) failed - see the command window."
        if unported:
            message += UNPORTED_NOTE
    return message


class stimulusResponse(SessionApp):  # noqa: N801 - MATLAB class name, per AGENTS.md §3
    """The "Compute Stimulus Responses" window for a session.

    Constructed with the session, as every session app is::

        app = ndi.gui.app.stimulusResponse(session)

    ``build=False`` makes the object without a window, which is how the run
    path is exercised in the tests and how a caller can drive it headlessly.
    """

    Name = "Stimulus Response"
    Category = "Stimulus"

    def __init__(
        self,
        session: Any,
        *,
        position: tuple[float, float, float, float] = DEFAULT_POSITION,
        build: bool = True,
    ):
        self.session = session
        self.position = tuple(position)

        #: The session's stimulator probes, as last loaded.
        self.stimulators: list[Any] = []
        #: Index into :attr:`stimulators` of the chosen probe, or None.
        self.probe_index: int | None = None
        #: The element types to compute on. Everything, as MATLAB starts.
        self.element_types: list[str] = list(ELEMENT_TYPES)
        #: "Replace existing responses".
        self.replace: bool = False
        #: The last message shown, as ``(message, title)`` -- what a headless
        #: caller reads instead of the dialog.
        self.last_alert: tuple[str, str] | None = None

        self.figure: Any = None
        self.probe_dropdown: Any = None
        self.type_list: Any = None
        self.replace_checkbox: Any = None
        self.run_button: Any = None
        self._held: list[Any] = []

        if build:
            self.build()
            self.show()
        self.reload_probes()

    # ------------------------------------------------------------------
    # selection
    # ------------------------------------------------------------------
    def selected_probe(self) -> Any:
        """The chosen stimulator probe, or None."""
        if self.probe_index is None:
            return None
        if not (0 <= self.probe_index < len(self.stimulators)):
            return None
        return self.stimulators[self.probe_index]

    def selected_types(self) -> list[str]:
        """The element types currently selected."""
        return list(self.element_types)

    def update_button_state(self) -> bool:
        """Enable Run when a probe is chosen and a type is selected.

        Returns the state it set, so the rule is checkable without a widget.
        """
        ok = self.selected_probe() is not None and bool(self.selected_types())
        if self.run_button is not None:
            self.run_button.setEnabled(ok)
        return ok

    def session_path(self) -> str:
        """The session's path for the subtitle, "" when it has none.

        Best-effort, as MATLAB's is: a session that cannot say where it lives
        costs the subtitle a path, not the window.
        """
        try:
            path = self.session.getpath()
        except Exception:  # noqa: BLE001 - not every session knows a path
            path = getattr(self.session, "path", "")
        return str(path or "")

    # ------------------------------------------------------------------
    # data loading
    # ------------------------------------------------------------------
    def reload_probes(self) -> list[Any]:
        """Re-read the session's stimulator probes and refill the dropdown.

        A session that cannot be read yields no probes rather than raising:
        Reload is the button a user presses when something looked wrong, and
        it must not be the thing that takes the window down.
        """
        try:
            stimulators = self.session.getprobes(type="stimulator")
        except Exception:  # noqa: BLE001 - an unreadable session has no probes
            stimulators = []
        self.stimulators = list(stimulators or [])
        self.probe_index = 0 if self.stimulators else None
        self._refill_probe_dropdown()
        self.update_button_state()
        return self.stimulators

    def elements_of_types(self, types: Sequence[str]) -> tuple[list[Any], list[str]]:
        """The session's elements of TYPES, and each one's type.

        Two parallel lists rather than pairs, matching MATLAB's ``[elems,
        elemTypes]``: the type is only ever wanted to name an element in a
        warning, and pairing them would have every other use unpack a tuple
        for nothing.
        """
        elements: list[Any] = []
        element_types: list[str] = []
        for element_type in types:
            try:
                found = self.session.getelements(**{"element.type": element_type})
            except Exception:  # noqa: BLE001 - a type nothing can be found for
                found = []
            for element in found or []:
                elements.append(element)
                element_types.append(element_type)
        return elements, element_types

    def existing_response_element_ids(self, probe: Any) -> list[str]:
        """Ids of the elements that already have a response for PROBE.

        One search, and the element ids read off the documents it returns --
        which is why the skip path costs one query and not one per element.
        """
        try:
            docs = self.session.database_search(response_query(identifier(probe), []))
        except Exception:  # noqa: BLE001 - an unsearchable database has no responses
            docs = []
        ids: list[str] = []
        for doc in docs or []:
            try:
                element_id = doc.dependency_value("element_id", error_if_not_found=False)
            except Exception:  # noqa: BLE001 - a document with no such dependency
                element_id = None
            if element_id and str(element_id) not in ids:
                ids.append(str(element_id))
        return ids

    def remove_existing_responses(self, probe: Any, elements: Sequence[Any]) -> int:
        """Delete the responses of PROBE and ELEMENTS. Returns the count.

        The scalar-parameter document each response depends on is removed
        with it. Leaving those behind would orphan them: nothing points at a
        parameter document except the response that was just deleted, so they
        would accumulate silently every time a user rebuilt responses.
        """
        element_ids = []
        for element in elements:
            try:
                element_ids.append(str(identifier(element)))
            except Exception:  # noqa: BLE001 - an element that will not identify itself
                continue
        try:
            docs = self.session.database_search(response_query(identifier(probe), element_ids))
        except Exception:  # noqa: BLE001 - an unsearchable database has nothing to remove
            docs = []
        docs = list(docs or [])
        if not docs:
            return 0

        from ...query import ndi_query

        parameter_docs: list[Any] = []
        for doc in docs:
            try:
                parameter_id = doc.dependency_value(
                    "stimulus_response_scalar_parameters_id", error_if_not_found=False
                )
            except Exception:  # noqa: BLE001 - a response with no parameters
                parameter_id = None
            if not parameter_id:
                continue
            try:
                parameter_docs.extend(
                    self.session.database_search(
                        ndi_query("base.id", "exact_string", str(parameter_id), "")
                    )
                    or []
                )
            except Exception:  # noqa: BLE001 - a parameter document that cannot be found
                continue

        self.session.database_rm(docs)
        if parameter_docs:
            self.session.database_rm(parameter_docs)
        return len(docs)

    # ------------------------------------------------------------------
    # the run
    # ------------------------------------------------------------------
    def run_responses(self) -> RunResult:
        """Compute the responses for the current selection.

        The whole of the app's behaviour; see the module docstring for why
        each path searches the database exactly once.
        """
        probe = self.selected_probe()
        types = self.selected_types()
        if probe is None or not types:
            self.alert(NOTHING_SELECTED, "Nothing selected")
            return RunResult(0, 0, 0, NOTHING_SELECTED)

        elements, element_types = self.elements_of_types(types)
        if not elements:
            self.alert(NO_ELEMENTS, "No elements")
            return RunResult(0, 0, 0, NO_ELEMENTS)

        if self.run_button is not None:
            self.run_button.setEnabled(False)
        try:
            return self._compute(probe, elements, element_types)
        finally:
            self.finish_run()

    def _compute(
        self, probe: Any, elements: Sequence[Any], element_types: Sequence[str]
    ) -> RunResult:
        if self.replace:
            # The documents are gone before anything is recomputed, so the
            # loop below never has to reason about what it is replacing.
            self.remove_existing_responses(probe, elements)
            todo = [True] * len(elements)
        else:
            todo = elements_to_compute(elements, self.existing_response_element_ids(probe))

        n_todo = sum(todo)
        skipped = len(elements) - n_todo
        if n_todo == 0:
            self.alert(NOTHING_TO_DO, "Nothing to do")
            return RunResult(0, skipped, 0, NOTHING_TO_DO)

        from ...app.stimulus.tuning_response import ndi_app_stimulus_tuning__response

        responder = ndi_app_stimulus_tuning__response(self.session)

        tag = f"stimresp_{identifier(probe)}"
        bar = make_progress_bar(
            "Stimulus Response", f"Computing responses ({n_todo} element(s))", tag
        )

        computed = 0
        failed = 0
        unported = False
        done = 0
        for element, element_type, wanted in zip(elements, element_types, todo, strict=True):
            if not wanted:
                continue
            try:
                responder.stimulus_responses(probe, element, False)
                computed += 1
            except NotImplementedError as exc:
                unported = True
                failed += 1
                _warn_failure(element, element_type, exc)
            except Exception as exc:  # noqa: BLE001 - one element must not stop the rest
                failed += 1
                _warn_failure(element, element_type, exc)
            done += 1
            update_progress_bar(bar, tag, done / n_todo)
        close_progress_bar(bar, tag)

        message = summary_message(computed, skipped, failed, unported=unported)
        self.alert(
            message,
            "Done with errors" if failed else "Done",
            success=failed == 0,
        )
        return RunResult(computed, skipped, failed, message)

    def finish_run(self) -> None:
        """Restore the Run button after a run, however it ended."""
        self.update_button_state()

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build(self) -> Any:
        from .._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtCore, QtWidgets

        from ..cloud_colors import cloud_colors, rgb_to_hex

        c = cloud_colors()
        navy = rgb_to_hex(c.dark_blue)
        white = rgb_to_hex(c.white)
        x, y, w, h = self.position

        self.figure = QtWidgets.QWidget()
        self.figure.setWindowTitle(f"Stimulus Response: {self.session.reference}")
        self.figure.setObjectName(WINDOW_TAG)
        self.figure.setGeometry(int(x), int(y), int(w), int(h))
        self.figure.setStyleSheet(f"background-color: {navy}; color: {white};")

        root = QtWidgets.QVBoxLayout(self.figure)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QtWidgets.QLabel("Compute Stimulus Responses")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {white}; font-size: 16px; font-weight: bold;")
        root.addWidget(title)

        subtitle = QtWidgets.QLabel(
            f"Session: {self.session.reference}    Path: {self.session_path()}"
        )
        subtitle.setStyleSheet(f"color: {white};")
        root.addWidget(subtitle)

        probe_row = QtWidgets.QHBoxLayout()
        probe_row.setSpacing(8)
        probe_label = QtWidgets.QLabel("Stimulator:")
        probe_label.setStyleSheet(f"color: {white}; font-weight: bold;")
        probe_row.addWidget(probe_label)
        self.probe_dropdown = QtWidgets.QComboBox()
        self.probe_dropdown.setStyleSheet(f"background-color: {white}; color: {navy};")
        self.probe_dropdown.currentIndexChanged.connect(self._on_probe_changed)
        probe_row.addWidget(self.probe_dropdown, 1)
        reload_button = QtWidgets.QPushButton("Reload")
        reload_button.setStyleSheet(f"background-color: {white}; color: {navy};")
        reload_button.clicked.connect(self.reload_probes)
        probe_row.addWidget(reload_button)
        root.addLayout(probe_row)

        types_header = QtWidgets.QLabel("Element types to compute on:")
        types_header.setStyleSheet(f"color: {white}; font-weight: bold;")
        root.addWidget(types_header)

        self.type_list = QtWidgets.QListWidget()
        self.type_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.type_list.setStyleSheet(f"background-color: {white}; color: {navy};")
        for element_type in ELEMENT_TYPES:
            self.type_list.addItem(element_type)
        self.type_list.selectAll()  # MATLAB opens with every type selected
        self.type_list.itemSelectionChanged.connect(self._on_types_changed)
        root.addWidget(self.type_list, 1)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setSpacing(12)
        self.replace_checkbox = QtWidgets.QCheckBox("Replace existing responses")
        # The indicator is painted explicitly: Qt's default is a dark box,
        # which on this navy background is a tickbox a user cannot see.
        self.replace_checkbox.setStyleSheet(
            f"QCheckBox {{ color: {white}; }}"
            f"QCheckBox::indicator {{ width: 13px; height: 13px;"
            f" background-color: {white}; border: 1px solid {white}; }}"
            f"QCheckBox::indicator:checked {{ background-color: {rgb_to_hex(c.light_blue)}; }}"
        )
        self.replace_checkbox.setToolTip(
            "Remove and rebuild every stimulus_response document for the chosen "
            "stimulator and element type(s); otherwise only elements without an "
            "existing response are computed"
        )
        self.replace_checkbox.toggled.connect(self._on_replace_toggled)
        button_row.addWidget(self.replace_checkbox)
        button_row.addStretch(1)
        self.run_button = QtWidgets.QPushButton("Compute responses")
        self.run_button.setStyleSheet(
            f"background-color: {rgb_to_hex(c.light_blue)}; color: {navy}; font-weight: bold;"
        )
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self.run_responses)
        button_row.addWidget(self.run_button)
        root.addLayout(button_row)

        return self.figure

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def close(self) -> None:
        if self.figure is not None:
            self.figure.close()

    def _refill_probe_dropdown(self) -> None:
        """Repopulate the dropdown from :attr:`stimulators`.

        The signal is blocked while the items change: refilling emits an
        index change, and letting that through would have a reload look like
        a user's choice and reset the selection under them.
        """
        if self.probe_dropdown is None:
            return
        self.probe_dropdown.blockSignals(True)
        try:
            self.probe_dropdown.clear()
            if self.stimulators:
                self.probe_dropdown.addItems(probe_labels(self.stimulators))
                self.probe_dropdown.setCurrentIndex(0)
            else:
                self.probe_dropdown.addItem(NO_STIMULATORS)
                self.probe_dropdown.setCurrentIndex(-1)
        finally:
            self.probe_dropdown.blockSignals(False)

    def _on_probe_changed(self, index: int) -> None:
        self.probe_index = index if index >= 0 else None
        self.update_button_state()

    def _on_types_changed(self) -> None:
        self.element_types = [item.text() for item in self.type_list.selectedItems()]
        self.update_button_state()

    def _on_replace_toggled(self, checked: bool) -> None:
        self.replace = bool(checked)

    def alert(self, message: str, title: str, *, success: bool = False) -> Any:
        """Show a message, and record it as :attr:`last_alert`.

        Non-blocking, as the navigator's and the profile editor's alerts are.
        With no window there is nothing to show and the record is the whole
        of it, which is what makes the run path checkable headlessly.
        """
        self.last_alert = (message, title)
        if self.figure is None:
            return None
        from PySide6 import QtWidgets

        box = QtWidgets.QMessageBox(self.figure)
        box.setWindowTitle(title)
        box.setText(message)
        box.setIcon(
            QtWidgets.QMessageBox.Icon.Information
            if success
            else QtWidgets.QMessageBox.Icon.Warning
        )
        box.show()
        self._held.append(box)
        box.finished.connect(lambda _=0, b=box: self._held.remove(b) if b in self._held else None)
        return box

    def __repr__(self) -> str:
        return f"stimulusResponse(stimulators={len(self.stimulators)})"


# ----------------------------------------------------------------------
# module helpers: the progress bar, and the warning a failed element gets
# ----------------------------------------------------------------------
def make_progress_bar(title: str, label: str, tag: str) -> Any:
    """An NDI progress bar with one bar, or None if one cannot be made.

    MATLAB's ``i_makeBar``, and swallowing for the same reason: a run that
    cannot draw a progress bar is still a run worth finishing. In this port
    that is not hypothetical -- the toolkit may be absent on a headless box,
    and every caller here is prepared for None.
    """
    try:
        from ..component.ProgressBarWindow import ndi_gui_component_ProgressBarWindow

        bar = ndi_gui_component_ProgressBarWindow(title)
        bar.addBar(Label=label, Tag=tag, Auto=False)
        return bar
    except Exception:  # noqa: BLE001 - no toolkit, no display, no progress bar
        return None


def update_progress_bar(bar: Any, tag: str, fraction: float) -> None:
    """Move BAR to FRACTION, clamped to 0..1. MATLAB's ``i_updateBar``."""
    if bar is None:
        return
    try:
        bar.updateBar(tag, max(0.0, min(1.0, float(fraction))))
    except Exception:  # noqa: BLE001 - a bar that has gone away
        pass


def close_progress_bar(bar: Any, tag: str) -> None:
    """Remove BAR's row. MATLAB's ``i_closeBar``."""
    if bar is None:
        return
    try:
        bar.removeBar(tag)
    except Exception:  # noqa: BLE001 - a bar that has gone away
        pass


def _warn_failure(element: Any, element_type: str, exc: BaseException) -> None:
    """Report one element's failure, naming it as MATLAB's warning does."""
    try:
        label = str(element.elementstring())
    except Exception:  # noqa: BLE001 - an element that will not name itself
        label = repr(element)
    warnings.warn(
        f"ndi.gui.app.stimulusResponse: could not compute responses for "
        f"{label} ({element_type}): {exc}",
        stacklevel=2,
    )
