"""ndi.gui.nav.update_dialog - the package table shown by the Update button.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/updateDialog.m``

A modal window listing each package ``ndi.update.install`` looks at (see
:func:`ndi.update.packageStatus`) for an ``ndi.update.check`` result. For
each package the table shows a tick box saying whether to update it, its
installed and latest version, its status, and its most serious note:

* info    - something to know (restart NDI, a package skipped)
* warning - updating touches your work (edits stashed and put back, local
  commits merged)
* error   - the update cannot go ahead until you act (an untracked file in
  the way, NDI-python not on main)

Selecting a row shows its notes and the files they are about in the box
under the table. Only ticked packages are updated. Packages that need
updating start ticked, except those where updating touches your own work;
packages that are up to date or blocked cannot be ticked. The Update button
names how many packages are ticked and is greyed out when none are; it reads
"Update anyway" when a ticked package has your changes, and Cancel is then
the default.

What the window shows is decided by the module-level functions
(:func:`table_data`, :func:`note_text`, :func:`update_button_state`), which
need no Qt, the split ``ndi.gui.nav`` makes elsewhere.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "COLUMNS",
    "UpdateDialog",
    "ask",
    "note_text",
    "table_data",
    "update_button_state",
]

#: Column titles, as MATLAB's updateDialog.Columns.
COLUMNS = ["Update", "Package", "Installed", "Latest", "Status", "Notes"]

_ORDER = ["info", "warning", "error"]


def note_text(row: dict[str, Any]) -> str:
    """Notes-column text for ROW: its most serious note, and how many more."""
    if not row["Notes"]:
        return ""
    k = max(range(len(row["Notes"])), key=lambda i: _ORDER.index(row["NoteLevels"][i]))
    txt = row["Notes"][k]
    if len(row["Notes"]) > 1:
        txt = f"{txt} (+{len(row['Notes']) - 1} more)"
    return txt


def table_data(rows: list[dict[str, Any]], selected: list[bool]) -> list[list[Any]]:
    """The table's cells for ROWS, ticked as SELECTED (one list per row)."""
    return [
        [bool(sel), r["Name"], r["Installed"], r["Latest"], r["Status"], note_text(r)]
        for r, sel in zip(rows, selected)
    ]


def update_button_state(rows: list[dict[str, Any]], selected: list[bool]) -> tuple[str, bool]:
    """Text and enabled state of the Update button.

    ``"Update (N)"`` for N ticked packages, ``"Update anyway (N)"`` if a
    ticked package has your changes, and greyed out for none.
    """
    n = sum(bool(s) for s in selected)
    if n == 0:
        return "Update", False
    if any(s and r["TouchesChanges"] for r, s in zip(rows, selected)):
        return f"Update anyway ({n})", True
    return f"Update ({n})", True


def ask(result: dict[str, Any], parent: Any = None) -> tuple[bool, list[str]]:
    """Open the dialog and wait for it to close.

    Returns ``(go, packages)``: ``go`` is True if the user pressed Update, and
    ``packages`` names the ticked packages (for ``ndi.update.install``'s
    ``Packages``).
    """
    dialog = UpdateDialog(result, parent=parent)
    dialog.exec()
    return dialog.choice == "update", dialog.selected_packages()


class UpdateDialog:
    """The modal package table (a ``QDialog``, built on construction).

    MATLAB::

        D = ndi.gui.nav.updateDialog(RESULT, 'Parent', FIG)

    Attributes:
        rows, summary: What :func:`ndi.update.packageStatus` returned.
        selected: Which rows are ticked.
        choice: ``"update"`` once Update is pressed, else ``"cancel"``.
        dialog, table, details, update_button, cancel_button: The widgets.
    """

    def __init__(self, result: dict[str, Any], parent: Any = None):
        from ...update import packageStatus

        self.rows, self.summary = packageStatus(result)
        self.selected = [r["Selected"] for r in self.rows]
        self.choice = "cancel"
        self._building = True
        self._build(parent)
        self._building = False

    # -- the operations MATLAB's methods expose --------------------------

    def set_selected(self, row: int, tf: bool) -> None:
        """Tick (TF true) or untick table row ROW (0-based).

        A row that cannot be updated stays unticked.
        """
        from PySide6 import QtCore

        tf = bool(tf) and self.rows[row]["Selectable"]
        self.selected[row] = tf
        item = self.table.item(row, 0)
        if item is not None:
            self._building = True
            item.setCheckState(
                QtCore.Qt.CheckState.Checked if tf else QtCore.Qt.CheckState.Unchecked
            )
            self._building = False
        self._refresh_update_button()

    def selected_packages(self) -> list[str]:
        """Names of the ticked packages."""
        return [r["Name"] for r, s in zip(self.rows, self.selected) if s]

    def show_details(self, row: int) -> None:
        """Show the notes and files of table row ROW (0-based)."""
        if 0 <= row < len(self.rows):
            self.details.setPlainText(self.rows[row]["Details"])

    def choose(self, choice: str) -> None:
        """Record the user's CHOICE (``"update"`` or ``"cancel"``) and close."""
        self.choice = choice
        if choice == "update":
            self.dialog.accept()
        else:
            self.dialog.reject()

    def exec(self) -> int:
        """Show the window modally and wait for it to close."""
        return self.dialog.exec()

    # -- MATLAB's property names -------------------------------------------

    #: Column titles (MATLAB's constant Columns).
    Columns = COLUMNS

    @property
    def Rows(self) -> list[dict[str, Any]]:  # noqa: N802 (MATLAB name)
        """The rows from :func:`ndi.update.packageStatus`."""
        return self.rows

    @property
    def Summary(self) -> dict[str, Any]:  # noqa: N802 (MATLAB name)
        """The summary from :func:`ndi.update.packageStatus`."""
        return self.summary

    @property
    def Selected(self) -> list[bool]:  # noqa: N802 (MATLAB name)
        """Which rows are ticked."""
        return self.selected

    @property
    def Choice(self) -> str:  # noqa: N802 (MATLAB name)
        """``"update"`` once Update is pressed, else ``"cancel"``."""
        return self.choice

    @property
    def Figure(self) -> Any:  # noqa: N802 (MATLAB name)
        """The window (a ``QDialog``; MATLAB's uifigure)."""
        return self.dialog

    @property
    def Table(self) -> Any:  # noqa: N802 (MATLAB name)
        """The package table (a ``QTableWidget``)."""
        return self.table

    @property
    def DetailsArea(self) -> Any:  # noqa: N802 (MATLAB name)
        """The read-only box with the selected row's details."""
        return self.details

    @property
    def UpdateButton(self) -> Any:  # noqa: N802 (MATLAB name)
        """The "Update (N)" / "Update anyway (N)" button."""
        return self.update_button

    @property
    def CancelButton(self) -> Any:  # noqa: N802 (MATLAB name)
        """The "Cancel" / "Close" button."""
        return self.cancel_button

    # -- construction ------------------------------------------------------

    def _build(self, parent: Any) -> None:
        from PySide6 import QtCore, QtGui, QtWidgets

        from ..cloud_colors import cloud_colors, rgb_to_hex

        c = cloud_colors()
        dlg = QtWidgets.QDialog(parent)
        dlg.setWindowTitle("NDI Update")
        dlg.setObjectName("ndiNavigatorUpdate")
        dlg.setModal(True)
        dlg.resize(780, 460)
        dlg.setStyleSheet(f"QDialog {{ background-color: {rgb_to_hex(c.dark_blue)}; }}")
        self.dialog = dlg
        layout = QtWidgets.QVBoxLayout(dlg)

        message = QtWidgets.QLabel(self.summary["Message"])
        message.setWordWrap(True)
        message.setStyleSheet(f"color: {rgb_to_hex(c.white)}; font-weight: bold;")
        layout.addWidget(message)

        table = QtWidgets.QTableWidget(len(self.rows), len(COLUMNS))
        table.setObjectName("ndiUpdateTable")
        table.setHorizontalHeaderLabels(COLUMNS)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        colors = {
            "info": c.light_blue,
            "warning": c.warn_amber,
            "error": (0.8, 0.1, 0.1),
        }
        style = dlg.style()
        icons = {
            "info": style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxInformation),
            "warning": style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning),
            "error": style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxCritical),
        }
        for i, cells in enumerate(table_data(self.rows, self.selected)):
            r = self.rows[i]
            for j, value in enumerate(cells):
                if j == 0:
                    item = QtWidgets.QTableWidgetItem()
                    flags = QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
                    if r["Selectable"]:
                        flags |= QtCore.Qt.ItemFlag.ItemIsUserCheckable
                    item.setFlags(flags)
                    item.setCheckState(
                        QtCore.Qt.CheckState.Checked if value else QtCore.Qt.CheckState.Unchecked
                    )
                else:
                    item = QtWidgets.QTableWidgetItem(str(value))
                # Bold the packages that can be updated.
                if r["WillUpdate"]:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                if j == 4 and r["Status"] == "Up to date":
                    item.setForeground(QtGui.QColor(rgb_to_hex(c.ok_green)))
                if j == len(COLUMNS) - 1 and r["NoteLevel"]:
                    item.setIcon(icons[r["NoteLevel"]])
                    item.setForeground(QtGui.QColor(rgb_to_hex(colors[r["NoteLevel"]])))
                table.setItem(i, j, item)
        header = table.horizontalHeader()
        for j, width in enumerate([55, 170, 75, 75, 130]):
            table.setColumnWidth(j, width)
        header.setStretchLastSection(True)
        table.itemChanged.connect(self._on_item_changed)
        table.currentCellChanged.connect(lambda row, *_: self.show_details(row))
        self.table = table
        layout.addWidget(table, 1)

        details = QtWidgets.QPlainTextEdit("Select a package to see its notes.")
        details.setObjectName("ndiUpdateDetails")
        details.setReadOnly(True)
        details.setFixedHeight(110)
        self.details = details
        layout.addWidget(details)
        # Start on the package that most needs reading.
        first = next((i for i, r in enumerate(self.rows) if r["Blocked"]), None)
        if first is None:
            first = next(
                (i for i, r in enumerate(self.rows) if r["Notes"] and r["WillUpdate"]), None
            )
        if first is not None:
            self.show_details(first)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.update_button = QtWidgets.QPushButton("Update")
        self.update_button.setObjectName("ndiUpdateGo")
        self.update_button.setStyleSheet(
            f"background-color: {rgb_to_hex(c.light_blue)}; color: {rgb_to_hex(c.dark_blue)};"
        )
        self.update_button.clicked.connect(lambda: self.choose("update"))
        self.cancel_button = QtWidgets.QPushButton(
            "Cancel" if self.summary["AnyUpdate"] else "Close"
        )
        self.cancel_button.setObjectName("ndiUpdateCancel")
        self.cancel_button.setStyleSheet(
            f"background-color: {rgb_to_hex(c.white)}; color: {rgb_to_hex(c.dark_blue)};"
        )
        self.cancel_button.clicked.connect(lambda: self.choose("cancel"))
        buttons.addWidget(self.update_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self._refresh_update_button()

    def _refresh_update_button(self) -> None:
        text, enabled = update_button_state(self.rows, self.selected)
        self.update_button.setText(text)
        self.update_button.setEnabled(enabled)
        # Enter should not stash someone's work: Cancel is the default then.
        touches = any(s and r["TouchesChanges"] for r, s in zip(self.rows, self.selected))
        default = self.cancel_button if (not enabled or touches) else self.update_button
        self.update_button.setDefault(default is self.update_button)
        self.cancel_button.setDefault(default is self.cancel_button)

    def _on_item_changed(self, item: Any) -> None:
        # A tick box changed. Rows that cannot be updated snap back.
        if self._building or item.column() != 0:
            return
        from PySide6 import QtCore

        row = item.row()
        self.set_selected(row, item.checkState() == QtCore.Qt.CheckState.Checked)
        if not self.rows[row]["Selectable"]:
            self.show_details(row)
