"""ndi.gui.profile_editor - manage the NDI Cloud login profiles.

MATLAB counterpart: ``src/ndi/+ndi/+gui/profileEditor.m``

A window over :mod:`ndi.cloud.profile`: add and remove profiles, change a
password, and choose which profile is CURRENT and which is DEFAULT. It is
the only route to choosing the active cloud account, so every cloud action
in the navigator -- upload, sync, mirror, the bulk status check -- runs
against whatever this window last selected.

CURRENT AND DEFAULT ARE DIFFERENT THINGS
Current is this session only and is not written to disk. Default is
persisted and becomes Current at the start of every future session. A row
can carry both markers, and the two buttons are separate because the choice
"use this account now" and the choice "use this account from now on" are
genuinely different. Conflating them would either surprise a user whose
one-off switch outlived the session, or fail to stick for one who meant it
to.

STAGE IS NOT SURFACED
``ndi.cloud.profile`` also carries a per-profile ``Stage``. MATLAB leaves it
out of this editor deliberately -- it is a developer-only field, set from
the command line -- and so does this. Adding it would offer every user a
control that can only break their cloud access.

WHAT IS PURE AND WHAT IS NOT
:func:`profile_rows` and the message builders are plain functions with no Qt
in them, so what the table SHOWS and what the user is TOLD are both testable
without a display. The class below owns the widgets and calls into them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

__all__ = [
    "ProfileEditor",
    "profile_rows",
    "COLUMNS",
    "MARKER",
    "WINDOW_TAG",
    "DEFAULT_POSITION",
    "add_failure_message",
    "remove_confirm_message",
]

#: Table columns, in MATLAB's order.
COLUMNS = ("Current", "Default", "Nickname", "Email", "UID")

#: Drawn in the Current/Default column of the row it applies to.
MARKER = "*"

#: Object name on the window, so an open editor can be found again.
WINDOW_TAG = "ndiProfileEditor"

#: Default geometry ``(x, y, width, height)``, as MATLAB has it.
DEFAULT_POSITION = (120, 120, 820, 440)

#: Shown when a button needing a selected row is pressed without one.
NO_SELECTION = "Select a profile first."


def profile_rows(
    profiles: Sequence[Any], current: Any = None, default: Any = None
) -> list[list[str]]:
    """The table contents: one row per profile, in :data:`COLUMNS` order.

    ``current`` and ``default`` are profile entries or None. A row is marked
    when its UID matches, so a profile that is both current and default
    carries BOTH markers -- that is a real and common state (you set a
    default, and this session is using it), and hiding one of them would
    misreport it.

    Matching is by UID rather than by object identity: the entries handed in
    may be separate reads of the same stored profile.
    """
    current_uid = _uid(current)
    default_uid = _uid(default)
    rows = []
    for entry in profiles:
        uid = _uid(entry)
        rows.append(
            [
                MARKER if uid and uid == current_uid else "",
                MARKER if uid and uid == default_uid else "",
                str(getattr(entry, "Nickname", "") or ""),
                str(getattr(entry, "Email", "") or ""),
                uid,
            ]
        )
    return rows


def _uid(entry: Any) -> str:
    return str(getattr(entry, "UID", "") or "") if entry is not None else ""


def add_failure_message(nickname: str, email: str, password: str) -> str:
    """Why an Add cannot proceed, or ``""`` when it can.

    All three fields are required. Returning the reason rather than a bare
    False is what lets the caller say the same thing MATLAB says without
    re-deriving which field was missing.
    """
    if not (nickname or "").strip() or not (email or "").strip() or not password:
        return "Nickname, email, and password must all be provided."
    return ""


def remove_confirm_message(entry: Any) -> str:
    """The confirmation for deleting a profile.

    Names the profile AND its email: nicknames are user-chosen and need not
    be unique, so the email is what makes it unambiguous which account is
    about to lose its stored credentials.
    """
    return f'Delete profile "{getattr(entry, "Nickname", "")}" ' f'({getattr(entry, "Email", "")})?'


class ProfileEditor:
    """The NDI Cloud profiles window."""

    def __init__(
        self,
        *,
        position: tuple[float, float, float, float] = DEFAULT_POSITION,
        build: bool = True,
    ):
        self.position = tuple(position)
        self.figure: Any = None
        self.table: Any = None
        self.buttons: dict[str, Any] = {}
        #: Row index the user last selected, or None.
        self.selected_row: int | None = None
        if build:
            self.build()

    # ------------------------------------------------------------------
    # model
    # ------------------------------------------------------------------
    def rows(self) -> list[list[str]]:
        """The rows the table should show, read fresh from the profile store."""
        from ..cloud import profile

        return profile_rows(profile.list_profiles(), profile.get_current(), profile.get_default())

    def selected_uid(self) -> str:
        """UID of the selected row, or ``""`` when nothing is selected.

        Read from the rendered table rather than from a cached list, so a
        selection can never point at a row the table no longer shows.
        """
        if self.table is None or self.selected_row is None:
            return ""
        if not (0 <= self.selected_row < self.table.rowCount()):
            return ""
        item = self.table.item(self.selected_row, COLUMNS.index("UID"))
        return item.text() if item is not None else ""

    def refresh(self) -> list[list[str]]:
        """Repopulate the table from the profile store; returns the rows."""
        rows = self.rows()
        if self.table is None:
            return rows

        from PySide6 import QtWidgets

        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(text))
        return rows

    # ------------------------------------------------------------------
    # the buttons
    # ------------------------------------------------------------------
    def add_profile(self) -> str:
        """Add a profile from a prompted nickname, email and password.

        Returns the new UID, or ``""`` when cancelled or refused.
        """
        title = "Add Cloud Profile"
        answer = self._ask_fields(("Nickname:", "Email:", "Password:"), title, secret_last=True)
        if answer is None:
            return ""
        nickname, email, password = answer

        problem = add_failure_message(nickname, email, password)
        if problem:
            self.alert(problem, "Add failed")
            return ""

        from ..cloud import profile

        try:
            uid = profile.add(nickname.strip(), email.strip(), password)
        except Exception as exc:  # noqa: BLE001
            self.alert(str(exc), "Add failed")
            return ""
        self.refresh()
        return uid

    def set_current(self) -> bool:
        """Use the selected profile for THIS SESSION only."""
        return self._apply_to_selection("set_current", "Set Current failed")

    def set_default(self) -> bool:
        """Persist the selected profile as the default for future sessions."""
        return self._apply_to_selection("set_default", "Set Default failed")

    def clear_default(self) -> bool:
        """Forget the persisted default. Needs no selection."""
        from ..cloud import profile

        try:
            profile.clear_default()
        except Exception as exc:  # noqa: BLE001
            self.alert(str(exc), "Clear Default failed")
            return False
        self.refresh()
        return True

    def change_password(self) -> bool:
        """Set a new password on the selected profile.

        The user never sees the underlying secrets key: the store is told the
        new password and manages the secret itself.
        """
        title = "Change Password"
        uid = self._require_selection(title)
        if not uid:
            return False

        answer = self._ask_fields(("New password:",), title, secret_last=True)
        if answer is None:
            return False
        password = answer[0]
        if not password:
            self.alert("Password cannot be empty.", "Change Password failed")
            return False

        from ..cloud import profile

        try:
            profile.set_password(uid, password)
        except Exception as exc:  # noqa: BLE001
            self.alert(str(exc), "Change Password failed")
            return False
        self.alert("Password updated.", "Done", success=True)
        return True

    def remove_profile(self) -> bool:
        """Delete the selected profile, after confirming.

        Removing also deletes the stored secret and clears Current/Default if
        they pointed at it, so the confirmation names the account precisely.
        """
        title = "Remove failed"
        uid = self._require_selection("No selection")
        if not uid:
            return False

        from ..cloud import profile

        try:
            entry = profile.get(uid)
        except Exception as exc:  # noqa: BLE001
            self.alert(str(exc), title)
            return False

        if not self.confirm(remove_confirm_message(entry), "Confirm remove", accept="Delete"):
            return False

        try:
            profile.remove(uid)
        except Exception as exc:  # noqa: BLE001
            self.alert(str(exc), title)
            return False

        # The selection is dropped rather than kept: the row it pointed at is
        # gone, and a stale index would silently act on whichever profile
        # slid into that position.
        self.selected_row = None
        self.refresh()
        return True

    def close(self) -> None:
        if self.figure is not None:
            self.figure.close()

    def _apply_to_selection(self, method: str, failure_title: str) -> bool:
        uid = self._require_selection("No selection")
        if not uid:
            return False
        from ..cloud import profile

        try:
            getattr(profile, method)(uid)
        except Exception as exc:  # noqa: BLE001
            self.alert(str(exc), failure_title)
            return False
        self.refresh()
        return True

    def _require_selection(self, title: str) -> str:
        uid = self.selected_uid()
        if not uid:
            self.alert(NO_SELECTION, title)
        return uid

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build(self) -> Any:
        from ._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtCore, QtWidgets

        from .cloud_colors import cloud_colors, rgb_to_hex

        c = cloud_colors()
        x, y, w, h = self.position

        self.figure = QtWidgets.QWidget()
        self.figure.setWindowTitle("NDI Cloud Profiles")
        self.figure.setObjectName(WINDOW_TAG)
        self.figure.setGeometry(int(x), int(y), int(w), int(h))
        self.figure.setStyleSheet(f"background-color: {rgb_to_hex(c.off_white)};")

        root = QtWidgets.QVBoxLayout(self.figure)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        header = QtWidgets.QLabel("NDI Cloud Profiles")
        header.setFixedHeight(28)
        header.setStyleSheet(
            f"background-color: {rgb_to_hex(c.dark_blue)};"
            f"color: {rgb_to_hex(c.white)};"
            "font-weight: bold; font-size: 14px; padding-left: 8px;"
        )
        root.addWidget(header)

        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        for index, width in enumerate((60, 60, 160, 220)):
            self.table.setColumnWidth(index, width)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self.table, 1)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        row.addStretch(1)
        for label, slot in (
            ("Add...", self.add_profile),
            ("Set Current", self.set_current),
            ("Set Default", self.set_default),
            ("Clear Default", self.clear_default),
            ("Change Password...", self.change_password),
            ("Remove", self.remove_profile),
            ("Close", self.close),
        ):
            button = QtWidgets.QPushButton(label)
            button.setStyleSheet(
                f"background-color: {rgb_to_hex(c.light_blue)};"
                f"color: {rgb_to_hex(c.dark_blue)}; font-weight: bold;"
            )
            button.clicked.connect(slot)
            row.addWidget(button)
            self.buttons[label] = button
        root.addLayout(row)

        QtCore.QTimer  # noqa: B018 - imported for callers that drive the window
        self.refresh()
        return self.figure

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def _on_selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table else []
        self.selected_row = rows[0].row() if rows else None

    # ------------------------------------------------------------------
    # dialogs
    # ------------------------------------------------------------------
    def _ask_fields(
        self, prompts: Sequence[str], title: str, *, secret_last: bool = False
    ) -> list[str] | None:
        """Prompt for one value per prompt. None when cancelled.

        The last field is masked when ``secret_last``, which is where this
        improves on MATLAB: its ``inputdlg`` shows the password in clear
        text, a documented v1 limitation there. Qt gives masking for free,
        so there is no reason to reproduce the shortcoming.
        """
        from PySide6 import QtWidgets

        values: list[str] = []
        for index, prompt in enumerate(prompts):
            masked = secret_last and index == len(prompts) - 1
            mode = (
                QtWidgets.QLineEdit.EchoMode.Password
                if masked
                else QtWidgets.QLineEdit.EchoMode.Normal
            )
            text, ok = QtWidgets.QInputDialog.getText(self.figure, title, prompt, mode)
            if not ok:
                return None
            values.append(text)
        return values

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
        self._held = getattr(self, "_held", [])
        self._held.append(box)
        box.finished.connect(lambda _=0, b=box: self._held.remove(b) if b in self._held else None)
        return box

    def confirm(self, message: str, title: str, *, accept: str) -> bool:
        """Confirm a destructive action, defaulting to Cancel."""
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
        return f"ProfileEditor(rows={len(self.rows())})"
