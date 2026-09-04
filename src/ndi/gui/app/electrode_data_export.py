"""ndi.gui.app.electrode_data_export - export probe data for spike sorters.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/ElectrodeDataExport.m``

A window over a session's n-trode probes: pick some, pick a sorter, press
Export, and each probe's flat int16 binary and Kilosort-style channel map
are written into that sorter's folder under the session path. It is the
first of MATLAB's session apps to reach Python, and so also the first
end-to-end proof of the discovery mechanism: it appears in the navigator's
per-session Apps menu by subclassing :class:`~ndi.gui.app.SessionApp` and
by nothing else -- no registration, no edit to the pane or the menu.

WHY THE LIST SAYS WHAT IT HAS ALREADY EXPORTED
Each row names the sorters that probe already has a binary for, in
parentheses. Exporting is slow -- minutes per probe of raw recording -- and
re-exporting silently overwrites, so the parenthetical is what stops a user
spending a coffee break rewriting a file they already had. It is read from
the filesystem on every refresh rather than remembered, so a folder deleted
outside the app is reflected the next time the list is rebuilt.

WHY MISSING GEOMETRY WARNS RATHER THAN REFUSES
A probe with no assigned electrode geometry still exports; its channel map
is a default single-column linear layout. That is legitimate for a real
single-shank array and wrong for most everything else, and a sorter given a
wrong map does not fail -- it merges units that were never neighbours. So
the app names the probes that would get one and makes Export the non-default
answer, which is the only point at which the choice is cheap. Geometries are
assigned with the Electrode Map app.

WHAT IS QT AND WHAT IS NOT
The label of each row, which sorters a probe counts as exported for, whether
Export can be pressed, and the text of the geometry warning are plain Python
and tested without a display -- the split :mod:`ndi.gui.preferences_editor`
and :mod:`ndi.gui.profile_editor` make, for the same reason. A row labelled
with the wrong probe does not raise; it just exports the wrong recording.

DEVIATIONS FROM MATLAB
* MATLAB's ``uilistbox`` carries ``ItemsData``, so its ``Value`` is already
  the selected probe INDICES. Qt's list widget has no such field, so the
  selection is read back as row numbers in :meth:`selected_indices`, which
  is what the rest of the app consumes.
* MATLAB exports on the same thread and leans on ``drawnow`` to keep the
  progress bar moving. This does the same, pumping the event loop through
  the progress helpers rather than moving the export to a worker thread:
  the progress bar is shared with the navigator's Progress pane, which is
  not thread-safe, and a background export would be a change to that
  component rather than to this app.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from .session_app import SessionApp

__all__ = [
    "ElectrodeDataExport",
    "Exporter",
    "EXPORTERS",
    "DEFAULT_POSITION",
    "WINDOW_TAG",
    "PROBE_TYPE",
    "probe_label",
    "missing_geometry_message",
]

#: Where the window opens, ``(x, y, width, height)``, as MATLAB positions it.
DEFAULT_POSITION: tuple[float, float, float, float] = (100, 100, 620, 460)

#: The window's object name, MATLAB's figure Tag.
WINDOW_TAG = "ndi.gui.app.ElectrodeDataExport"

#: The probe type this app exports. Everything else in a session -- a
#: stimulator, a single electrode -- has no n-trode binary to write.
PROBE_TYPE = "n-trode"


@dataclass(frozen=True)
class Exporter:
    """One supported export target.

    Each writes the same flat int16 binary and Kilosort-style
    ``channel_map.mat`` into its own folder, so a probe can be exported
    independently for each and the folders never collide.
    """

    #: What the dropdown shows, and what the list shows in parentheses.
    name: str
    #: The folder under the session path this sorter's exports go in.
    dir: str
    #: The binary's file name inside the probe's subfolder.
    bin: str


#: The supported sorters, in dropdown order. Add a row to support another.
EXPORTERS: tuple[Exporter, ...] = (
    Exporter(name="KIASORT", dir="kiasort", bin="kiasort.bin"),
    Exporter(name="Kilosort", dir="kilosort", bin="kilosort.bin"),
)


def probe_label(element_string: str, exported_for: list[str] | tuple[str, ...] = ()) -> str:
    """The list row for a probe: its element string, then what it is exported for.

    ``"ctx_-_1"`` on its own, or ``"ctx_-_1 (KIASORT, Kilosort)"``. A probe
    exported for nothing gets no parentheses rather than empty ones, so the
    common case reads as a plain name.
    """
    label = str(element_string)
    done = [str(name) for name in exported_for]
    if done:
        label = f"{label} ({', '.join(done)})"
    return label


def missing_geometry_message(missing: list[str] | tuple[str, ...]) -> str:
    """The warning shown when selected probes have no electrode geometry.

    Names them, because "some probes" leaves the user no way to tell whether
    the one they care about is among them.
    """
    names = [str(name) for name in missing]
    return (
        f"{len(names)} of the selected probe(s) have no electrode geometry assigned:\n"
        f"    {', '.join(names)}\n\n"
        "Their channel map will be a default single-column linear layout, which is usually "
        "wrong for real arrays. You can assign geometries first with the Electrode Map app."
        "\n\nExport anyway?"
    )


class ElectrodeDataExport(SessionApp):
    """Export the n-trode probes of a session for a spike sorter.

    ``ElectrodeDataExport(session)`` opens the window, which is the whole
    contract :class:`~ndi.gui.app.SessionApp` asks of an app.

    MATLAB equivalent: ``ndi.gui.app.ElectrodeDataExport``.
    """

    #: The Apps-menu label. Verbatim from MATLAB: it is user-visible text.
    Name: ClassVar[str] = "Electrode Data Export"

    def __init__(
        self,
        session: Any,
        *,
        position: tuple[float, float, float, float] = DEFAULT_POSITION,
        build: bool = True,
    ):
        self.session = session
        self.position = tuple(position)
        self.exporters: tuple[Exporter, ...] = EXPORTERS
        #: The session's n-trode probes, in the order the list shows them.
        self.probes: list[Any] = []
        self.figure: Any = None
        self.probe_list: Any = None
        self.export_dropdown: Any = None
        self.export_button: Any = None
        self._held: list[Any] = []
        if build:
            self.build()

    # ------------------------------------------------------------------
    # model
    # ------------------------------------------------------------------
    def load_probes(self) -> list[Any]:
        """Collect the session's n-trode probes.

        A session that cannot answer leaves the list empty rather than
        raising, as MATLAB's try/catch does: an app that will not open tells
        the user less than an app that opens empty.
        """
        try:
            probes = self.session.getprobes(type=PROBE_TYPE)
        except Exception:  # noqa: BLE001 - an unreadable session lists nothing
            probes = []
        self.probes = list(probes) if probes else []
        return self.probes

    def exported_sorters(self, probe: Any) -> list[str]:
        """Names of the sorters *probe* already has a binary for, in dropdown order."""
        from ...fun.file import elementDirectory

        names: list[str] = []
        for exporter in self.exporters:
            try:
                probedir = elementDirectory(Path(self.session.path) / exporter.dir, probe)[0]
                if (Path(probedir) / exporter.bin).is_file():
                    names.append(exporter.name)
            except Exception:  # noqa: BLE001 - an unreadable path exports nothing
                continue
        return names

    def probe_items(self) -> list[str]:
        """One list row per probe, in :attr:`probes` order."""
        return [
            probe_label(probe.elementstring(), self.exported_sorters(probe))
            for probe in self.probes
        ]

    def exporter_by_name(self, name: str) -> Exporter | None:
        """The exporter the dropdown is showing, or None if it names none."""
        for exporter in self.exporters:
            if exporter.name == name:
                return exporter
        return None

    def selected_exporter(self) -> Exporter | None:
        """The exporter currently chosen in the dropdown."""
        if self.export_dropdown is None:
            return None
        return self.exporter_by_name(self.export_dropdown.currentText())

    def selected_indices(self) -> list[int]:
        """Indices into :attr:`probes` of the selected rows, ascending.

        MATLAB reads these straight off the listbox's ItemsData; Qt has no
        such field, so the selected rows ARE the indices -- which holds
        because :meth:`refresh_probe_list` fills the list in probe order.
        """
        if self.probe_list is None:
            return []
        rows = sorted(index.row() for index in self.probe_list.selectedIndexes())
        return [row for row in rows if 0 <= row < len(self.probes)]

    def probes_without_geometry(self, indices: list[int]) -> list[str]:
        """Element strings of the selected probes that have no geometry on file."""
        from ...fun.probe.geometry import get as geometry_get

        missing: list[str] = []
        for index in indices:
            probe = self.probes[index]
            try:
                found = geometry_get(self.session, probe).found
            except Exception:  # noqa: BLE001 - unreadable is indistinguishable from absent
                found = False
            if not found:
                missing.append(str(probe.elementstring()))
        return missing

    def can_export(self) -> bool:
        """True when at least one probe and a sorter are chosen."""
        return bool(self.selected_indices()) and self.selected_exporter() is not None

    # ------------------------------------------------------------------
    # the window
    # ------------------------------------------------------------------
    def build(self) -> Any:
        from .._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtCore, QtWidgets

        from ..cloud_colors import cloud_colors, rgb_to_hex

        c = cloud_colors()
        x, y, w, h = self.position

        self.figure = QtWidgets.QWidget()
        self.figure.setWindowTitle(f"Electrode Data Export: {self.session.reference}")
        self.figure.setObjectName(WINDOW_TAG)
        self.figure.setGeometry(int(x), int(y), int(w), int(h))
        self.figure.setStyleSheet(f"background-color: {rgb_to_hex(c.dark_blue)};")

        root = QtWidgets.QVBoxLayout(self.figure)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        title = QtWidgets.QLabel("Export Electrode Data for Spike Sorting")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {rgb_to_hex(c.white)}; font-size: 16px; font-weight: bold;")
        title.setFixedHeight(30)
        root.addWidget(title)

        header = QtWidgets.QLabel("n-trode Probes (exported for):")
        header.setStyleSheet(f"color: {rgb_to_hex(c.white)}; font-weight: bold;")
        header.setFixedHeight(20)
        root.addWidget(header)

        self.probe_list = QtWidgets.QListWidget()
        self.probe_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.probe_list.setStyleSheet(
            f"background-color: {rgb_to_hex(c.white)}; color: {rgb_to_hex(c.dark_blue)};"
        )
        self.probe_list.itemSelectionChanged.connect(self.update_button_state)
        root.addWidget(self.probe_list, 1)

        bottom = QtWidgets.QHBoxLayout()
        bottom.setSpacing(8)

        export_label = QtWidgets.QLabel("Export To:")
        export_label.setStyleSheet(f"color: {rgb_to_hex(c.white)}; font-weight: bold;")
        export_label.setFixedWidth(75)
        bottom.addWidget(export_label)

        self.export_dropdown = QtWidgets.QComboBox()
        self.export_dropdown.addItems([exporter.name for exporter in self.exporters])
        self.export_dropdown.setFixedWidth(180)
        self.export_dropdown.setStyleSheet(
            f"background-color: {rgb_to_hex(c.white)}; color: {rgb_to_hex(c.dark_blue)};"
        )
        self.export_dropdown.currentIndexChanged.connect(self.update_button_state)
        bottom.addWidget(self.export_dropdown)

        bottom.addStretch(1)

        self.export_button = QtWidgets.QPushButton("Export")
        self.export_button.setFixedWidth(130)
        self.export_button.setStyleSheet(
            f"background-color: {rgb_to_hex(c.light_blue)};"
            f"color: {rgb_to_hex(c.dark_blue)}; font-weight: bold;"
        )
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.do_export)
        bottom.addWidget(self.export_button)

        root.addLayout(bottom)

        self.load_probes()
        self.refresh_probe_list()
        self.figure.show()
        return self.figure

    def refresh_probe_list(self) -> list[str]:
        """Rebuild the rows, keeping the selection; returns the row labels.

        The selection is kept BY INDEX, as MATLAB keeps it: the labels change
        as probes gain exports, so matching on text would drop the selection
        of exactly the probe that was just exported.
        """
        items = self.probe_items()
        if self.probe_list is None:
            return items

        from PySide6 import QtWidgets

        previous = self.selected_indices()
        self.probe_list.blockSignals(True)
        try:
            self.probe_list.clear()
            for text in items:
                self.probe_list.addItem(QtWidgets.QListWidgetItem(text))
            for index in previous:
                if 0 <= index < self.probe_list.count():
                    self.probe_list.item(index).setSelected(True)
        finally:
            self.probe_list.blockSignals(False)
        self.update_button_state()
        return items

    def update_button_state(self) -> bool:
        """Enable Export only when it would do something; returns the new state."""
        enabled = self.can_export()
        if self.export_button is not None:
            self.export_button.setEnabled(enabled)
        return enabled

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def close(self) -> None:
        if self.figure is not None:
            self.figure.close()

    # ------------------------------------------------------------------
    # exporting
    # ------------------------------------------------------------------
    def do_export(self) -> list[str]:
        """Export the selected probes for the selected sorter.

        Returns the per-probe error messages, so a caller (and a test) can
        see what failed; the user sees them in one dialog. A probe that
        fails does not stop the ones after it -- a two-hour export should
        not be lost to one unreadable epoch.
        """
        indices = self.selected_indices()
        exporter = self.selected_exporter()
        if not indices or exporter is None:
            return []

        missing = self.probes_without_geometry(indices)
        if missing and not self.confirm(
            missing_geometry_message(missing),
            "Missing electrode geometry",
            accept="Export anyway",
        ):
            return []

        if self.export_button is not None:
            self.export_button.setEnabled(False)
        _process_events()

        tag = f"export:{exporter.name}"
        bar = _make_bar("Exporting electrode data", f"Exporting for {exporter.name}", tag)
        errors: list[str] = []
        try:
            errors = self.export_probes(indices, exporter, bar=bar, tag=tag)
        finally:
            _close_bar(bar, tag)
            if self.export_button is not None:
                self.export_button.setEnabled(True)

        self.refresh_probe_list()

        if errors:
            self.alert("\n".join(errors), "Some exports failed")
        else:
            self.alert(
                f"Exported {len(indices)} probe(s) for {exporter.name}.",
                "Export complete",
                success=True,
            )
        return errors

    def export_probes(
        self,
        indices: list[int],
        exporter: Exporter,
        *,
        bar: Any = None,
        tag: str = "",
    ) -> list[str]:
        """Export the probes at *indices* for *exporter*; returns error messages.

        Each probe's own write progress maps into its slice of one bar
        across the whole selection, so the bar measures the job the user
        asked for rather than restarting at every probe.
        """
        from ...fun.probe.export import oneProbe

        errors: list[str] = []
        total = len(indices)
        for position, index in enumerate(indices):
            probe = self.probes[index]
            base = position / total

            def progress(fraction: float, _message: str = "", base: float = base) -> None:
                _update_bar(bar, tag, base + fraction / total)

            try:
                oneProbe(
                    self.session,
                    probe,
                    binary_dir=exporter.dir,
                    binaryFileName=exporter.bin,
                    verbose=0,
                    progressfcn=progress,
                )
            except Exception as exc:  # noqa: BLE001 - reported per probe, not raised
                errors.append(f"{probe.elementstring()}: {exc}")
        return errors

    # ------------------------------------------------------------------
    # dialogs
    # ------------------------------------------------------------------
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

    def confirm(self, message: str, title: str, *, accept: str) -> bool:
        """Confirm before a costly or lossy step, defaulting to Cancel."""
        if self.figure is None:
            return False
        from PySide6 import QtWidgets

        box = QtWidgets.QMessageBox(self.figure)
        box.setWindowTitle(title)
        box.setText(message)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        go = box.addButton(accept, QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is go

    def __repr__(self) -> str:
        return f"ElectrodeDataExport(probes={len(self.probes)})"


# ----------------------------------------------------------------------
# module helpers: the progress bar, which must never break an export
# ----------------------------------------------------------------------
def _make_bar(title: str, label: str, tag: str) -> Any:
    """A progress bar for the export, or None if one cannot be made.

    ``ProgressBarWindow`` docks into an open navigator's Progress pane and
    opens a standalone window when no navigator is open. Every call here is
    guarded because a missing display, or a progress component that will not
    load, must cost the user their progress bar and not their export.
    """
    try:
        from ..component import ndi_gui_component_ProgressBarWindow

        bar = ndi_gui_component_ProgressBarWindow(title)
        bar.addBar(Label=label, Tag=tag, Auto=False)
        return bar
    except Exception:  # noqa: BLE001 - no bar is a degraded export, not a failed one
        return None


def _update_bar(bar: Any, tag: str, fraction: float) -> None:
    """Move *bar* to *fraction*, clamped, and let the window repaint."""
    if bar is None:
        return
    try:
        bar.updateBar(tag, max(0.0, min(1.0, float(fraction))))
        _process_events()
    except Exception:  # noqa: BLE001 - see _make_bar
        pass


def _close_bar(bar: Any, tag: str) -> None:
    """Remove the export's bar, whether the export finished or failed."""
    if bar is None:
        return
    try:
        bar.removeBar(tag)
    except Exception:  # noqa: BLE001 - see _make_bar
        pass


def _process_events() -> None:
    """MATLAB's ``drawnow``: repaint mid-export, on the same thread."""
    try:
        from PySide6 import QtWidgets

        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.processEvents()
    except Exception:  # noqa: BLE001 - no display, nothing to repaint
        pass
