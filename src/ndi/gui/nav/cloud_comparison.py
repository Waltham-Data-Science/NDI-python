"""ndi.gui.nav.cloud_comparison - compare a local dataset with NDI Cloud, and sync.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/cloudComparison.m``

Opened from the dataset menu's "Cloud > Cloud comparison...". It is the
navigator's only way to sync: the per-operation menu items were removed
(VH-Lab/NDI-matlab#1230) so that a user always sees the state of both sides
before changing either.

WHICH COPY IS BEING COMPARED
    One cloud dataset can have several local copies, and the comparison
    depends on which one is used. The top of the window names, with Copy
    buttons, the local dataset name, the folder of THIS local copy, and the
    cloud dataset id.

THE COMPARISON
    :func:`ndi.cloud.sync.documentDifference` compares document ids only, so
    it is cheap enough to run whenever the window opens or Refresh is pressed.
    "Check content" runs :func:`ndi.cloud.sync.validate` instead; MATLAB's
    validate also flags documents present on both sides whose content
    differs. NDI-python's validate does not compare contents yet, so here the
    button reports that rather than implying the contents match.

SYNC BUTTONS
    One per :class:`ndi.cloud.sync.SyncMode`, run through
    :mod:`ndi.gui.nav.datasets_cloud`. The two Mirror buttons delete
    documents and ask first; the warning states how many documents will be
    deleted, from the current comparison. "Also sync data files" and "Dry
    run" map to ``SyncOptions.sync_files`` and ``SyncOptions.dry_run``. After
    an operation the comparison is recomputed.

What the window SAYS is decided by the static methods of
:class:`CloudComparison`, which need no display and are tested on their own.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from ..cloud_colors import cloud_colors, rgb_to_hex
from . import datasets_cloud, datasets_model
from .cloud_info_dialog import CloudInfoDialog

__all__ = ["CloudComparison", "ACTION_SPECS"]

#: The sync buttons in display order, as MATLAB's ``actionSpecs``: the MATLAB
#: sync function name, the label, the tooltip, whether it deletes, and the
#: key :mod:`datasets_cloud` runs it under.
ACTION_SPECS: list[dict[str, Any]] = [
    {
        "mode": "downloadNew",
        "label": "Download New from Cloud",
        "tooltip": "Add documents that are only in the cloud to this local copy. Deletes nothing.",
        "destructive": False,
        "key": "download_new",
    },
    {
        "mode": "uploadNew",
        "label": "Upload New to Cloud",
        "tooltip": "Add documents that are only in this local copy to the cloud. Deletes nothing.",
        "destructive": False,
        "key": "upload_new",
    },
    {
        "mode": "twoWaySync",
        "label": "Two Way Sync",
        "tooltip": "Add missing documents in both directions. Deletes nothing.",
        "destructive": False,
        "key": "two_way_sync",
    },
    {
        "mode": "mirrorFromRemote",
        "label": "Mirror from Cloud",
        "tooltip": "Make this local copy match the cloud. DELETES local-only documents.",
        "destructive": True,
        "key": "from_remote",
    },
    {
        "mode": "mirrorToRemote",
        "label": "Mirror to Cloud",
        "tooltip": "Make the cloud match this local copy. DELETES cloud-only documents.",
        "destructive": True,
        "key": "to_remote",
    },
]


class CloudComparison:
    """The Cloud comparison window for one local dataset."""

    def __init__(
        self,
        dataset: Any,
        *,
        cloud_dataset_id: str = "",
        parent: Any = None,
        build: bool = True,
        compute: bool = True,
    ):
        self.dataset = dataset
        self.dataset_name = datasets_model.dataset_label(dataset)
        self.local_path = datasets_model.dataset_path(dataset)
        if not cloud_dataset_id:
            try:
                cloud_dataset_id = datasets_cloud.resolve_cloud_target(dataset)
            except ValueError:
                cloud_dataset_id = ""
        self.cloud_dataset_id = str(cloud_dataset_id or "")
        self.report: Mapping[str, Any] | None = None
        self.content_checked = False

        self.figure: Any = None
        self.summary_label: Any = None
        self.table: Any = None
        self.status_label: Any = None
        self.sync_files_box: Any = None
        self.dry_run_box: Any = None
        self.action_buttons: list[Any] = []
        if build:
            self.build(parent)
            if compute:
                self.refresh()

    # ------------------------------------------------------------------
    # what the window says -- no Qt
    # ------------------------------------------------------------------
    @staticmethod
    def action_spec(mode: str) -> dict[str, Any]:
        """The :data:`ACTION_SPECS` entry for MODE (a MATLAB sync function name)."""
        for spec in ACTION_SPECS:
            if spec["mode"] == mode:
                return spec
        raise ValueError(f"Unknown sync mode {mode!r}.")

    @staticmethod
    def ids(report: Mapping[str, Any] | None, field: str) -> list[str]:
        """FIELD of REPORT as a list of str ([] when absent)."""
        if not isinstance(report, Mapping):
            return []
        value = report.get(field)
        if not value:
            return []
        if isinstance(value, str):
            return [value]
        return [str(v) for v in value]

    @staticmethod
    def counts(report: Mapping[str, Any] | None) -> tuple[int, int, int, float]:
        """(only in cloud, only local, in both, content differs).

        The last is NaN when the report did not compare contents.
        """
        ids = CloudComparison.ids
        n_diff: float = math.nan
        if isinstance(report, Mapping) and "mismatched_ids" in report:
            n_diff = len(ids(report, "mismatched_ids"))
        return (
            len(ids(report, "remote_only_ids")),
            len(ids(report, "local_only_ids")),
            len(ids(report, "common_ids")),
            n_diff,
        )

    @staticmethod
    def summary_text(report: Mapping[str, Any] | None) -> str:
        """One-line summary of a comparison report."""
        n_remote, n_local, n_both, n_diff = CloudComparison.counts(report)
        msg = f"Only in cloud: {n_remote}    Only local: {n_local}    In both: {n_both}"
        if not math.isnan(n_diff):
            msg += f"    Content differs: {int(n_diff)}"
        if n_remote == 0 and n_local == 0 and (math.isnan(n_diff) or n_diff == 0):
            msg += "    (in sync)"
        return msg

    @staticmethod
    def comparison_rows(report: Mapping[str, Any] | None) -> list[tuple[str, str]]:
        """(document id, where) rows: cloud-only, local-only, differing, then both."""
        ids = CloudComparison.ids
        remote = ids(report, "remote_only_ids")
        local = ids(report, "local_only_ids")
        both = ids(report, "common_ids")
        diffs = ids(report, "mismatched_ids")
        differing = set(diffs)
        same = [d for d in both if d not in differing]
        return (
            [(d, "Only in cloud") for d in remote]
            + [(d, "Only local") for d in local]
            + [(d, "In both - content differs") for d in diffs]
            + [(d, "In both") for d in same]
        )

    @staticmethod
    def mirror_warning(
        mode: str, report: Mapping[str, Any] | None, local_path: str, cloud_id: str
    ) -> str:
        """Confirmation text for a destructive mirror, with the deletion count."""
        local_path = local_path or "(unknown)"
        cloud_id = cloud_id or "(unknown)"
        if mode == "mirrorFromRemote":
            field = "local_only_ids"
            what = (
                f"Mirror from Cloud will make the local copy in\n{local_path}\n"
                f"an exact copy of cloud dataset {cloud_id}."
            )
            where = "from this local copy"
        elif mode == "mirrorToRemote":
            field = "remote_only_ids"
            what = (
                f"Mirror to Cloud will make cloud dataset {cloud_id}\n"
                f"an exact copy of the local copy in\n{local_path}."
            )
            where = "from the cloud dataset"
        else:
            raise ValueError(f"Only the mirror modes are destructive; got {mode!r}.")
        if report is None:
            count_text = (
                "Documents that are not on the other side will be permanently " f"DELETED {where}."
            )
        else:
            n = len(CloudComparison.ids(report, field))
            noun = "1 document" if n == 1 else f"{n} documents"
            count_text = (
                f"{noun} will be permanently DELETED {where}. (Counts are from the "
                "last comparison; press Refresh first if things may have changed.)"
            )
        return f"{what}\n\n{count_text}\n\nThis cannot be undone. Are you sure?"

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def compare(self, check_content: bool = False) -> Mapping[str, Any] | None:
        """Run the comparison and redraw. Returns the report (None on failure)."""
        if not self.cloud_dataset_id:
            self._set_summary(
                'This dataset is not linked to NDI Cloud. Use "Upload to Cloud" first.'
            )
            self._set_buttons_enabled(False)
            return None
        self._set_summary("Computing...")
        self._set_buttons_enabled(False)
        self._process_events()
        try:
            from ...cloud.sync import operations as sync_ops

            if check_content:
                report = sync_ops.validate(self.dataset, self.cloud_dataset_id)
            else:
                report = sync_ops.documentDifference(self.dataset, self.cloud_dataset_id)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self._set_summary(f"Could not compare: {exc}")
            self._set_buttons_enabled(True)
            return None
        self.report = report
        self.content_checked = bool(check_content)
        self._set_summary(self.summary_text(report))
        self._fill_table(self.comparison_rows(report))
        self._set_buttons_enabled(True)
        if check_content and "mismatched_ids" not in report:
            self._set_status("NDI-python cannot compare document contents yet; showing ids only.")
        else:
            self._set_status("Compared.")
        return report

    def refresh(self) -> Mapping[str, Any] | None:
        """Recompute the id-only comparison."""
        return self.compare(False)

    def check_content(self) -> Mapping[str, Any] | None:
        """Recompute, comparing contents too where supported."""
        return self.compare(True)

    def run_action(self, mode: str, *, confirm: Any = None) -> Any:
        """Run sync MODE (a MATLAB sync function name), then refresh.

        CONFIRM is ``(title, prompt) -> bool``; it is asked before a mirror
        unless this is a dry run, and the mirror runs only when it says yes.
        Without a CONFIRM a mirror is refused, so a destructive call cannot be
        reached without a question having been put to someone.
        """
        spec = self.action_spec(mode)
        sync_files = bool(self.sync_files_box.isChecked()) if self.sync_files_box else False
        dry_run = bool(self.dry_run_box.isChecked()) if self.dry_run_box else False
        if spec["destructive"] and not dry_run:
            prompt = self.mirror_warning(mode, self.report, self.local_path, self.cloud_dataset_id)
            if confirm is None or not confirm(spec["label"], prompt):
                self._set_status(f"{spec['label']} cancelled.")
                return None
        if spec["destructive"]:
            result = datasets_cloud.mirror_dataset(
                self.dataset, spec["key"], sync_files=sync_files, dry_run=dry_run
            )
        else:
            result = datasets_cloud.sync_dataset(
                self.dataset, spec["key"], sync_files=sync_files, dry_run=dry_run
            )
        self._set_status(f"{spec['label']}: {result.message.replace(chr(10), ', ')}")
        if not dry_run:
            self.refresh()
        return result

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build(self, parent: Any = None) -> Any:
        """Create the window: header, summary, table, options, sync buttons."""
        from .._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtWidgets

        c = cloud_colors()
        navy = rgb_to_hex(c.dark_blue)
        white = rgb_to_hex(c.white)
        light = rgb_to_hex(c.light_blue)

        self.figure = QtWidgets.QDialog(parent)
        self.figure.setWindowTitle("Cloud Comparison")
        self.figure.setObjectName("ndiNavigatorCloudComparison")
        self.figure.resize(760, 560)
        outer = QtWidgets.QVBoxLayout(self.figure)

        # --- header: which local copy, which cloud dataset --------------
        header = QtWidgets.QFrame()
        header.setStyleSheet(f"QFrame {{ background-color: {navy}; }}")
        grid = QtWidgets.QGridLayout(header)
        title = QtWidgets.QLabel("Comparing this local copy with its NDI Cloud dataset")
        title.setStyleSheet(f"color: {white}; font-weight: bold; font-size: 14px;")
        grid.addWidget(title, 0, 0, 1, 3)
        for row, (label, value, name) in enumerate(
            (
                ("Dataset name:", self.dataset_name, "ndiCompareName"),
                ("Local copy (this folder):", self.local_path, "ndiComparePath"),
                ("Cloud dataset ID:", self.cloud_dataset_id, "ndiCompareCloudId"),
            ),
            start=1,
        ):
            text = QtWidgets.QLabel(label)
            text.setStyleSheet(f"color: {white}; font-weight: bold;")
            grid.addWidget(text, row, 0)
            field = QtWidgets.QLineEdit(CloudInfoDialog.value_text(value))
            field.setReadOnly(True)
            field.setObjectName(name)
            field.setStyleSheet(f"background-color: {white}; color: {navy};")
            grid.addWidget(field, row, 1)
            button = QtWidgets.QPushButton("Copy")
            button.setObjectName(name + "Copy")
            button.setEnabled(bool(value))
            button.setStyleSheet(f"background-color: {light}; color: {navy};")
            button.clicked.connect(lambda _=False, v=value, b=button: self._copy(v, b))
            grid.addWidget(button, row, 2)
        outer.addWidget(header)

        # --- summary + Refresh / Check content ----------------------------
        row = QtWidgets.QHBoxLayout()
        self.summary_label = QtWidgets.QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(f"color: {navy}; font-weight: bold;")
        row.addWidget(self.summary_label, 1)
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.setToolTip("Recompute the comparison (document ids only; fast)")
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        content = QtWidgets.QPushButton("Check content")
        content.setToolTip(
            "Also compare the contents of documents on both sides "
            "(downloads the cloud documents; slower)"
        )
        content.clicked.connect(self.check_content)
        row.addWidget(content)
        outer.addLayout(row)

        # --- table ---------------------------------------------------------
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Document ID", "Where"])
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        outer.addWidget(self.table, 1)

        # --- options -------------------------------------------------------
        options = QtWidgets.QHBoxLayout()
        self.sync_files_box = QtWidgets.QCheckBox("Also sync data files")
        self.sync_files_box.setToolTip(
            "Download the binary data files as well as the documents (sync_files)"
        )
        options.addWidget(self.sync_files_box)
        self.dry_run_box = QtWidgets.QCheckBox("Dry run (preview only)")
        self.dry_run_box.setToolTip(
            "Report what the operation would do without changing anything (dry_run)"
        )
        options.addWidget(self.dry_run_box)
        options.addStretch(1)
        outer.addLayout(options)

        # --- sync buttons --------------------------------------------------
        buttons = QtWidgets.QHBoxLayout()
        self.action_buttons = []
        for spec in ACTION_SPECS:
            button = QtWidgets.QPushButton(spec["label"])
            button.setToolTip(spec["tooltip"])
            if spec["destructive"]:
                button.setStyleSheet("background-color: #d9541a; color: white;")
            else:
                button.setStyleSheet(f"background-color: {light}; color: {navy};")
            button.clicked.connect(
                lambda _=False, m=spec["mode"]: self.run_action(m, confirm=self._confirm)
            )
            buttons.addWidget(button)
            self.action_buttons.append(button)
        outer.addLayout(buttons)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setStyleSheet(f"color: {navy};")
        outer.addWidget(self.status_label)
        return self.figure

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def _confirm(self, title: str, prompt: str) -> bool:
        """Ask before a mirror. Cancel is the default."""
        from PySide6 import QtWidgets

        box = QtWidgets.QMessageBox(self.figure)
        box.setWindowTitle(title)
        box.setText(prompt)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        go = box.addButton("Delete and mirror", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is go

    def _copy(self, value: str, button: Any) -> None:
        if not value:
            return
        from PySide6 import QtGui

        QtGui.QGuiApplication.clipboard().setText(str(value))
        button.setText("Copied")

    def _fill_table(self, rows: list[tuple[str, str]]) -> None:
        if self.table is None:
            return
        from PySide6 import QtWidgets

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, (doc_id, where) in enumerate(rows):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(doc_id))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(where))
        self.table.setSortingEnabled(True)

    def _set_summary(self, text: str) -> None:
        if self.summary_label is not None:
            self.summary_label.setText(text)

    def _set_status(self, text: str) -> None:
        if self.status_label is not None:
            self.status_label.setText(text)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for button in self.action_buttons:
            button.setEnabled(bool(enabled))

    def _process_events(self) -> None:
        if self.figure is None:
            return
        from PySide6 import QtWidgets

        QtWidgets.QApplication.processEvents()
