"""ndi.gui.nav.daq_system_browser - a read-only browser of a session's DAQ systems.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/daqSystemBrowser.m``

Shows every DAQ system of a session so the user can see how each one finds
its data files and its epoch probe maps. A viewer only; nothing is edited.
The target of the navigator's per-session "Session > DAQ Systems..." item.

Layout (master-detail):

* Left -- a list of the session's DAQ systems by name.
* Right -- a scrollable panel describing the selected DAQ system, in
  sections: *Acquisition* (DAQ system class, DAQ reader, metadata readers),
  *Files in each epoch* (the file navigator and its ``fileparameters``
  patterns, one per line), *Epoch probe map* (the ``epochprobemap_class``
  and ``epochprobemap_fileparameters`` patterns, or the default location
  when none are set), and *Example epoch*: on request ("Load epochs") a
  chooser of the DAQ system's epochs and, for the chosen epoch, a table of
  the actual files on disk, the pattern each matches, and which file is the
  epoch probe map. Reading epochs touches the disk, so it runs only when
  asked.

Class names are MATLAB-style (``ndi.daq.reader.mfdaq.intan``, via
:func:`ndi.util.classname.ndi_matlab_classname`), so the two languages show
the same names; the panel shows the last component and the full name on
hover.

As in :mod:`ndi.gui.nav.session_info`, what the window will SAY is computed
by plain functions -- :meth:`DaqSystemBrowser.describe`,
:meth:`DaqSystemBrowser.epoch_file_rows` and friends -- that are testable
without a display; only the widgets need Qt.
"""

from __future__ import annotations

import fnmatch
import os
import re
from typing import Any

from ...util.classname import ndi_matlab_classname
from ...util.matlab_regex import matlab_to_python_regex
from ..cloud_colors import cloud_colors, rgb_to_hex

__all__ = ["DaqSystemBrowser"]

NONE_TEXT = "(none)"
NO_DAQ = "(no DAQ systems)"
UNNAMED_SESSION = "(unnamed session)"
EPOCH_COLUMN_NAMES = ["File", "Matches pattern", "Role"]
EPOCH_PROMPT_ROW = ['(choose "Load epochs" to see the files of an epoch)', "", ""]


class DaqSystemBrowser:
    """A window browsing one session's DAQ systems.

    Constructing it reads the session's DAQ systems once (with
    ``daqsystem_load()``); :meth:`build` creates the widgets. They are
    separate so the reading can be tested on its own.
    """

    def __init__(self, session: Any, *, build: bool = True):
        self.session = session
        self.daqs: list[Any] = self.daq_systems()
        self.info: list[dict[str, Any]] = self.describe_all(self.daqs)
        #: Per DAQ system: None until loaded, else a list of
        #: ``{"number": int, "id": str}`` (see :meth:`load_epochs`).
        self.epochs: list[list[dict[str, Any]] | None] = [None] * len(self.daqs)
        self.selected: int = 0

        self.figure: Any = None
        self.list: Any = None
        self.detail_area: Any = None
        self.detail_panel: Any = None
        self.epoch_dropdown: Any = None
        self.epoch_button: Any = None
        self.epoch_table: Any = None
        #: The rows currently shown in the epoch table (what the user sees).
        self.epoch_rows: list[list[str]] = [list(EPOCH_PROMPT_ROW)]
        #: The text of every label in the detail panel, top to bottom.
        self.detail_texts: list[str] = []
        if build:
            self.build()

    # ------------------------------------------------------------------
    # reading the session -- no Qt in this section
    # ------------------------------------------------------------------
    def session_ref(self) -> str:
        """A human-readable session reference, best effort."""
        try:
            ref = str(self.session.reference or "")
        except Exception:  # noqa: BLE001
            ref = ""
        return ref or UNNAMED_SESSION

    def daq_systems(self) -> list[Any]:
        """The session's DAQ system objects.

        No name filter: a name regexp makes the database search much slower
        on large databases, and every DAQ system is wanted anyway.
        """
        try:
            daqs = self.session.daqsystem_load()
        except Exception:  # noqa: BLE001
            return []
        if daqs is None:
            return []
        return list(daqs) if isinstance(daqs, (list, tuple)) else [daqs]

    @staticmethod
    def describe_all(daqs: list[Any]) -> list[dict[str, Any]]:
        """:meth:`describe` for each DAQ system in DAQS."""
        return [DaqSystemBrowser.describe(d) for d in daqs or []]

    @staticmethod
    def describe(d: Any) -> dict[str, Any]:
        """A display description of one DAQ system D.

        Keys ``name``, ``daq_class``, ``reader_class``, ``navigator_class``
        and ``epoch_probe_map_class`` (str), and ``file_parameters``,
        ``epoch_probe_map_file_parameters`` and ``metadata_readers`` (lists of
        str). D may be an ``ndi_daq_system`` or anything with the same
        attributes; a part that cannot be read is left empty. ``describe(None)``
        is the empty template.
        """
        s: dict[str, Any] = {
            "name": "",
            "daq_class": "",
            "reader_class": "",
            "navigator_class": "",
            "file_parameters": [],
            "epoch_probe_map_class": "",
            "epoch_probe_map_file_parameters": [],
            "metadata_readers": [],
        }
        if d is None:
            return s
        s["daq_class"] = _classname(d)
        s["name"] = _text(_get(d, "name"))

        reader = _get(d, "daqreader")
        if reader is not None:
            s["reader_class"] = _classname(reader)

        nav = _get(d, "filenavigator")
        if nav is not None:
            s["navigator_class"] = _classname(nav)
            s["file_parameters"] = DaqSystemBrowser.filematch_list(_get(nav, "fileparameters"))
            s["epoch_probe_map_class"] = _text(_get(nav, "epochprobemap_class"))
            s["epoch_probe_map_file_parameters"] = DaqSystemBrowser.filematch_list(
                _get(nav, "epochprobemap_fileparameters")
            )

        readers = _get(d, "daqmetadatareaders")
        if readers is None:
            readers = _get(d, "daqmetadatareader")
        if readers is not None and not isinstance(readers, (list, tuple)):
            readers = [readers]
        for m in readers or []:
            entry = _classname(m)
            tsv = _text(_get(m, "tab_separated_file_parameter"))
            if tsv:
                entry = f"{entry} ({tsv})"
            s["metadata_readers"].append(entry)
        return s

    @staticmethod
    def filematch_list(fp: Any) -> list[str]:
        """The filematch patterns of file parameters FP, as a list of str.

        FP may be empty, a pattern, a list of patterns, or a dict with a
        ``filematch`` key holding either (the form ``ndi_file_navigator``
        stores).
        """
        if not fp:
            return []
        if isinstance(fp, dict):
            fp = fp.get("filematch")
            if not fp:
                return []
        if isinstance(fp, str):
            return [fp]
        if isinstance(fp, (list, tuple)):
            return [str(x) for x in fp]
        return []

    @staticmethod
    def short_class_name(full_name: str) -> str:
        """Last component of a dotted class name: ``'a.b.intan'`` -> ``'intan'``."""
        return str(full_name or "").rsplit(".", 1)[-1]

    @staticmethod
    def epoch_labels(numbers: list[int], ids: list[str]) -> list[str]:
        """Epoch chooser text, e.g. ``'Epoch 1  (t00001)'``."""
        labels = []
        for i, n in enumerate(numbers):
            label = f"Epoch {n}"
            if i < len(ids) and ids[i]:
                label += f"  ({ids[i]})"
            labels.append(label)
        return labels

    @staticmethod
    def matching_pattern(patterns: list[str], name: str) -> str:
        """The first of PATTERNS that file NAME matches, or ``""``.

        Matching follows :func:`ndi.file.navigator.find_file_groups`: ``#`` is
        a wildcard (as a glob), and failing that the pattern is tried as a
        MATLAB regular expression. Each pattern is tried on its own.
        """
        for pattern in patterns or []:
            if fnmatch.fnmatch(name, pattern.replace("#", "*")):
                return pattern
            try:
                if re.search(matlab_to_python_regex(pattern), name):
                    return pattern
            except re.error:
                pass
        return ""

    @staticmethod
    def epoch_file_rows(
        files: list[str], patterns: list[str], probe_map_file: str | None
    ) -> list[list[str]]:
        """Rows of [file name, matching pattern, role] for one epoch.

        FILES are the full paths of the epoch's files, PATTERNS the
        navigator's filematch patterns and PROBE_MAP_FILE the epoch's epoch
        probe map file (full path, or empty). Each file is listed by name
        with the first pattern it matches; the epoch probe map file is marked
        in the Role column. When the probe map lives outside the epoch files
        (the default hidden location), it gets its own row.
        """
        rows: list[list[str]] = []
        probe_map_file = probe_map_file or ""
        for f in files or []:
            name = os.path.basename(f)
            role = "epoch probe map" if probe_map_file and f == probe_map_file else ""
            rows.append([name, DaqSystemBrowser.matching_pattern(patterns, name), role])
        if probe_map_file and probe_map_file not in (files or []):
            role = "epoch probe map (default location)"
            if not os.path.isfile(probe_map_file):
                role += ", not found"
            rows.append([os.path.basename(probe_map_file), "", role])
        return rows or [["(this epoch has no files)", "", ""]]

    @staticmethod
    def default_epoch_probe_map_text() -> str:
        """Shown when no epoch probe map file parameters are set."""
        return "(none set; default: hidden .<first epoch file>.epochprobemap.ndi file)"

    @staticmethod
    def detail_items(s: dict[str, Any]) -> list[tuple[str, str, str, str]]:
        """The detail panel's rows for description S, top to bottom.

        Each is ``(kind, label, value, tooltip)`` with kind one of
        ``title``, ``section``, ``field``, ``pattern``, ``note``,
        ``epochControls`` and ``epochTable``.
        """
        short = DaqSystemBrowser.short_class_name
        items: list[tuple[str, str, str, str]] = [("title", s["name"], "", "")]
        items.append(("section", "Acquisition", "", ""))
        items.append(("field", "DAQ system class", short(s["daq_class"]), s["daq_class"]))
        items.append(("field", "DAQ reader", short(s["reader_class"]), s["reader_class"]))
        items += _list_items("Metadata readers", s["metadata_readers"], NONE_TEXT)
        items.append(("section", "Files in each epoch", "", ""))
        items.append(("field", "File navigator", short(s["navigator_class"]), s["navigator_class"]))
        items += _list_items("File patterns", s["file_parameters"], NONE_TEXT)
        items.append(("section", "Epoch probe map", "", ""))
        items.append(
            (
                "field",
                "Class",
                short(s["epoch_probe_map_class"]),
                s["epoch_probe_map_class"],
            )
        )
        items += _list_items(
            "File patterns",
            s["epoch_probe_map_file_parameters"],
            DaqSystemBrowser.default_epoch_probe_map_text(),
        )
        items.append(("section", "Example epoch", "", ""))
        items.append(("epochControls", "Epoch", "", ""))
        items.append(("epochTable", "", "", ""))
        return items

    # ------------------------------------------------------------------
    # epochs -- read on request
    # ------------------------------------------------------------------
    def load_epochs(self, k: int | None = None) -> list[dict[str, Any]] | None:
        """Read DAQ system K's epochs and list them ("Load epochs").

        K is the 0-based position in the list, defaulting to the selected DAQ
        system. Reads the navigator's epoch table (which reads the disk),
        fills the epoch chooser and shows the files of the first epoch.
        Returns the epochs, or None when they could not be read (the reason
        is shown in the epoch table).
        """
        k = self.selected if k is None else k
        nav = _get(self.daqs[k], "filenavigator")
        try:
            et = nav.epochtable()
            if isinstance(et, tuple):
                et = et[0]
        except Exception as exc:  # noqa: BLE001
            self._set_epoch_rows([[f"(could not read the epochs: {exc})", "", ""]])
            return None
        self.epochs[k] = [
            {"number": i, "id": str((e or {}).get("epoch_id", "") or "")}
            for i, e in enumerate(et or [], start=1)
        ]
        if k == self.selected:
            self._fill_epoch_dropdown()
        return self.epochs[k]

    def choose_epoch(self, n: int) -> list[list[str]] | None:
        """Show the files of epoch N (1-based) of the selected DAQ system.

        The same as picking epoch N in the chooser; the epochs must have been
        loaded first. Returns the rows shown, or None when N is not an epoch.
        """
        ep = self.epochs[self.selected] if self.daqs else None
        if not ep or not any(e["number"] == n for e in ep):
            return None
        if self.epoch_dropdown is not None:
            self.epoch_dropdown.blockSignals(True)
            self.epoch_dropdown.setCurrentIndex(n - 1)
            self.epoch_dropdown.blockSignals(False)
        return self._show_epoch_files(self.selected, n)

    def epoch_rows_for(self, k: int, n: int) -> list[list[str]]:
        """The epoch-table rows for epoch N (1-based) of DAQ system K. No Qt."""
        nav = _get(self.daqs[k], "filenavigator")
        try:
            files = list(nav.getepochfiles_number(n) or [])
        except Exception as exc:  # noqa: BLE001
            return [[f"(could not read the epoch files: {exc})", "", ""]]
        if files and str(files[0]).startswith("epochid://"):
            return [["(this epoch is ingested; its raw files are stored in the database)", "", ""]]
        probe_map_file = ""
        try:
            probe_map_file = nav.epochprobemapfilename(n) or ""
        except Exception:  # noqa: BLE001
            pass
        return self.epoch_file_rows(files, self.info[k]["file_parameters"], probe_map_file)

    def _show_epoch_files(self, k: int, n: int) -> list[list[str]]:
        rows = self.epoch_rows_for(k, n)
        self._set_epoch_rows(rows)
        return rows

    def _set_epoch_rows(self, rows: list[list[str]]) -> None:
        self.epoch_rows = [list(r) for r in rows]
        if self.epoch_table is None:
            return
        from PySide6 import QtWidgets

        self.epoch_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for col, value in enumerate(row):
                self.epoch_table.setItem(r, col, QtWidgets.QTableWidgetItem(str(value)))

    def _fill_epoch_dropdown(self) -> None:
        """Populate the chooser from the selected DAQ system's loaded epochs."""
        ep = self.epochs[self.selected]
        if self.epoch_button is not None:
            self.epoch_button.setEnabled(False)
        if not ep:
            if self.epoch_dropdown is not None:
                self.epoch_dropdown.clear()
                self.epoch_dropdown.addItem("(no epochs)")
            self._set_epoch_rows([["(this DAQ system has no epochs)", "", ""]])
            return
        if self.epoch_dropdown is not None:
            self.epoch_dropdown.blockSignals(True)
            self.epoch_dropdown.clear()
            self.epoch_dropdown.addItems(
                self.epoch_labels([e["number"] for e in ep], [e["id"] for e in ep])
            )
            self.epoch_dropdown.setEnabled(True)
            self.epoch_dropdown.setCurrentIndex(0)
            self.epoch_dropdown.blockSignals(False)
        self._show_epoch_files(self.selected, ep[0]["number"])

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build(self) -> Any:
        """Create the window: DAQ system list and detail panel."""
        from .._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtWidgets

        c = cloud_colors()
        navy = rgb_to_hex(c.dark_blue)
        white = rgb_to_hex(c.white)

        self.figure = QtWidgets.QWidget()
        self.figure.setWindowTitle(f"DAQ systems: {self.session_ref()}")
        self.figure.setObjectName("ndiNavigatorDaqSystemBrowser")
        self.figure.resize(900, 620)
        self.figure.setStyleSheet(f"background-color: {navy};")

        outer = QtWidgets.QHBoxLayout(self.figure)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)

        left = QtWidgets.QVBoxLayout()
        heading = QtWidgets.QLabel("DAQ systems")
        heading.setStyleSheet(f"color: {white}; font-weight: bold;")
        left.addWidget(heading)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("ndiDaqSystemList")
        self.list.setFixedWidth(200)
        self.list.setStyleSheet(f"background-color: {white}; color: {navy};")
        left.addWidget(self.list, 1)
        outer.addLayout(left)

        self.detail_area = QtWidgets.QScrollArea()
        self.detail_area.setWidgetResizable(True)
        self.detail_area.setStyleSheet(f"background-color: {white};")
        outer.addWidget(self.detail_area, 1)

        if not self.info:
            self.list.addItem(NO_DAQ)
            self.list.setEnabled(False)
            panel = QtWidgets.QWidget()
            QtWidgets.QVBoxLayout(panel).addWidget(
                self._label("This session has no DAQ systems.", navy)
            )
            self.detail_area.setWidget(panel)
            self.detail_texts = ["This session has no DAQ systems."]
            return self.figure

        self.list.addItems([s["name"] for s in self.info])
        self.list.currentRowChanged.connect(self.select)
        self.select(0)
        return self.figure

    def select(self, k: int) -> None:
        """Show the details of DAQ system K (0-based position in the list)."""
        if k < 0 or k >= len(self.info):
            return
        self.selected = k
        if self.list is not None and self.list.currentRow() != k:
            self.list.blockSignals(True)
            self.list.setCurrentRow(k)
            self.list.blockSignals(False)
        self._show_details(k)

    def _show_details(self, k: int) -> None:
        """Rebuild the detail panel for DAQ system K."""
        self.epoch_rows = [list(EPOCH_PROMPT_ROW)]
        if self.detail_area is None:
            return
        from PySide6 import QtWidgets

        c = cloud_colors()
        navy = rgb_to_hex(c.dark_blue)
        light = rgb_to_hex(c.light_blue)

        panel = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(panel)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setVerticalSpacing(4)
        grid.setColumnMinimumWidth(0, 150)
        grid.setColumnStretch(1, 1)
        self.detail_texts = []

        items = self.detail_items(self.info[k])
        for r, (kind, label, value, tooltip) in enumerate(items):
            if kind == "title":
                w = self._label(label, navy, "font-size: 18pt; font-weight: bold;")
                grid.addWidget(w, r, 0, 1, 2)
            elif kind == "section":
                w = self._label(label, light, "font-size: 14pt; font-weight: bold;")
                grid.addWidget(w, r, 0, 1, 2)
            elif kind in ("field", "pattern", "note"):
                if label:
                    grid.addWidget(self._label(f"{label}:", navy), r, 0)
                if kind == "field" and not value:
                    value, extra = NONE_TEXT, "font-style: italic;"
                elif kind == "pattern":
                    extra = "font-family: monospace;"
                elif kind == "note":
                    extra = "font-style: italic;"
                else:
                    extra = ""
                w = self._label(value, navy, extra)
                if tooltip:
                    w.setToolTip(tooltip)
                grid.addWidget(w, r, 1)
            elif kind == "epochControls":
                grid.addWidget(self._label(f"{label}:", navy), r, 0)
                grid.addWidget(self._epoch_controls(k), r, 1)
            elif kind == "epochTable":
                self.epoch_table = QtWidgets.QTableWidget(1, len(EPOCH_COLUMN_NAMES))
                self.epoch_table.setObjectName("ndiDaqSystemEpochFiles")
                self.epoch_table.setHorizontalHeaderLabels(EPOCH_COLUMN_NAMES)
                self.epoch_table.verticalHeader().setVisible(False)
                self.epoch_table.setEditTriggers(
                    QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
                )
                self.epoch_table.horizontalHeader().setStretchLastSection(True)
                self.epoch_table.setMinimumHeight(200)
                self.epoch_table.setStyleSheet(f"color: {navy};")
                grid.addWidget(self.epoch_table, r, 0, 1, 2)
        grid.setRowStretch(len(items), 1)
        self.detail_panel = panel
        self.detail_area.setWidget(panel)

        self._set_epoch_rows([list(EPOCH_PROMPT_ROW)])
        # Epochs already loaded for this DAQ system are shown at once.
        if self.epochs[k] is not None:
            self._fill_epoch_dropdown()

    def _epoch_controls(self, k: int) -> Any:
        """The epoch chooser and the "Load epochs" button."""
        from PySide6 import QtWidgets

        c = cloud_colors()
        box = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        self.epoch_dropdown = QtWidgets.QComboBox()
        self.epoch_dropdown.setObjectName("ndiDaqSystemEpochChooser")
        self.epoch_dropdown.addItem("(not loaded)")
        self.epoch_dropdown.setEnabled(False)
        self.epoch_dropdown.currentIndexChanged.connect(lambda i: self._on_epoch_index(k, i))
        row.addWidget(self.epoch_dropdown, 1)
        self.epoch_button = QtWidgets.QPushButton("Load epochs")
        self.epoch_button.setToolTip("Read this DAQ system's epochs from disk")
        self.epoch_button.setStyleSheet(
            f"background-color: {rgb_to_hex(c.light_blue)}; color: {rgb_to_hex(c.dark_blue)};"
        )
        self.epoch_button.clicked.connect(lambda: self.load_epochs(k))
        row.addWidget(self.epoch_button)
        return box

    def _on_epoch_index(self, k: int, index: int) -> None:
        ep = self.epochs[k]
        if ep and 0 <= index < len(ep):
            self._show_epoch_files(k, ep[index]["number"])

    def _label(self, text: str, color: str, extra: str = "") -> Any:
        from PySide6 import QtWidgets

        w = QtWidgets.QLabel(str(text))
        w.setWordWrap(True)
        w.setStyleSheet(f"color: {color}; {extra}")
        # Selectable, so a pattern or class name can be copied by hand.
        from PySide6 import QtCore

        w.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail_texts.append(str(text))
        return w

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def __repr__(self) -> str:
        return f"DaqSystemBrowser(session={self.session_ref()!r}, daqs={len(self.daqs)})"


def _list_items(label: str, values: list[str], empty_text: str) -> list[tuple[str, str, str, str]]:
    """One ``pattern`` row per value, labelling only the first; or one ``note``."""
    if not values:
        return [("note", label, empty_text, "")]
    return [("pattern", label if i == 0 else "", v, "") for i, v in enumerate(values)]


def _get(obj: Any, name: str) -> Any:
    """``obj.name`` or ``obj[name]``, or None when it cannot be read."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    try:
        return getattr(obj, name)
    except Exception:  # noqa: BLE001
        return None


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _classname(obj: Any) -> str:
    """The MATLAB-style class name of OBJ, e.g. ``ndi.daq.system.mfdaq``."""
    try:
        return ndi_matlab_classname(obj)
    except Exception:  # noqa: BLE001
        return type(obj).__name__
