"""ndi.gui.nav.cloud_dataset_browser - browse, open and delete your NDI Cloud datasets.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/cloudDatasetBrowser.m``
(VH-Lab/NDI-matlab#1231)

Lists every NDI Cloud dataset in every organization the signed-in user
belongs to, with Name, Organization, Documents, Files, Created and Last
changed. "Created" is when the dataset was created on NDI Cloud, which is
when its first documents were added; "Last changed" is its last update time.
Selecting a row shows the details, including the cloud dataset id with a
Copy button; counts or dates the list did not include are then fetched with
:func:`ndi.cloud.api.datasets.getDataset`.

"Sort by" orders the list by any column, either direction; Refresh reloads.

OPEN hands the selected dataset to the ``open_fcn`` callback (the navigator
downloads its documents into a folder and adds it, as "Open Private Cloud
dataset..." does).

DELETE asks first, in a dialog built to be hard to click through: it names
the dataset, id and organization, when it was created and how many documents
and files it has, and keeps Delete disabled until the user ticks "I
understand..." and types the dataset's name. For a dataset in a group
organization a second box must be ticked too: "This is in a group
organization. Are you sure you want to delete it?" Deletion calls
:func:`ndi.cloud.api.datasets.deleteDataset` with its default ``when="7d"``,
so the dataset can be restored with ``undeleteDataset`` for 7 days.

NDI Cloud does not currently say directly whether an organization is a
personal one; see :meth:`CloudDatasetBrowser.is_group_organization`.

The decisions are the static methods, tested without a display.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

from ..cloud_colors import cloud_colors, rgb_to_hex
from .datasets_text import first_field, normalize_cloud_list

__all__ = ["CloudDatasetBrowser", "COLUMN_NAMES"]

#: The table's columns, in order; also the "Sort by" choices.
COLUMN_NAMES = ["Name", "Organization", "Documents", "Files", "Created", "Last changed"]


class CloudDatasetBrowser:
    """The "Browse my Cloud datasets..." window."""

    def __init__(
        self,
        *,
        open_fcn: Callable[[str, str], Any] | None = None,
        parent: Any = None,
        build: bool = True,
        load: bool = True,
    ):
        self.open_fcn = open_fcn
        self.entries: list[dict[str, Any]] = []
        self.organizations: list[dict[str, Any]] = []
        self.selected_index: int | None = None
        self.sort_column = "Name"
        self.sort_descending = False

        self.figure: Any = None
        self.table: Any = None
        self.details: Any = None
        self.id_field: Any = None
        self.id_copy_button: Any = None
        self.open_button: Any = None
        self.delete_button: Any = None
        self.status_label: Any = None
        self.sort_dir_button: Any = None
        if build:
            self.build(parent)
            if load:
                self.refresh()

    # ------------------------------------------------------------------
    # what the window says -- no Qt
    # ------------------------------------------------------------------
    @staticmethod
    def to_count(value: Any) -> float:
        """A count from a record field; NaN when absent or unreadable."""
        if isinstance(value, bool):
            return math.nan
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip():
            try:
                return float(value)
            except ValueError:
                return math.nan
        return math.nan

    @staticmethod
    def entry_from_record(record: Any) -> dict[str, Any]:
        """One dataset record (from listDatasets or getDataset) -> entry."""

        def f(names: list[str]) -> Any:
            if not isinstance(record, Mapping):
                return ""
            for name in names:
                value = record.get(name)
                if value not in (None, ""):
                    return value
            return ""

        entry = {
            "id": str(first_field(record, ["id", "_id", "x_id", "datasetId"]) or ""),
            "name": str(f(["name", "datasetName", "branchName"]) or ""),
            "organizationId": str(f(["organizationId", "organization"]) or ""),
            "organizationName": str(f(["organizationName"]) or ""),
            "documentCount": CloudDatasetBrowser.to_count(
                f(["documentCount", "numberOfDocuments"])
            ),
            "fileCount": CloudDatasetBrowser.to_count(f(["fileCount", "numberOfFiles"])),
            "createdAt": str(f(["createdAt", "created"]) or ""),
            "updatedAt": str(f(["updatedAt", "lastModified", "modifiedAt"]) or ""),
        }
        if not entry["name"]:
            entry["name"] = entry["id"]
        entry["detailed"] = (
            not math.isnan(entry["documentCount"])
            and not math.isnan(entry["fileCount"])
            and bool(entry["createdAt"])
            and bool(entry["updatedAt"])
        )
        return entry

    @staticmethod
    def entries_from_list(answer: Any) -> list[dict[str, Any]]:
        """A listDatasets answer -> entries, dropping records without an id."""
        answer = getattr(answer, "data", answer)
        entries = [CloudDatasetBrowser.entry_from_record(r) for r in normalize_cloud_list(answer)]
        return [e for e in entries if e["id"]]

    @staticmethod
    def merge_entry(entry: dict[str, Any], full: dict[str, Any]) -> dict[str, Any]:
        """ENTRY with its missing values filled from FULL."""
        out = dict(entry)
        for key in ("name", "organizationId", "organizationName", "createdAt", "updatedAt"):
            if not out.get(key) and full.get(key):
                out[key] = full[key]
        for key in ("documentCount", "fileCount"):
            if math.isnan(out.get(key, math.nan)):
                out[key] = full.get(key, math.nan)
        return out

    @staticmethod
    def sort_entries(
        entries: list[dict[str, Any]], column: str, descending: bool = False
    ) -> list[dict[str, Any]]:
        """ENTRIES ordered by COLUMN (stable). Unknown values sort last either way."""
        if not entries or not column:
            return list(entries)
        keys = {
            "Name": ("name", True),
            "Organization": ("organizationName", True),
            "Created": ("createdAt", False),
            "Last changed": ("updatedAt", False),
            "Documents": ("documentCount", False),
            "Files": ("fileCount", False),
        }
        if column not in keys:
            raise ValueError(f"Unknown column {column!r}. Use one of: {', '.join(COLUMN_NAMES)}.")
        field, fold = keys[column]

        def missing(e: dict[str, Any]) -> bool:
            v = e.get(field)
            return v in (None, "") or (isinstance(v, float) and math.isnan(v))

        known = [e for e in entries if not missing(e)]
        unknown = [e for e in entries if missing(e)]

        def key(e: dict[str, Any]) -> Any:
            v = e[field]
            return v.lower() if fold and isinstance(v, str) else v

        # sorted() is stable, and reverse=True keeps ties in their original
        # order, so ties never shuffle in either direction.
        return sorted(known, key=key, reverse=descending) + unknown

    @staticmethod
    def entries_to_rows(entries: list[dict[str, Any]]) -> list[list[str]]:
        """Table text, one row per entry."""
        b = CloudDatasetBrowser
        return [
            [
                e["name"],
                e["organizationName"],
                b.count_text(e["documentCount"]),
                b.count_text(e["fileCount"]),
                b.date_text(e["createdAt"]),
                b.date_text(e["updatedAt"]),
            ]
            for e in entries
        ]

    @staticmethod
    def details_text(entry: dict[str, Any], is_group: bool) -> list[str]:
        """The facts about one dataset, one per line."""
        b = CloudDatasetBrowser
        org_kind = "group organization" if is_group else "your own organization"
        org = entry.get("organizationName") or "(unknown)"
        return [
            f"Name:          {entry['name']}",
            f"Cloud ID:      {entry['id']}",
            f"Organization:  {org} ({org_kind})",
            f"Created:       {b.date_text(entry['createdAt'])}",
            f"Last changed:  {b.date_text(entry['updatedAt'])}",
            f"Documents:     {b.count_text(entry['documentCount'])}",
            f"Files:         {b.count_text(entry['fileCount'])}",
        ]

    @staticmethod
    def date_text(value: str) -> str:
        """'2024-05-01T12:34:56.789Z' -> '2024-05-01 12:34 UTC'."""
        value = str(value or "")
        if not value:
            return "(unknown)"
        if len(value) >= 16 and value[10] == "T":
            return f"{value[:10]} {value[11:16]} UTC"
        return value

    @staticmethod
    def count_text(n: Any) -> str:
        if n is None or (isinstance(n, float) and math.isnan(n)):
            return "(unknown)"
        return str(int(round(n)))

    @staticmethod
    def delete_allowed(
        name: str, typed_name: str, understood: bool, is_group: bool, group_confirmed: bool
    ) -> bool:
        """True when every delete confirmation is satisfied.

        The typed name must match NAME exactly (surrounding spaces ignored),
        "I understand" must be ticked, and for a group organization the group
        box must be ticked too.
        """
        name = str(name or "").strip()
        return (
            bool(understood)
            and bool(name)
            and str(typed_name or "").strip() == name
            and (not is_group or bool(group_confirmed))
        )

    @staticmethod
    def is_group_organization(org: Mapping[str, Any] | None) -> bool:
        """True unless ORG is known to be a personal organization.

        NDI Cloud's organization records (id, name, canUploadDataset) do not
        currently say whether an organization is personal. Whichever of these
        fields is present decides, in order: ``isPersonal``/``personal``
        (personal when true), ``type`` (personal when ``"personal"``),
        ``memberCount`` (personal when 1 or fewer). Otherwise the organization
        is treated as a group, so the extra confirmation is shown rather than
        skipped when unsure.
        """
        if not isinstance(org, Mapping) or not org:
            return True
        for key in ("isPersonal", "personal"):
            if org.get(key) is not None and org.get(key) != "":
                return not bool(org[key])
        if org.get("type"):
            return str(org["type"]).lower() != "personal"
        if org.get("memberCount") is not None and org.get("memberCount") != "":
            return float(org["memberCount"]) > 1
        return True

    # ------------------------------------------------------------------
    # model actions
    # ------------------------------------------------------------------
    def set_entries(self, entries: list[dict[str, Any]]) -> None:
        """Show ENTRIES, sorted by the current sort choice."""
        self.entries = self.sort_entries(entries, self.sort_column, self.sort_descending)
        self._redraw()
        self.select(None)

    def set_sort(self, column: str, descending: bool = False) -> None:
        self.sort_column = column
        self.sort_descending = bool(descending)
        self.set_entries(self.entries)
        if self.sort_dir_button is not None:
            self.sort_dir_button.setText("Descending" if descending else "Ascending")

    def refresh(self) -> None:
        """Reload the dataset list from NDI Cloud."""
        self._set_status("Contacting NDI Cloud...")
        try:
            from ...cloud.api import datasets as datasets_api

            answer = datasets_api.listDatasets()
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self._set_status(f"Could not load datasets: {exc}")
            return
        try:
            from ...cloud.internal import getOrganizations

            self.organizations = list(getOrganizations())
        except Exception:  # noqa: BLE001 - only refines the group check
            self.organizations = []
        self.set_entries(self.entries_from_list(answer))
        self._set_status(f"{len(self.entries)} dataset(s).")

    def organization_of(self, entry: dict[str, Any]) -> dict[str, Any]:
        for org in self.organizations:
            if isinstance(org, Mapping) and str(org.get("id", "")) == entry["organizationId"]:
                return dict(org)
        return {"id": entry["organizationId"], "name": entry["organizationName"]}

    def is_group(self, entry: dict[str, Any]) -> bool:
        return self.is_group_organization(self.organization_of(entry))

    def fill_details(self, index: int) -> dict[str, Any]:
        """Fetch the counts/dates the list did not include for row INDEX."""
        entry = self.entries[index]
        if entry.get("detailed"):
            return entry
        try:
            from ...cloud.api import datasets as datasets_api

            record = datasets_api.getDataset(entry["id"])
            record = getattr(record, "data", record)
            entry = self.merge_entry(entry, self.entry_from_record(record))
        except Exception:  # noqa: BLE001 - details stay "(unknown)"
            pass
        entry["detailed"] = True
        self.entries[index] = entry
        self._redraw()
        return entry

    def select(self, index: int | None) -> None:
        """Make row INDEX current (None for none) and show its details."""
        self.selected_index = index
        has = index is not None
        for button in (self.delete_button, self.open_button, self.id_copy_button):
            if button is not None:
                button.setEnabled(has)
        if self.id_copy_button is not None:
            self.id_copy_button.setText("Copy")
        if not has:
            if self.id_field is not None:
                self.id_field.setText("")
            if self.details is not None:
                self.details.setPlainText("Select a dataset to see its details.")
            return
        entry = self.fill_details(index)
        if self.id_field is not None:
            self.id_field.setText(entry["id"])
        if self.details is not None:
            self.details.setPlainText("\n".join(self.details_text(entry, self.is_group(entry))))

    def delete_selected(self, *, confirm: Callable[[dict[str, Any], bool], bool] | None = None):
        """Delete the selected dataset after CONFIRM says yes. Returns True if deleted.

        CONFIRM is ``(entry, is_group) -> bool``; by default the Qt dialog of
        :meth:`confirm_delete`. Without a selection nothing happens.
        """
        if self.selected_index is None:
            return False
        entry = self.entries[self.selected_index]
        confirm = confirm or (lambda e, g: self.confirm_delete(e, g, self.figure))
        if not confirm(entry, self.is_group(entry)):
            self._set_status("Delete cancelled.")
            return False
        try:
            from ...cloud.api import datasets as datasets_api

            datasets_api.deleteDataset(entry["id"])
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self._alert(f"NDI Cloud did not delete the dataset: {exc}", "Delete dataset")
            return False
        self._alert(
            f'"{entry["name"]}" was deleted. NDI Cloud removes it permanently after 7 '
            "days; until then it can be restored with "
            f"ndi.cloud.api.datasets.undeleteDataset('{entry['id']}').",
            "Delete dataset",
        )
        self.refresh()
        return True

    def open_selected(self) -> Any:
        if self.selected_index is None or self.open_fcn is None:
            return None
        entry = self.entries[self.selected_index]
        return self.open_fcn(entry["id"], entry["name"])

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    @staticmethod
    def confirm_delete(entry: dict[str, Any], is_group: bool, parent: Any = None) -> bool:
        """The modal "are you really sure" dialog. True only if every check passed."""
        from PySide6 import QtWidgets

        c = cloud_colors()
        navy = rgb_to_hex(c.dark_blue)
        dialog = QtWidgets.QDialog(parent)
        dialog.setWindowTitle("Delete NDI Cloud dataset?")
        dialog.setObjectName("ndiCloudDatasetDeleteConfirm")
        dialog.setModal(True)
        layout = QtWidgets.QVBoxLayout(dialog)

        warn = QtWidgets.QLabel(
            "You are about to DELETE this dataset from NDI Cloud. Everyone who "
            "uses it will lose access to it."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #bf1a1a; font-weight: bold; font-size: 14px;")
        layout.addWidget(warn)
        note = QtWidgets.QLabel(
            "Local copies are not affected. NDI Cloud removes the dataset permanently "
            "after 7 days."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {navy};")
        layout.addWidget(note)
        facts = QtWidgets.QPlainTextEdit(
            "\n".join(CloudDatasetBrowser.details_text(entry, is_group))
        )
        facts.setReadOnly(True)
        layout.addWidget(facts)

        understand = QtWidgets.QCheckBox(
            "I understand that this deletes the dataset from NDI Cloud."
        )
        layout.addWidget(understand)
        group_box = QtWidgets.QCheckBox(
            "This is in a group organization. Are you sure you want to delete it?"
        )
        group_box.setStyleSheet("color: #bf1a1a; font-weight: bold;")
        group_box.setVisible(bool(is_group))
        layout.addWidget(group_box)
        layout.addWidget(QtWidgets.QLabel(f"Type the dataset name ({entry['name']}) to confirm:"))
        typed = QtWidgets.QLineEdit()
        layout.addWidget(typed)

        buttons = QtWidgets.QHBoxLayout()
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.setDefault(True)
        cancel.clicked.connect(dialog.reject)
        delete = QtWidgets.QPushButton("Delete dataset")
        delete.setEnabled(False)
        delete.setAutoDefault(False)
        delete.setStyleSheet("background-color: #cc2626; color: white;")
        delete.clicked.connect(dialog.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(delete)
        layout.addLayout(buttons)

        def update(*_: Any) -> None:
            delete.setEnabled(
                CloudDatasetBrowser.delete_allowed(
                    entry["name"],
                    typed.text(),
                    understand.isChecked(),
                    is_group,
                    group_box.isChecked(),
                )
            )

        understand.toggled.connect(update)
        group_box.toggled.connect(update)
        typed.textChanged.connect(update)
        cancel.setFocus()

        accepted = dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted
        return accepted and CloudDatasetBrowser.delete_allowed(
            entry["name"], typed.text(), understand.isChecked(), is_group, group_box.isChecked()
        )

    def build(self, parent: Any = None) -> Any:
        from .._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtWidgets

        c = cloud_colors()
        navy = rgb_to_hex(c.dark_blue)
        white = rgb_to_hex(c.white)
        light = rgb_to_hex(c.light_blue)

        self.figure = QtWidgets.QDialog(parent)
        self.figure.setWindowTitle("NDI Cloud Datasets")
        self.figure.setObjectName("ndiNavigatorCloudDatasetBrowser")
        self.figure.resize(900, 560)
        outer = QtWidgets.QVBoxLayout(self.figure)

        header = QtWidgets.QLabel("My NDI Cloud datasets")
        header.setStyleSheet(
            f"background-color: {navy}; color: {white}; font-weight: bold; "
            "font-size: 14px; padding: 4px 8px;"
        )
        outer.addWidget(header)

        sort_row = QtWidgets.QHBoxLayout()
        sort_row.addWidget(QtWidgets.QLabel("Sort by:"))
        sort_by = QtWidgets.QComboBox()
        sort_by.addItems(COLUMN_NAMES)
        sort_by.setCurrentText(self.sort_column)
        sort_by.currentTextChanged.connect(lambda col: self.set_sort(col, self.sort_descending))
        sort_row.addWidget(sort_by)
        self.sort_dir_button = QtWidgets.QPushButton("Ascending")
        self.sort_dir_button.setStyleSheet(f"background-color: {light}; color: {navy};")
        self.sort_dir_button.clicked.connect(
            lambda: self.set_sort(self.sort_column, not self.sort_descending)
        )
        sort_row.addWidget(self.sort_dir_button)
        sort_row.addStretch(1)
        outer.addLayout(sort_row)

        # The model is sorted (set_sort), not the widget, so a row number
        # always names the entry it shows.
        self.table = QtWidgets.QTableWidget(0, len(COLUMN_NAMES))
        self.table.setHorizontalHeaderLabels(COLUMN_NAMES)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_selection)
        outer.addWidget(self.table, 1)

        id_row = QtWidgets.QHBoxLayout()
        id_label = QtWidgets.QLabel("Cloud dataset ID:")
        id_label.setStyleSheet(f"color: {navy}; font-weight: bold;")
        id_row.addWidget(id_label)
        self.id_field = QtWidgets.QLineEdit()
        self.id_field.setReadOnly(True)
        self.id_field.setObjectName("ndiBrowserCloudId")
        id_row.addWidget(self.id_field, 1)
        self.id_copy_button = QtWidgets.QPushButton("Copy")
        self.id_copy_button.setEnabled(False)
        self.id_copy_button.clicked.connect(self._copy_id)
        id_row.addWidget(self.id_copy_button)
        outer.addLayout(id_row)

        self.details = QtWidgets.QPlainTextEdit("Select a dataset to see its details.")
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(130)
        outer.addWidget(self.details)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)
        self.open_button = QtWidgets.QPushButton("Open...")
        self.open_button.setToolTip(
            "Download this dataset's documents to a folder and add it to the Datasets list"
        )
        self.open_button.setEnabled(False)
        self.open_button.setVisible(self.open_fcn is not None)
        self.open_button.clicked.connect(self.open_selected)
        buttons.addWidget(self.open_button)
        self.delete_button = QtWidgets.QPushButton("Delete...")
        self.delete_button.setToolTip("Delete this dataset from NDI Cloud (asks first)")
        self.delete_button.setEnabled(False)
        self.delete_button.setStyleSheet("background-color: #cc2626; color: white;")
        self.delete_button.clicked.connect(lambda: self.delete_selected())
        buttons.addWidget(self.delete_button)
        outer.addLayout(buttons)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet(f"color: {navy};")
        outer.addWidget(self.status_label)
        return self.figure

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def _redraw(self) -> None:
        if self.table is None:
            return
        from PySide6 import QtWidgets

        rows = self.entries_to_rows(self.entries)
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, text in enumerate(row):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(text))
        if self.selected_index is not None and self.selected_index < len(rows):
            self.table.selectRow(self.selected_index)
        self.table.blockSignals(False)

    def _on_selection(self) -> None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        self.select(min(rows) if rows else None)

    def _copy_id(self) -> None:
        if self.id_field is None or not self.id_field.text():
            return
        from PySide6 import QtGui

        QtGui.QGuiApplication.clipboard().setText(self.id_field.text())
        self.id_copy_button.setText("Copied")

    def _set_status(self, text: str) -> None:
        if self.status_label is not None:
            self.status_label.setText(text)

    def _alert(self, message: str, title: str) -> None:
        if self.figure is None:
            return
        from PySide6 import QtWidgets

        QtWidgets.QMessageBox.information(self.figure, title, message)
