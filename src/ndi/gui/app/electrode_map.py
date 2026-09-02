"""ndi.gui.app.electrode_map - assign electrode geometries to a session's probes.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/ElectrodeMap.m``

The first session app: a window with the electrode-layout library on the left,
the session's n-trode probes on the right, and an arrow between them that
assigns the selected layout to the selected probe. A "Plot geometry" button
draws the selected layout, so a user can see what they are about to assign.

WHAT THE LISTS SAY
A geometry reads ``name (site count)``. A probe reads
``elementstring (channel count) *model*``, where the starred part is the layout
it already has and is absent when it has none -- so the window answers "which
probes are still unassigned?" at a glance, which is the question it exists for.
Selecting an assigned probe highlights its layout on the left, matched by
``probe_model``.

WHAT IS QT AND WHAT IS NOT
Everything the window SAYS -- the two lists' contents, which geometry a probe
already has, whether the buttons are live -- is computed in plain Python and
tested without a display, as elsewhere in this package. :meth:`build` and the
handlers are the only Qt.

ASSIGNMENT REPLACES
``from_library`` is called with ``replace=True``: re-assigning overwrites a
probe's geometry rather than stacking a second ``probe_geometry`` document.
A site-count mismatch against the probe's epochprobemap is surfaced in a dialog
and does not block the assignment -- it is advisory, as in MATLAB, because a
probe can legitimately record a subset of a layout's sites.
"""

from __future__ import annotations

from typing import Any

from ...fun.probe import channelCount, geometry
from ..cloud_colors import cloud_colors, rgb_to_hex
from .session_app import SessionApp

__all__ = ["ElectrodeMap", "WINDOW_TAG", "DEFAULT_POSITION", "TITLE_TEXT"]

#: Object name on the window, MATLAB's Tag: what finds this app's window again.
WINDOW_TAG = "ndi.gui.app.ElectrodeMap"

#: MATLAB's Position: (x, y, width, height).
DEFAULT_POSITION = (100, 100, 680, 480)

#: The heading over the two lists.
TITLE_TEXT = "Assign Electrode Geometries to Probes"

#: Shown for a probe whose geometry has no probe_model of its own. A geometry
#: that exists but cannot be named still has to read as assigned, or the window
#: would invite the user to assign it again.
UNNAMED_ASSIGNMENT = "assigned"


class ElectrodeMap(SessionApp):
    """Assign electrode geometries to the n-trode probes of a session."""

    Name = "Electrode Map"

    def __init__(self, session: Any, *, build: bool = True):
        self.session = session
        self.figure: Any = None
        self.title_label: Any = None
        self.geometry_list: Any = None
        self.probe_list: Any = None
        self.assign_button: Any = None
        self.plot_button: Any = None

        #: The session's n-trode probes, in the order the right list shows them.
        self.probes: list[Any] = []
        #: Library names, parallel to :attr:`geometry_models`; the left list's data.
        self.geometry_names: list[str] = []
        #: The left list's labels: each name with its site count.
        self.geometry_labels: list[str] = []
        #: Each library layout's probe_model, so a probe's assignment can be
        #: matched back to the list. "" where a layout declares none.
        self.geometry_models: list[str] = []

        self.load_geometries()
        self.load_probes()
        if build:
            self.build()

    # ------------------------------------------------------------------
    # reading the library and the session -- no Qt in this section
    # ------------------------------------------------------------------
    def load_geometries(self) -> list[str]:
        """Read the layout library; return the left list's labels.

        A layout that will not read contributes its bare name and an empty
        model rather than disappearing: the library is data on disk, and one
        unreadable file must not empty the list.
        """
        try:
            names = geometry.list_library()
        except Exception:  # noqa: BLE001 - no library, no layouts
            names = []

        labels: list[str] = []
        models: list[str] = []
        for name in names:
            label = name
            model = ""
            try:
                layout, _ = geometry.read_library(name)
                sites = layout.get("site_locations_leftright") or []
                if sites:
                    label = f"{name} ({len(sites)})"
                model = str(layout.get("probe_model") or "")
            except Exception:  # noqa: BLE001 - an unreadable layout keeps its name
                pass
            labels.append(label)
            models.append(model)

        self.geometry_names = list(names)
        self.geometry_models = models
        self.geometry_labels = labels
        return labels

    def load_probes(self) -> list[Any]:
        """Collect the session's n-trode probes."""
        try:
            probes = self.session.getprobes(type="n-trode")
        except Exception:  # noqa: BLE001 - a session that cannot say has none
            probes = []
        self.probes = list(probes) if probes else []
        return self.probes

    def assigned_geometry_label(self, probe: Any) -> str:
        """The probe_model of PROBE's current geometry, "" when it has none."""
        try:
            found = geometry.get(self.session, probe)
        except Exception:  # noqa: BLE001 - an unreadable database reads as unassigned
            return ""
        if not found.found:
            return ""
        return str((found.pg or {}).get("probe_model") or "") or UNNAMED_ASSIGNMENT

    def probe_rows(self) -> list[str]:
        """The right list's labels, one per probe."""
        rows: list[str] = []
        for probe in self.probes:
            try:
                label = str(probe.elementstring())
            except Exception:  # noqa: BLE001
                label = type(probe).__name__
            channels = channelCount(probe)
            if channels is not None:
                label = f"{label} ({channels})"
            model = self.assigned_geometry_label(probe)
            if model:
                label = f"{label} *{model}*"
            rows.append(label)
        return rows

    def geometry_index_for_model(self, model: str) -> int | None:
        """Which library layout has PROBE_MODEL, or None.

        This is what lets selecting a probe highlight its geometry. Matching on
        probe_model rather than on the library name is deliberate: the name is
        where the file sits, the model is what the layout claims to be, and a
        document records the latter.
        """
        if not model:
            return None
        for index, candidate in enumerate(self.geometry_models):
            if candidate == model:
                return index
        return None

    def assign(self, name: str, probe_index: int) -> dict[str, Any]:
        """Assign library layout NAME to the probe at PROBE_INDEX, and save it.

        Returns the ``info`` from :func:`ndi.fun.probe.geometry.from_struct` --
        the site/channel count check the caller shows the user. Raises whatever
        the assignment raised; the handler reports it.
        """
        probe = self.probes[probe_index]
        _, _, info = geometry.from_library(self.session, probe, name, replace=True, verbose=0)
        return info

    def window_title(self) -> str:
        """MATLAB's window name: the app, then which session it is editing."""
        try:
            reference = str(self.session.reference or "")
        except Exception:  # noqa: BLE001
            reference = ""
        return f"Electrode Map: {reference}"

    # ------------------------------------------------------------------
    # Qt construction
    # ------------------------------------------------------------------
    def build(self) -> Any:
        from PySide6 import QtCore, QtWidgets

        from .._qt_helpers import get_or_create_app

        get_or_create_app()
        colors = cloud_colors()
        navy = rgb_to_hex(colors.dark_blue)
        white = rgb_to_hex(colors.white)
        accent = rgb_to_hex(colors.light_blue)

        self.figure = QtWidgets.QWidget()
        self.figure.setObjectName(WINDOW_TAG)
        self.figure.setWindowTitle(self.window_title())
        x, y, width, height = DEFAULT_POSITION
        self.figure.setGeometry(x, y, width, height)
        self.figure.setStyleSheet(f"background-color: {navy};")

        root = QtWidgets.QVBoxLayout(self.figure)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.title_label = QtWidgets.QLabel(TITLE_TEXT)
        self.title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet(f"color: {white}; font-size: 16px; font-weight: bold;")
        root.addWidget(self.title_label)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(8)
        root.addLayout(body, 1)

        list_style = f"background-color: {white}; color: {navy};"
        header_style = f"color: {white}; font-weight: bold;"
        button_style = f"background-color: {accent}; color: {navy};"

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(6)
        left_header = QtWidgets.QLabel("Electrode Geometries")
        left_header.setStyleSheet(header_style)
        left.addWidget(left_header)

        self.geometry_list = QtWidgets.QListWidget()
        self.geometry_list.setStyleSheet(list_style)
        self.geometry_list.addItems(self.geometry_labels)
        self.geometry_list.currentRowChanged.connect(lambda _row: self.update_button_state())
        left.addWidget(self.geometry_list, 1)

        self.plot_button = QtWidgets.QPushButton("Plot geometry")
        self.plot_button.setStyleSheet(button_style)
        self.plot_button.setToolTip("Plot the selected electrode geometry")
        self.plot_button.clicked.connect(self.plot_selected_geometry)
        left.addWidget(self.plot_button)
        body.addLayout(left, 1)

        center = QtWidgets.QVBoxLayout()
        center.addStretch(1)
        self.assign_button = QtWidgets.QPushButton("→")
        self.assign_button.setStyleSheet(f"{button_style} font-size: 22px; font-weight: bold;")
        self.assign_button.setToolTip("Assign the selected geometry to the selected probe")
        self.assign_button.setFixedSize(90, 44)
        self.assign_button.clicked.connect(self.assign_selected)
        center.addWidget(self.assign_button)
        center.addStretch(1)
        body.addLayout(center)

        right = QtWidgets.QVBoxLayout()
        right.setSpacing(6)
        right_header = QtWidgets.QLabel("n-trode Probes")
        right_header.setStyleSheet(header_style)
        right.addWidget(right_header)

        self.probe_list = QtWidgets.QListWidget()
        self.probe_list.setStyleSheet(list_style)
        self.probe_list.currentRowChanged.connect(lambda _row: self.on_probe_selected())
        right.addWidget(self.probe_list, 1)
        body.addLayout(right, 1)

        self.refresh_probe_list()
        self.update_button_state()
        self.figure.show()
        return self.figure

    # ------------------------------------------------------------------
    # handlers
    # ------------------------------------------------------------------
    def refresh_probe_list(self) -> list[str]:
        """Rebuild the right list, keeping the selected row where it still exists."""
        rows = self.probe_rows()
        if self.probe_list is None:
            return rows
        previous = self.probe_list.currentRow()
        self.probe_list.blockSignals(True)
        self.probe_list.clear()
        self.probe_list.addItems(rows)
        if 0 <= previous < len(rows):
            self.probe_list.setCurrentRow(previous)
        self.probe_list.blockSignals(False)
        self.update_button_state()
        return rows

    def selected_geometry(self) -> str | None:
        """The selected library name, or None."""
        if self.geometry_list is None:
            return None
        row = self.geometry_list.currentRow()
        if 0 <= row < len(self.geometry_names):
            return self.geometry_names[row]
        return None

    def selected_probe_index(self) -> int | None:
        """The selected probe's index, or None."""
        if self.probe_list is None:
            return None
        row = self.probe_list.currentRow()
        if 0 <= row < len(self.probes):
            return row
        return None

    def on_probe_selected(self) -> None:
        """Highlight the geometry the selected probe already has, if any."""
        index = self.selected_probe_index()
        if index is not None:
            model = self.assigned_geometry_label(self.probes[index])
            match = self.geometry_index_for_model(model)
            if match is not None and self.geometry_list is not None:
                self.geometry_list.setCurrentRow(match)
        self.update_button_state()

    def update_button_state(self) -> None:
        """Assign needs both selections; Plot needs only a geometry."""
        has_geometry = self.selected_geometry() is not None
        has_probe = self.selected_probe_index() is not None
        if self.assign_button is not None:
            self.assign_button.setEnabled(has_geometry and has_probe)
        if self.plot_button is not None:
            self.plot_button.setEnabled(has_geometry)

    def plot_selected_geometry(self) -> Any:
        """Open a plot of the selected geometry."""
        name = self.selected_geometry()
        if name is None:
            return None
        try:
            handles = geometry.plot(name)
        except Exception as exc:  # noqa: BLE001
            self.alert(str(exc), "Plot failed")
            return None
        self.show_plot()
        return handles

    @staticmethod
    def show_plot() -> None:
        """Put the figure on screen.

        Its own method so a test can plot without a window manager, and because
        MATLAB's ``figure`` shows itself while matplotlib's does not.
        """
        import matplotlib.pyplot as plt

        plt.show(block=False)

    def assign_selected(self) -> dict[str, Any] | None:
        """Assign the selected geometry to the selected probe."""
        name = self.selected_geometry()
        index = self.selected_probe_index()
        if name is None or index is None:
            return None

        try:
            info = self.assign(name, index)
        except Exception as exc:  # noqa: BLE001
            self.alert(str(exc), "Assignment failed")
            return None

        self.refresh_probe_list()

        # Advisory, not a failure: the assignment is already saved. MATLAB
        # warns to the command window as well; a user in a GUI never sees that.
        if info.get("channel_mismatch"):
            self.alert(str(info.get("message", "")), "Channel count mismatch")
        return info

    def alert(self, message: str, title: str) -> None:
        """Report MESSAGE to the user.

        A method rather than an inline dialog so a test can watch what the
        window would have said without a message box to dismiss.
        """
        from PySide6 import QtWidgets

        box = QtWidgets.QMessageBox(self.figure)
        box.setWindowTitle(title)
        box.setText(message)
        box.exec()
