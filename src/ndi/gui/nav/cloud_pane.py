"""ndi.gui.nav.cloud_pane - the uncollapsible "NDI Cloud" pane.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/cloudPane.m``

A single-row pane with four controls on the right:

    * a login indicator: a small coloured button saying whether NDI Cloud
      access is set up (see :meth:`CloudPane.login_status`):

        - green (check mark): logged in -- ``NDI_CLOUD_TOKEN`` holds a token
          that has not expired;
        - yellow (circle): ready to log in -- not logged in, but the current
          (else default) profile has an email and a stored password, or
          ``NDI_CLOUD_USERNAME`` / ``NDI_CLOUD_PASSWORD`` are both set, so the
          next NDI Cloud action signs in;
        - red (cross): not configured -- no token and nothing to log in with
          (no profile, or a profile without a stored password).

      Hovering says which, and for whom; clicking opens the profile editor.
      It is re-read every ``LOGIN_REFRESH_SECONDS`` (a token can expire while
      the navigator is open), when the profile editor closes, after the
      reload button logs out, and on every pane refresh;
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

import os
from collections.abc import Mapping
from typing import Any

from ..cloud_colors import cloud_colors, rgb_to_hex
from .datasets_text import cloud_summary_message
from .pane import RELOAD_GLYPH, NavPane, reload_icon_file  # noqa: F401 - re-exported

__all__ = [
    "CloudPane",
    "LOGIN_WIDTH",
    "LOGIN_REFRESH_SECONDS",
    "RELOAD_WIDTH",
    "CHECK_WIDTH",
    "PROFILE_WIDTH",
    "BUTTON_SPACING",
    "reload_icon_file",
]

LOGIN_WIDTH = 26
RELOAD_WIDTH = 26
CHECK_WIDTH = 26
PROFILE_WIDTH = 62
BUTTON_SPACING = 4

#: How often the login indicator re-reads its state, in seconds.
LOGIN_REFRESH_SECONDS = 30

#: Glyphs drawn on the login indicator, so the state does not rest on colour.
LOGIN_GLYPHS = {"loggedin": "\u2713", "ready": "\u25cb", "notconfigured": "\u2715"}

_CLICK = "Click to view or edit your NDI Cloud profiles."


LOGOUT_MESSAGE = (
    "Cleared the current NDI Cloud login. The next NDI Cloud action will "
    "sign in again using your default NDI Cloud profile."
)

NO_DATASETS_PANE = "No datasets pane is available."


class CloudPane(NavPane):
    """The "NDI Cloud" pane: login indicator, refresh login, check all, profile."""

    def __init__(self, navigator: Any = None):
        super().__init__(navigator, title="NDI Cloud", collapsible=False)
        self.login_indicator: Any = None
        self.login_state = ""
        self.login_timer: Any = None
        self.reload_button: Any = None
        self.check_button: Any = None
        self.profile_button: Any = None
        #: The open editor, held so Qt does not collect the window.
        self.profile_editor: Any = None

    def right_width(self) -> float:
        """login (26) + 4 + reload (26) + 4 + C (26) + 4 + Profile (62)."""
        return (
            LOGIN_WIDTH
            + BUTTON_SPACING
            + RELOAD_WIDTH
            + BUTTON_SPACING
            + CHECK_WIDTH
            + BUTTON_SPACING
            + PROFILE_WIDTH
        )

    # ------------------------------------------------------------------
    # the login indicator -- no Qt
    # ------------------------------------------------------------------
    @staticmethod
    def duration_text(secs: float) -> str:
        """A rough, readable length of time (``'about 3 hours'``)."""
        secs = abs(float(secs))
        if secs < 90:
            return "less than 2 minutes"
        if secs < 90 * 60:
            return f"{round(secs / 60)} minutes"
        if secs < 36 * 3600:
            return f"about {round(secs / 3600)} hours"
        return f"about {round(secs / 86400)} days"

    @staticmethod
    def describe_login(
        seconds_left: float | None,
        user_name: str = "",
        profile: Any = None,
        has_password: bool = False,
        env_credentials: bool = False,
    ) -> dict[str, Any]:
        """Decide the login indicator's state and hover text.

        MATLAB counterpart: ``cloudPane.describeLogin``. Returns a dict with
        ``state`` (``'loggedin'``, ``'ready'`` or ``'notconfigured'``),
        ``color`` (a palette triplet), ``glyph`` and ``tooltip``.

        SECONDS_LEFT is the token's remaining life (None when there is no
        readable token; <= 0 when it has expired). USER_NAME names the account
        the token or the environment variables are for. PROFILE is the
        current-or-default profile (a ``ProfileEntry`` or a mapping with
        ``Nickname`` and ``Email``), or None. HAS_PASSWORD says whether it has
        a stored password; ENV_CREDENTIALS whether ``NDI_CLOUD_USERNAME`` and
        ``NDI_CLOUD_PASSWORD`` are both set.
        """
        c = cloud_colors()
        user_name = str(user_name or "")

        def field(name: str) -> str:
            if profile is None:
                return ""
            if isinstance(profile, Mapping):
                return str(profile.get(name) or "")
            return str(getattr(profile, name, "") or "")

        has_profile = profile is not None
        email, nickname = field("Email"), field("Nickname")
        expired = ""
        if seconds_left is not None and seconds_left <= 0:
            expired = f" (The last login expired {CloudPane.duration_text(-seconds_left)} ago.)"

        def status(state: str, color: Any, tooltip: str) -> dict[str, Any]:
            return {
                "state": state,
                "color": color,
                "glyph": LOGIN_GLYPHS[state],
                "tooltip": tooltip,
            }

        if seconds_left is not None and seconds_left > 0:
            as_whom = f" as {user_name}" if user_name else ""
            return status(
                "loggedin",
                c.ok_green,
                f"Logged in to NDI Cloud{as_whom}. The login expires in "
                f"{CloudPane.duration_text(seconds_left)}. {_CLICK}",
            )
        if has_profile and email and has_password:
            return status(
                "ready",
                c.warn_amber,
                f'Ready to log in to NDI Cloud as {email} (profile "{nickname}"). '
                f"Not logged in yet: the next NDI Cloud action signs in.{expired} {_CLICK}",
            )
        if env_credentials:
            return status(
                "ready",
                c.warn_amber,
                f"Ready to log in to NDI Cloud as {user_name} (from the "
                "NDI_CLOUD_USERNAME and NDI_CLOUD_PASSWORD environment variables). "
                f"Not logged in yet: the next NDI Cloud action signs in.{expired} {_CLICK}",
            )
        if has_profile:
            return status(
                "notconfigured",
                c.alert_red,
                f'NDI Cloud login is not set up: profile "{nickname}" has no stored '
                f"email and password.{expired} Click to open the profile editor and "
                "set its password.",
            )
        return status(
            "notconfigured",
            c.alert_red,
            f"NDI Cloud login is not set up: there is no NDI Cloud profile.{expired} "
            "Click to open the profile editor and add one with your NDI Cloud email "
            "and password.",
        )

    @staticmethod
    def login_status() -> dict[str, Any]:
        """The NDI Cloud login state, read from this process.

        MATLAB counterpart: ``cloudPane.loginStatus``. Gathers the
        ``NDI_CLOUD_TOKEN`` token's remaining life, the current (else default)
        profile and whether it has a stored password, and the
        ``NDI_CLOUD_USERNAME`` / ``NDI_CLOUD_PASSWORD`` variables, and passes
        them to :meth:`describe_login`. Never raises: anything it cannot read
        counts as absent.
        """
        user_name = os.environ.get("NDI_CLOUD_USERNAME", "")
        token = os.environ.get("NDI_CLOUD_TOKEN", "")
        seconds_left = None
        if token:
            try:
                from ...cloud.auth import decodeJwt, tokenSecondsRemaining

                seconds_left = tokenSecondsRemaining(token)
                if not user_name:
                    user_name = str(decodeJwt(token).get("email") or "")
            except Exception:  # noqa: BLE001 - an unreadable token is no login
                pass

        entry = None
        has_password = False
        try:
            from ...cloud import profile

            entry = profile.get_current() or profile.get_default()
            if entry is not None:
                has_password = bool(profile.get_password(entry.UID))
        except Exception:  # noqa: BLE001 - see docstring
            has_password = False

        env_credentials = bool(
            os.environ.get("NDI_CLOUD_USERNAME") and os.environ.get("NDI_CLOUD_PASSWORD")
        )
        return CloudPane.describe_login(
            seconds_left, user_name, entry, has_password, env_credentials
        )

    def refresh(self) -> None:
        """Re-read the NDI Cloud login state into the indicator."""
        self.update_login_indicator()

    def update_login_indicator(self) -> dict[str, Any]:
        """Show the current login state on the indicator, and return it."""
        status = self.login_status()
        self.login_state = status["state"]
        btn = self.login_indicator
        if btn is not None:
            c = cloud_colors()
            btn.setText(status["glyph"])
            btn.setToolTip(status["tooltip"])
            btn.setStyleSheet(
                f"background-color: {rgb_to_hex(status['color'])}; "
                f"color: {rgb_to_hex(c.white)}; font-weight: bold;"
            )
        return status

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build_header_right(self, layout: Any) -> None:
        from PySide6 import QtCore, QtWidgets

        self.login_indicator = QtWidgets.QPushButton()
        self.login_indicator.setObjectName("ndiNavigatorCloudLoginIndicator")
        self.login_indicator.setFixedWidth(LOGIN_WIDTH)
        self.login_indicator.clicked.connect(self.open_profile_editor)
        layout.addWidget(self.login_indicator)
        self.update_login_indicator()
        # Parented to the indicator, so it goes when the navigator does.
        self.login_timer = QtCore.QTimer(self.login_indicator)
        self.login_timer.setInterval(LOGIN_REFRESH_SECONDS * 1000)
        self.login_timer.timeout.connect(self._on_login_timer)
        self.login_timer.start()

        self.reload_button = self.refresh_button(
            "Refresh NDI Cloud login (logout)", self.refresh_login
        )
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

        dialog = self._open_progress_dialog(title)
        try:
            report = pane.check_all_cloud_status(lambda f, m: self._progress(f, m, dialog))
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            self._close_progress_dialog(dialog)
            self._alert(str(exc), title, success=False)
            return None
        self._close_progress_dialog(dialog)

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
        self.update_login_indicator()
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
                self._watch_editor_close(self.profile_editor.figure)
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
    def _on_login_timer(self) -> None:
        try:
            self.update_login_indicator()
        except Exception:  # noqa: BLE001 - a failed read must not stop the timer
            pass

    def _watch_editor_close(self, figure: Any) -> None:
        """Re-read the login state when the profile editor window closes."""
        if figure is None:
            return
        try:
            from PySide6 import QtCore
        except ImportError:
            return
        pane = self

        class _CloseWatcher(QtCore.QObject):
            def eventFilter(self, obj: Any, event: Any) -> bool:  # noqa: N802 - Qt API
                if event.type() == QtCore.QEvent.Type.Close:
                    pane._on_login_timer()
                return False

        watcher = _CloseWatcher(figure)
        figure.installEventFilter(watcher)

    def _datasets_pane(self) -> Any | None:
        if self.navigator is None:
            return None
        handle = getattr(self.navigator, "datasets_pane_handle", None)
        return handle() if callable(handle) else None

    def _open_progress_dialog(self, title: str) -> Any | None:
        """Return a non-modal ``QProgressDialog``, or None when Qt is missing.

        Non-modal so the check loop is not blocked; the caller drives it
        through :meth:`_progress` on every dataset. Returns None when a Qt
        application is not running (headless tests, no display); the check
        still runs, just without a visible dialog. Mirrors MATLAB's
        ``uiprogressdlg`` for the bulk cloud-status check.
        """
        try:
            from PySide6 import QtCore, QtWidgets
        except ImportError:
            return None
        parent = getattr(self.navigator, "figure", None)
        try:
            dialog = QtWidgets.QProgressDialog("Checking NDI Cloud status...", "", 0, 100, parent)
        except Exception:  # noqa: BLE001 - no display, no Qt app
            return None
        # No cancel button: mirroring MATLAB's Cancelable=false, and the
        # check itself does not accept cancellation.
        dialog.setCancelButton(None)
        dialog.setWindowTitle(title)
        dialog.setWindowModality(QtCore.Qt.WindowModality.NonModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        dialog.show()
        return dialog

    def _close_progress_dialog(self, dialog: Any) -> None:
        if dialog is None:
            return
        dialog.reset()
        dialog.close()

    def _progress(self, fraction: float, message: str, dialog: Any = None) -> None:
        """Progress callback for the bulk check.

        Advances the shared ``QProgressDialog`` in place. Kept processing
        events on each call so the dialog stays live under a synchronous
        Python loop -- MATLAB's uiprogressdlg redraws itself; Qt's does not
        until control returns to the event loop.
        """
        if dialog is None:
            return
        try:
            from PySide6 import QtCore, QtWidgets
        except ImportError:
            return
        percent = max(0, min(100, int(round(float(fraction) * 100))))
        dialog.setValue(percent)
        dialog.setLabelText(message)
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents)

    def _alert(self, message: str, title: str, *, success: bool) -> None:
        if self.navigator is None:
            return
        alert = getattr(self.navigator, "alert", None)
        if callable(alert):
            alert(message, title, success=success)
