"""ndi.gui.nav.cloud_status_dialog - the result window of "Check Cloud status".

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/cloudStatusDialog.m``

Reports whether a dataset is linked to NDI Cloud. It shows the status
sentence, the NDI Cloud dataset id in a read-only (selectable) field, and a
"Copy" button that puts the id on the clipboard. When the dataset is not in
the cloud there is no id: the field reads "(not in NDI Cloud)" and Copy is
disabled.

What the window SAYS -- the sentence, the id text, whether Copy is enabled --
is decided by the static methods, which need no display and are tested on
their own; :meth:`CloudStatusDialog.build` only lays the widgets out.
"""

from __future__ import annotations

from typing import Any

from ..cloud_colors import cloud_colors, rgb_to_hex

__all__ = ["CloudStatusDialog"]

#: Shown in the id field when there is no id to show.
NOT_IN_CLOUD_TEXT = "(not in NDI Cloud)"


class CloudStatusDialog:
    """The "Check Cloud status" result window for one dataset."""

    def __init__(
        self,
        in_cloud: bool,
        cloud_dataset_id: str = "",
        *,
        parent: Any = None,
        build: bool = True,
    ):
        self.in_cloud = bool(in_cloud)
        self.cloud_dataset_id = str(cloud_dataset_id or "")
        self.figure: Any = None
        self.id_field: Any = None
        self.copy_button: Any = None
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
        """Whether the Copy button is enabled."""
        return CloudStatusDialog.can_copy(in_cloud, cloud_dataset_id)

    @staticmethod
    def id_text(in_cloud: bool, cloud_dataset_id: str) -> str:
        """Text shown in the id field."""
        if CloudStatusDialog.can_copy(in_cloud, cloud_dataset_id):
            return str(cloud_dataset_id)
        return NOT_IN_CLOUD_TEXT

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build(self, parent: Any = None) -> Any:
        """Create the window: message, id row with Copy, and OK."""
        from .._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtWidgets

        c = cloud_colors()
        navy = rgb_to_hex(c.dark_blue)
        white = rgb_to_hex(c.white)
        light = rgb_to_hex(c.light_blue)

        self.figure = QtWidgets.QDialog(parent)
        self.figure.setWindowTitle("Check Cloud Status")
        self.figure.setObjectName("ndiNavigatorCloudStatus")
        self.figure.setStyleSheet(f"QDialog {{ background-color: {navy}; }}")
        self.figure.resize(460, 170)

        layout = QtWidgets.QGridLayout(self.figure)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setVerticalSpacing(10)

        message = QtWidgets.QLabel(self.status_message(self.in_cloud))
        message.setWordWrap(True)
        message.setStyleSheet(f"color: {white};")
        layout.addWidget(message, 0, 0, 1, 3)

        label = QtWidgets.QLabel("Cloud dataset ID:")
        label.setStyleSheet(f"color: {white}; font-weight: bold;")
        layout.addWidget(label, 1, 0)

        # A read-only line edit rather than a label, so the id can also be
        # selected and copied by hand.
        self.id_field = QtWidgets.QLineEdit(self.id_text(self.in_cloud, self.cloud_dataset_id))
        self.id_field.setReadOnly(True)
        self.id_field.setObjectName("ndiCloudDatasetId")
        self.id_field.setStyleSheet(f"background-color: {white}; color: {navy};")
        layout.addWidget(self.id_field, 1, 1)

        self.copy_button = QtWidgets.QPushButton("Copy")
        self.copy_button.setObjectName("ndiCloudDatasetIdCopy")
        self.copy_button.setToolTip("Copy the cloud dataset ID to the clipboard")
        self.copy_button.setEnabled(self.copy_enable(self.in_cloud, self.cloud_dataset_id))
        self.copy_button.setStyleSheet(f"background-color: {light}; color: {navy};")
        self.copy_button.clicked.connect(self.copy_id)
        layout.addWidget(self.copy_button, 1, 2)

        ok = QtWidgets.QPushButton("OK")
        ok.setStyleSheet(f"background-color: {white}; color: {navy};")
        ok.clicked.connect(self.figure.accept)
        layout.addWidget(ok, 2, 2)
        layout.setRowStretch(0, 1)
        return self.figure

    def copy_id(self) -> bool:
        """Copy the cloud dataset id to the clipboard. False when there is none."""
        if not self.can_copy(self.in_cloud, self.cloud_dataset_id):
            return False
        from PySide6 import QtGui

        QtGui.QGuiApplication.clipboard().setText(self.cloud_dataset_id)
        if self.copy_button is not None:
            self.copy_button.setText("Copied")
        return True

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def __repr__(self) -> str:
        return (
            f"CloudStatusDialog(in_cloud={self.in_cloud!r}, "
            f"cloud_dataset_id={self.cloud_dataset_id!r})"
        )
