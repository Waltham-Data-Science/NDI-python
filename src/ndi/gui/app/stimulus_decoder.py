"""ndi.gui.app.stimulus_decoder - run the stimulus decoder over a probe's epochs.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/stimulusDecoder.m``

A window over one stimulator probe of a session: its epochs on the left,
what the stimuli in the selected epochs vary and hold constant on the
right, and two buttons that write the documents everything downstream
needs. "Run decoder" writes the ``stimulus_presentation`` documents
(:meth:`ndi.app.stimulus.decoder.parse_stimuli`); "Label Control Stims"
writes the ``control_stimulus_ids`` documents
(:meth:`ndi.app.stimulus.tuning_response.label_control_stimuli`) that the
stimulus-response tools need on top of them.

WHAT THE MARKERS MEAN, AND WHY THERE ARE TWO
An epoch's row is prefixed ``*`` once it has been decoded and ``*c`` once
its control stimuli have been labeled as well. They are separate steps
producing separate documents, and a session that has had the first done but
not the second looks fully decoded to anyone who only checks for
``stimulus_presentation``. Showing both states is what stops that reading.

DECODING IS SKIPPED, NOT REDONE
An epoch that already has a ``stimulus_presentation`` is left alone, so
pressing "Run decoder" over a part-decoded probe costs nothing for the
epochs already done. "Re-decode selected (overwrite)" is the opt-in for the
other case -- the stimulus record was wrong and has to be rebuilt -- and it
removes only the SELECTED epochs' documents, never the probe's whole set.

WHAT IS QT AND WHAT IS NOT
Every rule the window applies -- an epoch's marker, which documents belong
to a selection, when each button is live, what the "varies" and "constant"
panels say, and the wording of each refusal -- is plain Python here and
tested with no display, the split :mod:`ndi.gui.preferences_editor` and
:mod:`ndi.gui.app.electrode_data_export` make. A panel showing another
epoch's stimulus parameters does not raise; it just tells a user something
untrue about their experiment.

DEVIATIONS FROM MATLAB
* MATLAB's ``uilistbox``/``uidropdown`` carry ``ItemsData``, so their
  ``Value`` is already the epoch id or probe index. Qt has no such field, so
  the row numbers are read back and mapped through :attr:`epoch_ids` and
  :attr:`stimulators`, which are kept in list order for exactly that.
* MATLAB's ``uiprogressdlg`` is modal and indeterminate. Qt's equivalent
  would need an event loop of its own to stay responsive, so the wait is
  shown as a disabled window with a status line instead: the same "this is
  working, do not press again" signal without a second loop.
"""

from __future__ import annotations

from typing import Any, ClassVar

from .session_app import SessionApp

__all__ = [
    "stimulusDecoder",
    "StimulusDecoder",
    "DEFAULT_POSITION",
    "WINDOW_TAG",
    "PROBE_TYPE",
    "NO_STIMULATORS",
    "NO_EPOCHS",
    "SELECT_EPOCHS_MESSAGE",
    "NOT_DECODED_MESSAGE",
    "epoch_marker",
    "epoch_item",
    "value_to_text",
    "varies_lines",
    "constant_rows",
]

#: Where the window opens, ``(x, y, width, height)``, as MATLAB positions it.
DEFAULT_POSITION: tuple[float, float, float, float] = (100, 100, 880, 540)

#: The window's object name, MATLAB's figure Tag.
WINDOW_TAG = "ndi.gui.app.stimulusDecoder"

#: The probe type this app decodes.
PROBE_TYPE = "stimulator"

#: Dropdown text when the session has no stimulator probes at all.
NO_STIMULATORS = "(no stimulator probes)"

#: List text when the chosen probe has no epochs.
NO_EPOCHS = "(no stimulus epochs)"

#: Panel text before anything is selected.
SELECT_EPOCHS_MESSAGE = "(select one or more epochs)"

#: Panel text when the selection has not been decoded yet.
NOT_DECODED_MESSAGE = "(no stimulus_presentation for the selected epoch(s) - run the decoder first)"


def epoch_marker(decoded: bool, control_labeled: bool) -> str:
    """The two-character prefix for an epoch's row.

    ``"*c"`` decoded and control stimuli labeled, ``"* "`` decoded only,
    ``"  "`` neither. Fixed width so the ids below each other line up: a
    ragged left edge makes a long list unreadable, which is the whole reason
    the list is in a fixed-width font.
    """
    if not decoded:
        return "  "
    return "*c" if control_labeled else "* "


def epoch_item(epoch_id: str, decoded: bool, control_labeled: bool) -> str:
    """One row of the epoch list: its marker, then the epoch id."""
    return f"{epoch_marker(decoded, control_labeled)} {epoch_id}"


def value_to_text(value: Any) -> str:
    """A compact one-line rendering of a stimulus parameter value.

    MATLAB's ``valueToText``, which uses ``mat2str`` for numeric and logical
    values and formats cells and strings element by element. The shapes come
    from :func:`ndi.fun.stimulus.whatVaries`, so this has to handle a bare
    scalar, a list of the distinct values a parameter takes, and the nested
    lists a structured parameter can hold.
    """
    import numpy as np

    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, np.integer, np.floating)):
        return _number_to_text(value)
    if isinstance(value, np.ndarray):
        return value_to_text(value.tolist())
    if isinstance(value, (list, tuple)):
        parts = [value_to_text(v) for v in value]
        if all(isinstance(v, (int, float, bool, np.integer, np.floating, np.bool_)) for v in value):
            # MATLAB's mat2str of a numeric row vector.
            return "[" + " ".join(parts) + "]"
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {value_to_text(v)}" for k, v in value.items()) + "}"
    if value is None:
        return ""
    return f"<{type(value).__name__}>"


def _number_to_text(value: Any) -> str:
    """A number without a trailing ``.0`` where it carries no information."""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def varies_lines(varies: list[dict[str, Any]]) -> list[str]:
    """The "What varies" panel's lines: one ``name = <values>`` per parameter."""
    if not varies:
        return ["(nothing varies across these stimuli)"]
    return [
        f"{entry.get('parameter', '')} = {value_to_text(entry.get('values'))}" for entry in varies
    ]


def constant_rows(constant: list[dict[str, Any]]) -> list[list[str]]:
    """The "What is constant" table's rows, ``[parameter, value]`` each."""
    return [
        [str(entry.get("parameter", "")), value_to_text(entry.get("value"))] for entry in constant
    ]


class stimulusDecoder(SessionApp):  # noqa: N801 (MATLAB class name)
    """Drive :class:`ndi.app.stimulus.decoder` over a session's stimulus epochs.

    ``stimulusDecoder(session)`` opens the window, which is the whole
    contract :class:`~ndi.gui.app.SessionApp` asks of an app.

    MATLAB equivalent: ``ndi.gui.app.stimulusDecoder``.
    """

    #: The Apps-menu label. Verbatim from MATLAB: it is user-visible text.
    Name: ClassVar[str] = "Stimulus Decoder"

    #: Groups the app under a "Stimulus" submenu, as MATLAB groups it.
    Category: ClassVar[str] = "Stimulus"

    def __init__(
        self,
        session: Any,
        *,
        position: tuple[float, float, float, float] = DEFAULT_POSITION,
        build: bool = True,
    ):
        self.session = session
        self.position = tuple(position)

        #: The session's stimulator probes, in dropdown order.
        self.stimulators: list[Any] = []
        #: Epoch ids of the chosen probe, in list order.
        self.epoch_ids: list[str] = []
        #: Epoch ids that already have a stimulus_presentation.
        self.decoded_epochs: list[str] = []
        #: Those epochs' documents, parallel to :attr:`decoded_epochs`.
        self.pres_docs: list[Any] = []
        #: Epoch ids that already have a control_stimulus_ids.
        self.control_labeled_epochs: list[str] = []

        self.figure: Any = None
        self.probe_dropdown: Any = None
        self.epoch_list: Any = None
        self.varies_text: Any = None
        self.constant_table: Any = None
        self.overwrite_checkbox: Any = None
        self.run_button: Any = None
        self.control_button: Any = None
        self.status_label: Any = None
        self._held: list[Any] = []

        if build:
            self.build()
            # The first database reads -- probes, epochs, documents -- can
            # take a moment on a large session, so they happen behind the
            # same wait indicator the Reload button uses.
            self.with_wait("Loading stimulator probes...", self.reload_probes)

    # ------------------------------------------------------------------
    # model: probes
    # ------------------------------------------------------------------
    def session_path(self) -> str:
        """The session's path, for the subtitle. "" when it will not say."""
        try:
            getpath = getattr(self.session, "getpath", None)
            if callable(getpath):
                return str(getpath())
            return str(getattr(self.session, "path", "") or "")
        except Exception:  # noqa: BLE001 - a path is decoration, never a failure
            return ""

    def load_stimulators(self) -> list[Any]:
        """Collect the session's stimulator probes.

        A session that cannot answer lists none rather than raising, as
        MATLAB's try/catch does: an app that opens empty says more than one
        that will not open.
        """
        try:
            probes = self.session.getprobes(type=PROBE_TYPE)
        except Exception:  # noqa: BLE001 - an unreadable session lists nothing
            probes = []
        self.stimulators = list(probes) if probes else []
        return self.stimulators

    def probe_labels(self) -> list[str]:
        """The dropdown's items: one element string per stimulator."""
        return [str(probe.elementstring()) for probe in self.stimulators]

    def selected_probe(self) -> Any | None:
        """The stimulator the dropdown is showing, or None."""
        if self.probe_dropdown is None:
            return self.stimulators[0] if self.stimulators else None
        index = self.probe_dropdown.currentIndex()
        if 0 <= index < len(self.stimulators):
            return self.stimulators[index]
        return None

    # ------------------------------------------------------------------
    # model: epochs and their documents
    # ------------------------------------------------------------------
    def load_epochs(self, probe: Any) -> list[str]:
        """The probe's epoch ids, in epoch-table order. Raises as the probe does."""
        result = probe.epochtable()
        et = result[0] if isinstance(result, tuple) else result
        return [entry.get("epoch_id") for entry in (et or []) if entry.get("epoch_id")]

    def decoded_epoch_ids(self, probe: Any) -> list[str]:
        """Epoch ids that already have a stimulus_presentation for PROBE.

        ONE database search, and the documents are cached in
        :attr:`pres_docs` (parallel to the returned ids) so the "what varies
        / what is constant" panels can be filled on every selection change
        without going back to the database each time.
        """
        from ...fun.utils import identifier
        from ...query import ndi_query

        ids: list[str] = []
        self.pres_docs = []
        try:
            docs = self.session.database_search(
                ndi_query("").isa("stimulus_presentation")
                & ndi_query("").depends_on("stimulus_element_id", identifier(probe))
            )
        except Exception:  # noqa: BLE001 - an unreadable database means nothing decoded
            docs = []

        for doc in docs:
            try:
                epoch_id = doc.document_properties["epochid"]["epochid"]
            except Exception:  # noqa: BLE001 - a document with no readable epoch
                continue
            if epoch_id not in ids:
                ids.append(epoch_id)
                self.pres_docs.append(doc)
        return ids

    def control_labeled_epoch_ids(self, probe: Any) -> list[str]:
        """Epoch ids whose control stimuli have already been labeled.

        A ``control_stimulus_ids`` document depends on a
        ``stimulus_presentation``, not on the probe, so there is no query
        that reaches the epochs directly. The route back is through the
        presentation documents cached by :meth:`decoded_epoch_ids` -- which
        is also what keeps this to one further search rather than one per
        epoch.
        """
        from ...fun.utils import identifier
        from ...query import ndi_query

        if not self.pres_docs:
            return []  # nothing decoded, so nothing can be labeled

        pres_to_epoch: dict[str, str] = {}
        for doc, epoch_id in zip(self.pres_docs, self.decoded_epochs):
            try:
                pres_to_epoch[identifier(doc)] = epoch_id
            except Exception:  # noqa: BLE001 - unreadable id: skip
                continue

        try:
            docs = self.session.database_search(ndi_query("").isa("control_stimulus_ids"))
        except Exception:  # noqa: BLE001 - unreadable database means nothing labeled
            docs = []

        ids: list[str] = []
        for doc in docs:
            try:
                pres_id = doc.dependency_value("stimulus_presentation_id")
            except Exception:  # noqa: BLE001 - no readable dependency: skip
                continue
            epoch_id = pres_to_epoch.get(pres_id)
            if epoch_id is not None and epoch_id not in ids:
                ids.append(epoch_id)
        return ids

    def pres_docs_for_epochs(self, epoch_ids: list[str]) -> list[Any]:
        """The cached stimulus_presentation documents of EPOCH_IDS."""
        wanted = set(epoch_ids)
        return [
            doc for doc, epoch_id in zip(self.pres_docs, self.decoded_epochs) if epoch_id in wanted
        ]

    def epoch_items(self) -> list[str]:
        """One row per epoch, marked with what has been done to it."""
        decoded = set(self.decoded_epochs)
        labeled = set(self.control_labeled_epochs)
        return [
            epoch_item(epoch_id, epoch_id in decoded, epoch_id in labeled)
            for epoch_id in self.epoch_ids
        ]

    def selected_epoch_ids(self) -> list[str]:
        """The epoch ids selected in the list, in list order.

        MATLAB reads these off the listbox's ItemsData; Qt has no such
        field, so the selected ROWS index :attr:`epoch_ids` -- which holds
        because :meth:`reload_epochs` fills the list in that order, and is
        empty when the list holds only a placeholder.
        """
        if self.epoch_list is None or not self.epoch_ids:
            return []
        rows = sorted(index.row() for index in self.epoch_list.selectedIndexes())
        return [self.epoch_ids[row] for row in rows if 0 <= row < len(self.epoch_ids)]

    # ------------------------------------------------------------------
    # model: what the buttons may do
    # ------------------------------------------------------------------
    def can_run_decoder(self) -> bool:
        """True when a probe is chosen and at least one epoch is selected."""
        return self.selected_probe() is not None and bool(self.selected_epoch_ids())

    def can_label_controls(self) -> bool:
        """True when a probe is chosen and it has at least one decoded epoch.

        Not "and an epoch is selected": labeling has no per-epoch filter, so
        it operates on all of the probe's decoded epochs and a selection
        would misrepresent what the button does.
        """
        return self.selected_probe() is not None and bool(self.decoded_epochs)

    def decode_refusal(self, selection: list[str], overwrite: bool) -> str:
        """Why "Run decoder" would do nothing, or "" when it would do something.

        Pressing a button and seeing nothing happen reads as a broken app.
        Every selected epoch already being decoded is the common way to get
        there, and it has a fix the user can act on, so it is said rather
        than shown as silence.
        """
        if not selection:
            return "Choose a stimulator probe and select one or more epochs."
        if overwrite:
            return ""
        already = [epoch_id for epoch_id in selection if epoch_id in set(self.decoded_epochs)]
        if len(already) == len(selection):
            return (
                "Every selected epoch already has a stimulus_presentation document. "
                'Tick "Re-decode selected (overwrite)" to rebuild them.'
            )
        return ""

    def label_refusal(self, overwrite: bool) -> str:
        """Why "Label Control Stims" would do nothing, or "" when it would not."""
        if self.selected_probe() is None:
            return "Choose a stimulator probe."
        if not self.decoded_epochs:
            return (
                "This probe has no decoded epochs. Run the decoder first, then label "
                "the control stimuli."
            )
        if overwrite:
            return ""
        labeled = set(self.control_labeled_epochs)
        if all(epoch_id in labeled for epoch_id in self.decoded_epochs):
            return (
                "Every decoded epoch already has its control stimuli labeled. "
                'Tick "Re-decode selected (overwrite)" to rebuild them.'
            )
        return ""

    def overwrite(self) -> bool:
        """Whether the overwrite box is ticked."""
        return bool(self.overwrite_checkbox is not None and self.overwrite_checkbox.isChecked())

    # ------------------------------------------------------------------
    # model: the stimulus-parameter panels
    # ------------------------------------------------------------------
    def stimulus_info(self, selection: list[str]) -> tuple[list[str], list[list[str]]]:
        """The two panels' contents for SELECTION: ``(varies_lines, rows)``.

        A message rather than empty panels whenever there is nothing to
        report, because an empty "what varies" panel and a panel for an
        undecoded epoch look identical and mean opposite things.
        """
        if not selection:
            return [SELECT_EPOCHS_MESSAGE], []

        docs = self.pres_docs_for_epochs(selection)
        if not docs:
            return [NOT_DECODED_MESSAGE], []

        from ...fun.stimulus import whatVaries

        try:
            varies, constant = whatVaries(docs)
        except Exception as exc:  # noqa: BLE001 - reported in the panel, not raised
            return [f"(could not read stimuli: {exc})"], []

        return varies_lines(varies), constant_rows(constant)

    # ------------------------------------------------------------------
    # the window
    # ------------------------------------------------------------------
    def build(self) -> Any:
        from .._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtCore, QtGui, QtWidgets

        from ..cloud_colors import cloud_colors, rgb_to_hex

        c = cloud_colors()
        x, y, w, h = self.position
        navy = rgb_to_hex(c.dark_blue)
        white = rgb_to_hex(c.white)
        light = rgb_to_hex(c.light_blue)
        on_white = f"background-color: {white}; color: {navy};"

        self.figure = QtWidgets.QWidget()
        self.figure.setWindowTitle(f"Stimulus Decoder: {self.session.reference}")
        self.figure.setObjectName(WINDOW_TAG)
        self.figure.setGeometry(int(x), int(y), int(w), int(h))
        self.figure.setStyleSheet(f"background-color: {navy};")

        root = QtWidgets.QVBoxLayout(self.figure)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QtWidgets.QLabel("Run Stimulus Decoder")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {white}; font-size: 16px; font-weight: bold;")
        title.setFixedHeight(30)
        root.addWidget(title)

        subtitle = QtWidgets.QLabel(
            f"Session: {self.session.reference}    Path: {self.session_path()}"
        )
        subtitle.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {white};")
        subtitle.setFixedHeight(20)
        root.addWidget(subtitle)

        # stimulator selector + reload
        prow = QtWidgets.QHBoxLayout()
        prow.setSpacing(8)
        probe_label = QtWidgets.QLabel("Stimulator:")
        probe_label.setStyleSheet(f"color: {white}; font-weight: bold;")
        probe_label.setFixedWidth(90)
        probe_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        prow.addWidget(probe_label)

        self.probe_dropdown = QtWidgets.QComboBox()
        self.probe_dropdown.setStyleSheet(on_white)
        self.probe_dropdown.currentIndexChanged.connect(self.on_probe_changed)
        prow.addWidget(self.probe_dropdown, 1)

        reload_button = QtWidgets.QPushButton("Reload")
        reload_button.setFixedWidth(90)
        reload_button.setStyleSheet(on_white)
        reload_button.clicked.connect(
            lambda: self.with_wait("Loading stimulator probes...", self.reload_probes)
        )
        prow.addWidget(reload_button)
        root.addLayout(prow)

        # headers over the two halves, sharing the 40/60 split below them
        hrow = QtWidgets.QHBoxLayout()
        hrow.setSpacing(8)
        left_header = QtWidgets.QLabel(
            "Stimulus epochs (* = decoded, *c = control stimuli labeled):"
        )
        left_header.setStyleSheet(f"color: {white}; font-weight: bold;")
        hrow.addWidget(left_header, 2)
        right_header = QtWidgets.QLabel("Stimulus parameters (selected epoch(s)):")
        right_header.setStyleSheet(f"color: {white}; font-weight: bold;")
        hrow.addWidget(right_header, 3)
        root.addLayout(hrow)

        srow = QtWidgets.QHBoxLayout()
        srow.setSpacing(8)

        fixed_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)

        self.epoch_list = QtWidgets.QListWidget()
        self.epoch_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.epoch_list.setFont(fixed_font)
        self.epoch_list.setStyleSheet(on_white)
        self.epoch_list.itemSelectionChanged.connect(self.on_epoch_selection_changed)
        srow.addWidget(self.epoch_list, 2)

        pcol = QtWidgets.QVBoxLayout()
        pcol.setSpacing(4)
        varies_label = QtWidgets.QLabel("What varies (among non-blank stimuli)")
        varies_label.setStyleSheet(f"color: {white}; font-weight: bold;")
        varies_label.setFixedHeight(18)
        pcol.addWidget(varies_label)

        self.varies_text = QtWidgets.QPlainTextEdit()
        self.varies_text.setReadOnly(True)
        self.varies_text.setFont(fixed_font)
        self.varies_text.setStyleSheet(on_white)
        pcol.addWidget(self.varies_text, 1)

        constant_label = QtWidgets.QLabel("What is constant (among non-blank stimuli)")
        constant_label.setStyleSheet(f"color: {white}; font-weight: bold;")
        constant_label.setFixedHeight(18)
        pcol.addWidget(constant_label)

        self.constant_table = QtWidgets.QTableWidget(0, 2)
        self.constant_table.setHorizontalHeaderLabels(["Parameter", "Value"])
        self.constant_table.verticalHeader().setVisible(False)
        self.constant_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.constant_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.constant_table.setStyleSheet(on_white)
        pcol.addWidget(self.constant_table, 1)

        srow.addLayout(pcol, 3)
        root.addLayout(srow, 1)

        # overwrite + the two action buttons
        brow = QtWidgets.QHBoxLayout()
        brow.setSpacing(12)
        self.overwrite_checkbox = QtWidgets.QCheckBox("Re-decode selected (overwrite)")
        self.overwrite_checkbox.setStyleSheet(f"color: {white};")
        self.overwrite_checkbox.setToolTip(
            "Remove and rebuild the stimulus_presentation documents of the selected "
            'epochs (and, for "Label Control Stims", the control_stimulus_ids '
            "documents), even if they already exist"
        )
        brow.addWidget(self.overwrite_checkbox)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet(f"color: {white};")
        brow.addWidget(self.status_label, 1)

        button_style = f"background-color: {light}; color: {navy}; font-weight: bold;"
        self.control_button = QtWidgets.QPushButton("Label Control Stims")
        self.control_button.setFixedWidth(170)
        self.control_button.setStyleSheet(button_style)
        self.control_button.setToolTip(
            "Label the control (blank) stimuli of the probe's decoded epochs, "
            "writing control_stimulus_ids documents"
        )
        self.control_button.setEnabled(False)
        self.control_button.clicked.connect(self.run_control_labels)
        brow.addWidget(self.control_button)

        self.run_button = QtWidgets.QPushButton("Run decoder")
        self.run_button.setFixedWidth(150)
        self.run_button.setStyleSheet(button_style)
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self.run_decoder)
        brow.addWidget(self.run_button)
        root.addLayout(brow)

        self.figure.show()
        return self.figure

    # ------------------------------------------------------------------
    # refreshing the window from the model
    # ------------------------------------------------------------------
    def reload_probes(self) -> list[str]:
        """Reload the stimulators and rebuild the dropdown; returns its items."""
        self.load_stimulators()
        labels = self.probe_labels()

        if self.probe_dropdown is None:
            return labels

        self.probe_dropdown.blockSignals(True)
        try:
            self.probe_dropdown.clear()
            self.probe_dropdown.addItems(labels or [NO_STIMULATORS])
            self.probe_dropdown.setEnabled(bool(labels))
        finally:
            self.probe_dropdown.blockSignals(False)

        if labels:
            self.reload_epochs()
        else:
            self.clear_epoch_list()
        return labels

    def on_probe_changed(self) -> None:
        self.with_wait("Loading epochs...", self.reload_epochs)

    def reload_epochs(self) -> list[str]:
        """Rebuild the epoch list for the chosen probe; returns its rows.

        The selection is kept BY EPOCH ID, not by row: the markers change as
        epochs are decoded, and after a reload to another probe the same row
        number means a different epoch entirely.
        """
        previous = self.selected_epoch_ids()
        probe = self.selected_probe()
        if probe is None:
            return self.clear_epoch_list()

        try:
            self.epoch_ids = self.load_epochs(probe)
        except Exception as exc:  # noqa: BLE001 - reported in the list, not raised
            self.epoch_ids = []
            self.decoded_epochs = []
            self.pres_docs = []
            self.control_labeled_epochs = []
            return self._set_epoch_rows([f"(could not read epochs: {exc})"], [])

        self.decoded_epochs = self.decoded_epoch_ids(probe)
        self.control_labeled_epochs = self.control_labeled_epoch_ids(probe)

        items = self.epoch_items()
        if not items:
            self.epoch_ids = []
            return self._set_epoch_rows([NO_EPOCHS], [])
        return self._set_epoch_rows(items, previous)

    def clear_epoch_list(self) -> list[str]:
        """Empty the list and everything read from it."""
        self.epoch_ids = []
        self.decoded_epochs = []
        self.pres_docs = []
        self.control_labeled_epochs = []
        return self._set_epoch_rows([], [])

    def _set_epoch_rows(self, rows: list[str], keep: list[str]) -> list[str]:
        """Fill the list widget with ROWS, reselecting the epochs in KEEP."""
        if self.epoch_list is None:
            self.update_button_state()
            self.update_stimulus_info()
            return rows

        from PySide6 import QtWidgets

        self.epoch_list.blockSignals(True)
        try:
            self.epoch_list.clear()
            for text in rows:
                self.epoch_list.addItem(QtWidgets.QListWidgetItem(text))
            wanted = set(keep)
            for index, epoch_id in enumerate(self.epoch_ids):
                if epoch_id in wanted and index < self.epoch_list.count():
                    self.epoch_list.item(index).setSelected(True)
        finally:
            self.epoch_list.blockSignals(False)

        self.update_button_state()
        self.update_stimulus_info()
        return rows

    def on_epoch_selection_changed(self) -> None:
        self.update_button_state()
        self.update_stimulus_info()

    def update_button_state(self) -> tuple[bool, bool]:
        """Set both buttons' enabled state; returns ``(run, label)``."""
        run = self.can_run_decoder()
        label = self.can_label_controls()
        if self.run_button is not None:
            self.run_button.setEnabled(run)
        if self.control_button is not None:
            self.control_button.setEnabled(label)
        return run, label

    def update_stimulus_info(self) -> tuple[list[str], list[list[str]]]:
        """Refill both parameter panels from the current selection."""
        lines, rows = self.stimulus_info(self.selected_epoch_ids())

        if self.varies_text is not None:
            self.varies_text.setPlainText("\n".join(lines))
        if self.constant_table is not None:
            from PySide6 import QtWidgets

            self.constant_table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for cidx, text in enumerate(row):
                    self.constant_table.setItem(r, cidx, QtWidgets.QTableWidgetItem(text))
        return lines, rows

    # ------------------------------------------------------------------
    # the two actions
    # ------------------------------------------------------------------
    def run_decoder(self) -> list[Any]:
        """Decode the selected epochs; returns the documents written."""
        probe = self.selected_probe()
        selection = self.selected_epoch_ids()
        overwrite = self.overwrite()

        refusal = self.decode_refusal(selection, overwrite)
        if probe is None or refusal:
            self.alert(
                refusal or "Choose a stimulator probe and select one or more epochs.",
                "Already decoded" if selection else "Nothing selected",
            )
            return []

        from ...app.stimulus.decoder import ndi_app_stimulus_decoder

        def work() -> list[Any]:
            decoder = ndi_app_stimulus_decoder(self.session)
            newdocs, _existing = decoder.parse_stimuli(probe, overwrite, selection)
            return list(newdocs)

        newdocs = self._run_guarded(
            work, f"Decoding {len(selection)} epoch(s)...", "Decoding failed"
        )
        if newdocs is None:
            return []

        self.reload_epochs()  # refresh the "*" markers
        self.alert(
            f"Decoded {len(selection)} epoch(s); wrote {len(newdocs)} document(s).",
            "Done",
            success=True,
        )
        return newdocs

    def run_control_labels(self) -> list[Any]:
        """Label the probe's control stimuli; returns the documents written."""
        probe = self.selected_probe()
        overwrite = self.overwrite()

        refusal = self.label_refusal(overwrite)
        if refusal:
            self.alert(
                refusal,
                (
                    "No probe selected"
                    if probe is None
                    else ("Nothing to label" if not self.decoded_epochs else "Already labeled")
                ),
            )
            return []

        from ...app.stimulus.tuning_response import ndi_app_stimulus_tuning__response

        def work() -> list[Any]:
            app = ndi_app_stimulus_tuning__response(self.session)
            return list(app.label_control_stimuli(probe, overwrite))

        cs_docs = self._run_guarded(work, "Labeling control stimuli...", "Labeling failed")
        if cs_docs is None:
            return []

        self.reload_epochs()  # refresh the "*c" markers
        self.alert(
            f"Labeled control stimuli; wrote {len(cs_docs)} control_stimulus_ids document(s).",
            "Done",
            success=True,
        )
        return cs_docs

    def _run_guarded(self, work: Any, message: str, failure_title: str) -> Any:
        """Run WORK behind the wait indicator; None when it raised.

        Both buttons go dead for the duration. These calls write documents
        and take as long as the recording is big, and a second press while
        the first is running would decode the same epochs twice.
        """
        self.set_busy(True, message)
        try:
            return work()
        except Exception as exc:  # noqa: BLE001 - reported in a dialog, not raised
            self.alert(str(exc), failure_title)
            return None
        finally:
            self.set_busy(False, "")
            self.update_button_state()

    # ------------------------------------------------------------------
    # waiting, and dialogs
    # ------------------------------------------------------------------
    def with_wait(self, message: str, work: Any) -> Any:
        """Run WORK behind the wait indicator, nesting safely.

        MATLAB nests this (the constructor's wait wraps the reload's), and a
        nested call must not clear the outer indicator early, so the outer
        message is restored rather than blanked.
        """
        previous = self.status_text()
        self.set_busy(True, message)
        try:
            return work()
        finally:
            self.set_busy(False, previous)

    def status_text(self) -> str:
        return self.status_label.text() if self.status_label is not None else ""

    def set_busy(self, busy: bool, message: str) -> None:
        """Show or clear the wait state, and pump the event loop once."""
        if self.status_label is not None:
            self.status_label.setText(message)
        if busy:
            if self.run_button is not None:
                self.run_button.setEnabled(False)
            if self.control_button is not None:
                self.control_button.setEnabled(False)
        _process_events()

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def close(self) -> None:
        if self.figure is not None:
            self.figure.close()

    def alert(self, message: str, title: str, *, success: bool = False) -> Any:
        """Show a message. Non-blocking, as the navigator's alert is."""
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
        return (
            f"stimulusDecoder(stimulators={len(self.stimulators)}, "
            f"epochs={len(self.epoch_ids)}, decoded={len(self.decoded_epochs)})"
        )


#: PascalCase spelling, for code that would rather not write a class name
#: that starts lowercase. The MATLAB spelling is the class itself.
StimulusDecoder = stimulusDecoder


def _process_events() -> None:
    """MATLAB's ``drawnow``: let the window repaint mid-work."""
    try:
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.processEvents()
    except Exception:  # noqa: BLE001 - no display, nothing to repaint
        pass
