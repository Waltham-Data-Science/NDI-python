"""ndi.gui.nav.cloud_pane - the uncollapsible "NDI Cloud" pane.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/cloudPane.m``

A single-row pane with three controls on the right:

    * a reload button that clears the current NDI Cloud login, so the next
      cloud action re-authenticates with the default profile. This is the
      quick recovery when a token has expired and a stale login is otherwise
      being reused;
    * a "C" button that checks every dataset in the Datasets pane at once and
      badges each one -- the bulk equivalent of the per-dataset "Check Cloud
      status" command, so a user with twenty datasets does not check them one
      at a time. The letter matches the light-blue cloud badge that
      :func:`ndi.gui.nav.status_icon.status_icon` draws on a dataset that is
      in the cloud;
    * a "Profile" button for the NDI Cloud profile editor.

The Profile button opens :class:`ndi.gui.profile_editor.ProfileEditor`,
which is the only route to choosing the active cloud account -- so every
cloud action in the datasets pane runs against whatever it last selected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .datasets_text import cloud_summary_message
from .pane import NavPane

__all__ = [
    "CloudPane",
    "RELOAD_WIDTH",
    "CHECK_WIDTH",
    "PROFILE_WIDTH",
    "BUTTON_SPACING",
    "reload_icon_file",
]

RELOAD_WIDTH = 26
CHECK_WIDTH = 26
PROFILE_WIDTH = 62
BUTTON_SPACING = 4

#: U+21BB CLOCKWISE OPEN CIRCLE ARROW. Used only if the SVG icon will not
#: render -- a blank button is worse than an approximate glyph.
RELOAD_GLYPH = "↻"

LOGOUT_MESSAGE = (
    "Cleared the current NDI Cloud login. The next NDI Cloud action will "
    "sign in again using your default NDI Cloud profile."
)

NO_DATASETS_PANE = "No datasets pane is available."


def reload_icon_file() -> Path:
    """Absolute path to the reload button icon.

    The SVG is a byte-for-byte copy of MATLAB's
    ``+ndi/+gui/reload_icon.svg``, kept at the mirrored location here so the
    two ports draw the same button rather than each inventing an icon.
    """
    return Path(__file__).resolve().parent.parent / "reload_icon.svg"


class CloudPane(NavPane):
    """The "NDI Cloud" pane: refresh login, check all, profile."""

    def __init__(self, navigator: Any = None):
        super().__init__(navigator, title="NDI Cloud", collapsible=False)
        self.reload_button: Any = None
        self.check_button: Any = None
        self.profile_button: Any = None
        #: The open editor, held so Qt does not collect the window.
        self.profile_editor: Any = None

    def right_width(self) -> float:
        """reload (26) + 4 + C (26) + 4 + Profile (62)."""
        return RELOAD_WIDTH + BUTTON_SPACING + CHECK_WIDTH + BUTTON_SPACING + PROFILE_WIDTH

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build_header_right(self, layout: Any) -> None:
        from PySide6 import QtGui, QtWidgets

        self.reload_button = QtWidgets.QPushButton()
        self.reload_button.setFixedWidth(RELOAD_WIDTH)
        self.reload_button.setToolTip("Refresh NDI Cloud login (logout)")
        icon = QtGui.QIcon(str(reload_icon_file()))
        if icon.isNull():
            # No SVG support in this Qt build, or the file is missing. A
            # button with neither icon nor text is invisible to the user.
            self.reload_button.setText(RELOAD_GLYPH)
        else:
            self.reload_button.setIcon(icon)
        self.reload_button.clicked.connect(self.refresh_login)
        self.accent_button(self.reload_button)
        layout.addWidget(self.reload_button)

        self.check_button = QtWidgets.QPushButton("C")
        self.check_button.setFixedWidth(CHECK_WIDTH)
        self.check_button.setToolTip("Check NDI Cloud status of all datasets")
        self.check_button.clicked.connect(self.check_all_cloud)
        self.accent_button(self.check_button)
        layout.addWidget(self.check_button)

        self.profile_button = QtWidgets.QPushButton("Profile")
        self.profile_button.setFixedWidth(PROFILE_WIDTH)
        self.profile_button.setToolTip(
            "Open the NDI Cloud profile editor to manage your cloud accounts "
            "and choose the active one"
        )
        self.profile_button.clicked.connect(self.open_profile_editor)
        self.accent_button(self.profile_button)
        layout.addWidget(self.profile_button)

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def check_all_cloud(self) -> dict[str, int] | None:
        """Check the NDI Cloud status of every dataset, and badge each one.

        Returns the report, or None when there is no datasets pane to ask.
        Returning rather than only showing it is what makes the outcome
        checkable without a display, and it is the same report
        :func:`ndi.gui.nav.datasets_text.cloud_summary_message` turns into
        the sentence the user reads.
        """
        title = "Check NDI Cloud status"
        pane = self._datasets_pane()
        if pane is None:
            # Expected until datasetsPane is in the stack, and still possible
            # afterwards, so this says so rather than raising.
            self._alert(NO_DATASETS_PANE, title, success=False)
            return None

        try:
            report = pane.check_all_cloud_status(self._progress)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            self._alert(str(exc), title, success=False)
            return None

        self._alert(cloud_summary_message(report), title, success=True)
        return report

    def refresh_login(self) -> bool:
        """Clear the NDI Cloud login so the next call re-authenticates.

        Invalidates the current token on the server where it can (best
        effort) and clears the locally stored credentials. The next cloud
        action then signs in again with the default profile, which is what
        recovers from an expired or stale token.
        """
        title = "NDI Cloud"
        from ...cloud.auth import logout

        try:
            logout()
        except Exception as exc:  # noqa: BLE001
            self._alert(str(exc), title, success=False)
            return False
        self._alert(LOGOUT_MESSAGE, title, success=True)
        return True

    def open_profile_editor(self) -> Any:
        """Open the NDI Cloud profile editor, returning it.

        The editor is held on the pane. A Qt window with no reference is
        garbage-collected and vanishes the instant this method returns, so
        keeping it is what makes the button work at all rather than flicker.
        Reopening reuses the window and refreshes it, so a second click
        raises the one already on screen instead of stacking a duplicate.
        """
        from ..profile_editor import ProfileEditor

        try:
            if self.profile_editor is None or self.profile_editor.figure is None:
                self.profile_editor = ProfileEditor()
            else:
                self.profile_editor.refresh()
            self.profile_editor.show()
        except Exception as exc:  # noqa: BLE001
            self._alert(str(exc), "Profile", success=False)
            return None
        return self.profile_editor

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _datasets_pane(self) -> Any | None:
        if self.navigator is None:
            return None
        handle = getattr(self.navigator, "datasets_pane_handle", None)
        return handle() if callable(handle) else None

    def _progress(self, fraction: float, message: str) -> None:
        """Progress callback for the bulk check.

        A no-op for now: MATLAB drives a uiprogressdlg here, and a modal Qt
        dialog driven from inside the loop would block the very work it is
        reporting on. The datasets pane already accepts the callback, so a
        real progress widget slots in here without touching that side.
        """

    def _alert(self, message: str, title: str, *, success: bool) -> None:
        if self.navigator is None:
            return
        alert = getattr(self.navigator, "alert", None)
        if callable(alert):
            alert(message, title, success=success)
