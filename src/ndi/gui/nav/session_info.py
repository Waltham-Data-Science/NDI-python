"""ndi.gui.nav.session_info - a vital-statistics window for one session.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/sessionInfo.m``

Summarises a session: its DAQ systems (each epoch one row), its elements
(display string and type), and its subjects. The target of the navigator's
per-session "Session > Info..." menu item.

The window reads the session once, at construction. Every read is wrapped
defensively so a session that cannot answer one query still shows the rest --
an info window that renders nothing because one of three lookups failed is
worse than one that renders two thirds. The row builders are separate from
the widget construction, so what the window will SAY is testable without a
display; only how it looks is not.
"""

from __future__ import annotations

from typing import Any

from ..cloud_colors import cloud_colors, rgb_to_hex

__all__ = ["SessionInfo"]

#: Shown when a section has nothing to report. Distinguishable from a real
#: empty string in a row, which would mean "this field was blank".
NO_DAQ = "(no DAQ systems)"
NONE_ROW = "(none)"
NO_ID = "(no id)"
UNNAMED_SESSION = "(unnamed session)"
UNNAMED_DAQ = "(unnamed DAQ system)"


class SessionInfo:
    """A window summarising one session.

    Constructing it reads the session; :meth:`build` creates the widgets.
    They are separate so the reading can be tested on its own.
    """

    def __init__(self, session: Any, *, build: bool = True):
        self.session = session
        self.figure: Any = None
        if build:
            self.build()

    # ------------------------------------------------------------------
    # reading the session -- no Qt in this section
    # ------------------------------------------------------------------
    def session_ref(self) -> str:
        """A human-readable session reference, best effort."""
        try:
            ref = str(self.session.reference or "")
        except Exception:  # noqa: BLE001 - a session that cannot say is not fatal
            ref = ""
        return ref or UNNAMED_SESSION

    def daq_systems(self) -> list[Any]:
        """The session's DAQ system objects."""
        try:
            daqs = self.session.daqsystem_load(name="(.*)")
        except Exception:  # noqa: BLE001
            return []
        if daqs is None:
            return []
        return list(daqs) if isinstance(daqs, (list, tuple)) else [daqs]

    @staticmethod
    def daq_name(d: Any) -> str:
        """A display name for a DAQ system, best effort."""
        try:
            name = str(d.name or "")
        except Exception:  # noqa: BLE001
            name = type(d).__name__
        return name or UNNAMED_DAQ

    def daq_rows(self) -> list[tuple[str, Any, str]]:
        """Rows of (DAQ system, epoch number, epoch id), one per epoch.

        A DAQ system with no epochs still gets a row, with blank epoch
        entries -- otherwise a system that failed to enumerate its epochs
        would vanish from the window entirely, which reads as "there is no
        such DAQ system" rather than "it has no epochs".
        """
        daqs = self.daq_systems()
        if not daqs:
            return [(NO_DAQ, "", "")]

        rows: list[tuple[str, Any, str]] = []
        for d in daqs:
            name = self.daq_name(d)
            try:
                et = d.epochtable()
                if isinstance(et, tuple):
                    et = et[0]
            except Exception:  # noqa: BLE001
                et = None
            if not et:
                rows.append((name, "", ""))
                continue
            for k, entry in enumerate(et, start=1):
                number = entry.get("epoch_number") or k
                eid = str(entry.get("epoch_id") or "") or NO_ID
                rows.append((name, number, eid))
        return rows

    def element_rows(self) -> list[tuple[str, str]]:
        """Rows of (element string, type).

        The first column uses ``elementstring`` ("name | reference") so the
        reference is shown, not just the name; the name alone is the fallback
        when that call fails.
        """
        try:
            elements = self.session.getelements()
        except Exception:  # noqa: BLE001
            elements = []

        rows: list[tuple[str, str]] = []
        for e in elements or []:
            try:
                name = str(e.elementstring())
            except Exception:  # noqa: BLE001
                try:
                    name = str(e.name)
                except Exception:  # noqa: BLE001
                    name = ""
            try:
                etype = str(e.type)
            except Exception:  # noqa: BLE001
                etype = ""
            rows.append((name, etype))
        return rows or [(NONE_ROW, "")]

    def subject_rows(self) -> list[tuple[str, str]]:
        """Rows of (local identifier, description) for the session's subjects."""
        from ...query import ndi_query

        try:
            docs = self.session.database_search(ndi_query("").isa("subject"))
        except Exception:  # noqa: BLE001
            docs = []

        rows: list[tuple[str, str]] = []
        for doc in docs or []:
            identifier = description = ""
            try:
                s = doc.document_properties.get("subject", {}) or {}
                identifier = str(s.get("local_identifier", "") or "")
                description = str(s.get("description", "") or "")
            except Exception:  # noqa: BLE001
                pass
            rows.append((identifier, description))
        return rows or [(NONE_ROW, "")]

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build(self) -> Any:
        """Create the window and populate every section."""
        from .._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtWidgets

        c = cloud_colors()
        navy = rgb_to_hex(c.dark_blue)

        self.figure = QtWidgets.QWidget()
        self.figure.setWindowTitle(f"Session: {self.session_ref()}")
        self.figure.setObjectName("ndiNavigatorSessionInfo")
        self.figure.resize(460, 520)
        self.figure.setStyleSheet(f"background-color: {navy};")

        layout = QtWidgets.QVBoxLayout(self.figure)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        self._section(layout, "DAQ systems")
        layout.addWidget(
            self._table(["DAQ system", "Epoch number", "Epoch id"], self.daq_rows()), 1
        )
        self._section(layout, "Elements")
        layout.addWidget(self._table(["Element", "Element type"], self.element_rows()), 1)
        self._section(layout, "Subjects")
        layout.addWidget(self._table(["Subject", "Description"], self.subject_rows()), 1)
        return self.figure

    def _section(self, layout: Any, text: str) -> None:
        """A small bold heading above a section."""
        from PySide6 import QtWidgets

        c = cloud_colors()
        label = QtWidgets.QLabel(text)
        label.setStyleSheet(f"color: {rgb_to_hex(c.white)}; font-weight: bold;")
        layout.addWidget(label)

    def _table(self, headers: list[str], rows: list[tuple]) -> Any:
        """A white table body with dark-navy text, per the palette."""
        from PySide6 import QtWidgets

        c = cloud_colors()
        table = QtWidgets.QTableWidget(len(rows), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setStyleSheet(
            f"background-color: {rgb_to_hex(c.white)}; color: {rgb_to_hex(c.dark_blue)};"
        )
        for r, row in enumerate(rows):
            for col, value in enumerate(row):
                table.setItem(r, col, QtWidgets.QTableWidgetItem(str(value)))
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def __repr__(self) -> str:
        return f"SessionInfo(session={self.session_ref()!r})"
