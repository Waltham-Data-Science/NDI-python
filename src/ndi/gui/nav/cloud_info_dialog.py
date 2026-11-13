"""ndi.gui.nav.cloud_info_dialog - the result window of "Cloud info...".

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/cloudInfoDialog.m`` (formerly
``cloudStatusDialog.m``, renamed in VH-Lab/NDI-matlab#1230)

Reports whether a dataset is linked to NDI Cloud. Below the status sentence
are three read-only (selectable) rows, each with a "Copy" button:

* Dataset name - the local dataset's reference
* Local path - the folder that holds THIS local copy
* Cloud dataset ID - the NDI Cloud dataset id

When the dataset is not in the cloud there is no id: that field reads
"(not in NDI Cloud)" and its Copy is disabled. An unknown name or path reads
"(unknown)", also with Copy disabled. The path matters because one cloud
dataset can have several local copies.

What the window SAYS -- the sentence, the field texts, whether each Copy is
enabled -- is decided by the static methods, which need no display and are
tested on their own; :meth:`CloudInfoDialog.build` only lays the widgets out.
"""

from __future__ import annotations

from typing import Any

from ..cloud_colors import cloud_colors, rgb_to_hex

__all__ = ["CloudInfoDialog"]

#: Shown in the id field when there is no id to show.
NOT_IN_CLOUD_TEXT = "(not in NDI Cloud)"

#: Shown in the name or path field when it is not known.
UNKNOWN_TEXT = "(unknown)"


class CloudInfoDialog:
    """The "Cloud info..." result window for one dataset."""

    def __init__(
        self,
        in_cloud: bool,
        cloud_dataset_id: str = "",
        *,
        dataset_name: str = "",
        local_path: str = "",
        parent: Any = None,
        build: bool = True,
    ):
        self.in_cloud = bool(in_cloud)
        self.cloud_dataset_id = str(cloud_dataset_id or "")
        self.dataset_name = str(dataset_name or "")
        self.local_path = str(local_path or "")
        self.figure: Any = None
        self.id_field: Any = None
        self.copy_button: Any = None
        self.name_field: Any = None
        self.name_copy_button: Any = None
        self.path_field: Any = None
        self.path_copy_button: Any = None
        if build:
            self.build(parent)

    # ------------------------------------------------------------------
    # what the window says -- no Qt
    # ------------------------------------------------------------------
    @staticmethod
    def status_message(in_cloud: bool) -> str:
        """The status sentence shown at the top of the window."""
        if in_cloud:
            return "This dataset is linked to NDI Cloud."
        return 'This dataset is not in NDI Cloud. Use "Upload to Cloud" to add it.'

    @staticmethod
    def can_copy(in_cloud: bool, cloud_dataset_id: str) -> bool:
        """True when there is a cloud dataset id to copy."""
        return bool(in_cloud) and bool(cloud_dataset_id)

    @staticmethod
    def copy_enable(in_cloud: bool, cloud_dataset_id: str) -> bool:
        """Whether the id's Copy button is enabled."""
        return CloudInfoDialog.can_copy(in_cloud, cloud_dataset_id)

    @staticmethod
    def id_text(in_cloud: bool, cloud_dataset_id: str) -> str:
        """Text shown in the id field."""
        if CloudInfoDialog.can_copy(in_cloud, cloud_dataset_id):
            return str(cloud_dataset_id)
        return NOT_IN_CLOUD_TEXT

    @staticmethod
    def value_text(value: str) -> str:
        """Text shown in the name or path field."""
        return str(value) if value else UNKNOWN_TEXT

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build(self, parent: Any = None) -> Any:
        """Create the window: message, name/path/id rows with Copy, and OK."""
        from .._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtWidgets

        c = cloud_colors()
        navy = rgb_to_hex(c.dark_blue)
        white = rgb_to_hex(c.white)

        self.figure = QtWidgets.QDialog(parent)
        self.figure.setWindowTitle("Cloud Info")
        self.figure.setObjectName("ndiNavigatorCloudInfo")
        self.figure.setStyleSheet(f"QDialog {{ background-color: {navy}; }}")
        self.figure.resize(560, 240)

        layout = QtWidgets.QGridLayout(self.figure)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setVerticalSpacing(10)

        message = QtWidgets.QLabel(self.status_message(self.in_cloud))
        message.setWordWrap(True)
        message.setStyleSheet(f"color: {white};")
        layout.addWidget(message, 0, 0, 1, 3)

        self.name_field, self.name_copy_button = self._add_row(
            layout,
            1,
            "Dataset name:",
            self.value_text(self.dataset_name),
            bool(self.dataset_name),
            "ndiDatasetName",
            "Copy the dataset name to the clipboard",
            self.copy_name,
        )
        self.path_field, self.path_copy_button = self._add_row(
            layout,
            2,
            "Local path:",
            self.value_text(self.local_path),
            bool(self.local_path),
            "ndiDatasetLocalPath",
            "Copy the local path to the clipboard",
            self.copy_path,
        )
        self.id_field, self.copy_button = self._add_row(
            layout,
            3,
            "Cloud dataset ID:",
            self.id_text(self.in_cloud, self.cloud_dataset_id),
            self.copy_enable(self.in_cloud, self.cloud_dataset_id),
            "ndiCloudDatasetId",
            "Copy the cloud dataset ID to the clipboard",
            self.copy_id,
        )

        ok = QtWidgets.QPushButton("OK")
        ok.setStyleSheet(f"background-color: {white}; color: {navy};")
        ok.clicked.connect(self.figure.accept)
        layout.addWidget(ok, 4, 2)
        layout.setRowStretch(0, 1)
        return self.figure

    def _add_row(
        self,
        layout: Any,
        row: int,
        label: str,
        value: str,
        enabled: bool,
        name: str,
        tip: str,
        slot: Any,
    ) -> tuple[Any, Any]:
        """One "label | read-only value | Copy" row."""
        from PySide6 import QtWidgets

        c = cloud_colors()
        navy = rgb_to_hex(c.dark_blue)
        white = rgb_to_hex(c.white)
        light = rgb_to_hex(c.light_blue)

        text = QtWidgets.QLabel(label)
        text.setStyleSheet(f"color: {white}; font-weight: bold;")
        layout.addWidget(text, row, 0)

        # A read-only line edit rather than a label, so the value can also be
        # selected and copied by hand.
        field = QtWidgets.QLineEdit(value)
        field.setReadOnly(True)
        field.setObjectName(name)
        field.setStyleSheet(f"background-color: {white}; color: {navy};")
        layout.addWidget(field, row, 1)

        button = QtWidgets.QPushButton("Copy")
        button.setObjectName(name + "Copy")
        button.setToolTip(tip)
        button.setEnabled(bool(enabled))
        button.setStyleSheet(f"background-color: {light}; color: {navy};")
        button.clicked.connect(slot)
        layout.addWidget(button, row, 2)
        return field, button

    def _copy(self, text: str, button: Any) -> bool:
        if not text:
            return False
        from PySide6 import QtGui

        QtGui.QGuiApplication.clipboard().setText(text)
        if button is not None:
            button.setText("Copied")
        return True

    def copy_id(self) -> bool:
        """Copy the cloud dataset id to the clipboard. False when there is none."""
        if not self.can_copy(self.in_cloud, self.cloud_dataset_id):
            return False
        return self._copy(self.cloud_dataset_id, self.copy_button)

    def copy_name(self) -> bool:
        """Copy the dataset name to the clipboard. False when it is unknown."""
        return self._copy(self.dataset_name, self.name_copy_button)

    def copy_path(self) -> bool:
        """Copy the local path to the clipboard. False when it is unknown."""
        return self._copy(self.local_path, self.path_copy_button)

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def __repr__(self) -> str:
        return (
            f"CloudInfoDialog(in_cloud={self.in_cloud!r}, "
            f"cloud_dataset_id={self.cloud_dataset_id!r}, "
            f"dataset_name={self.dataset_name!r}, local_path={self.local_path!r})"
        )
