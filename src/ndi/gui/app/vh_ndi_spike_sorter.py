"""ndi.gui.app.vh_ndi_spike_sorter - open the VH Lab interactive spike sorter.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/vhNDISpikeSorter.m``

A small window that launches the VH Lab interactive spike sorter for a
session, and -- when the sorter is not installed -- says so plainly instead.
The sorter itself lives in ``vhlab-library-matlab``, a separate repository
that is not part of NDI; this app only hands it the session.

THE WINDOW IS MOSTLY THE UNAVAILABLE CASE, AND THAT IS THE POINT
The whole app is an availability check, a sentence, and one button. MATLAB
builds it that way deliberately: the sorter is an optional dependency, so
the app has to be openable whether or not it is installed, and has to
explain the difference. An app that errored when the sorter was missing
would leave a user staring at a stack trace to learn they need a library.

WHAT "AVAILABLE" MEANS ON THIS SIDE
MATLAB asks ``which('vhNDISpikeSorter.spikesorting')`` -- is that package
function on the path? The Python question is whether the same name can be
imported and called. So :func:`resolve_launcher` imports the module
``vhNDISpikeSorter`` and looks for ``spikesorting`` on it.

BE CLEAR ABOUT THIS: ``vhlab-library-matlab`` IS MATLAB, and there is no
Python build of it, so on a stock Python install this app opens with its
button disabled and always will. It is written against the name rather than
against a hardcoded "no" for two reasons. It stays a faithful port of
MATLAB's contract; and a lab that does grow a Python launcher of that name
-- a binding, a reimplementation, a shim onto a MATLAB engine -- gets a
working button with no change to NDI. The unavailable message says which
situation the user is in rather than implying a ``pip install`` would fix
it, because it would not.

WHAT IS QT AND WHAT IS NOT
Whether the sorter is available, which sentence that produces, and whether
the button may be pressed are plain Python here and tested with no display,
the split the other apps in this package make. A window that says the
sorter is installed when it is not sends someone hunting a bug in the
sorter instead of installing it.
"""

from __future__ import annotations

import importlib
from typing import Any, ClassVar

from .session_app import SessionApp

__all__ = [
    "vhNDISpikeSorter",
    "VHNDISpikeSorter",
    "DEFAULT_POSITION",
    "WINDOW_TAG",
    "LAUNCHER",
    "LAUNCHER_MODULE",
    "LAUNCHER_FUNCTION",
    "AVAILABLE_MESSAGE",
    "UNAVAILABLE_MESSAGE",
    "NOT_FOUND_ALERT",
    "resolve_launcher",
    "availability_message",
]

#: Where the window opens, ``(x, y, width, height)``, as MATLAB positions it.
DEFAULT_POSITION: tuple[float, float, float, float] = (100, 100, 460, 200)

#: The window's object name, MATLAB's figure Tag.
WINDOW_TAG = "ndi.gui.app.vhNDISpikeSorter"

#: The external entry point this app wraps, spelled as MATLAB spells it.
#: MATLAB resolves it as a package function; Python resolves it as
#: ``LAUNCHER_FUNCTION`` on the module ``LAUNCHER_MODULE``.
LAUNCHER = "vhNDISpikeSorter.spikesorting"
LAUNCHER_MODULE, LAUNCHER_FUNCTION = LAUNCHER.split(".", 1)

#: Shown when the sorter can be launched.
AVAILABLE_MESSAGE = (
    "The VH Lab interactive spike sorter is available. Click below to open it " "for this session."
)

#: Shown when it cannot. MATLAB says "not found on the MATLAB path. Install /
#: add vhlab-library-matlab"; on this side that would be misleading, because
#: vhlab-library-matlab is MATLAB and no amount of installing makes it
#: importable here. The sentence says what is actually true and what actually
#: works.
UNAVAILABLE_MESSAGE = (
    f"The VH Lab spike sorter ({LAUNCHER_MODULE}) is not available from Python. "
    "It ships in vhlab-library-matlab, which is a MATLAB library: run the sorter "
    "from MATLAB with ndi.gui.app.vhNDISpikeSorter, or make a Python "
    f"{LAUNCHER} importable to use it here."
)

#: Shown if the button is pressed and the sorter has gone away since the
#: window opened.
NOT_FOUND_ALERT = (
    f"{LAUNCHER} could not be imported. See the message in the window: the VH Lab "
    "spike sorter is a MATLAB library and is run from MATLAB."
)


def resolve_launcher() -> Any | None:
    """The VH Lab sorter's entry point, or None when it is not installed.

    MATLAB's ``which('vhNDISpikeSorter.spikesorting')``, asked the Python
    way: import the module, take the function off it.

    EVERY failure is None rather than an exception -- a missing module, a
    module that raises on import, a module without the function, a name that
    is not callable. All four mean the same thing to this app ("cannot
    launch"), and an app whose window will not open cannot tell the user
    why it will not open.
    """
    try:
        module = importlib.import_module(LAUNCHER_MODULE)
    except Exception:  # noqa: BLE001 - absent, or broken: not launchable either way
        return None
    launcher = getattr(module, LAUNCHER_FUNCTION, None)
    return launcher if callable(launcher) else None


def availability_message(available: bool) -> str:
    """The sentence the window shows for each state."""
    return AVAILABLE_MESSAGE if available else UNAVAILABLE_MESSAGE


class vhNDISpikeSorter(SessionApp):  # noqa: N801 (MATLAB class name)
    """Launch the VH Lab interactive spike sorter for a session.

    ``vhNDISpikeSorter(session)`` opens the window, which is the whole
    contract :class:`~ndi.gui.app.SessionApp` asks of an app.

    MATLAB equivalent: ``ndi.gui.app.vhNDISpikeSorter``.
    """

    #: The Apps-menu label. Verbatim from MATLAB: it is user-visible text.
    Name: ClassVar[str] = "VHLab Spike Sorter"

    #: Groups the app beside the other sorters, as MATLAB groups it.
    Category: ClassVar[str] = "Spike Sorters"

    def __init__(
        self,
        session: Any,
        *,
        position: tuple[float, float, float, float] = DEFAULT_POSITION,
        build: bool = True,
    ):
        self.session = session
        self.position = tuple(position)

        self.figure: Any = None
        self.status_label: Any = None
        self.open_button: Any = None
        self._held: list[Any] = []

        if build:
            self.build()

    # ------------------------------------------------------------------
    # model
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """Whether the sorter can be launched right now.

        Asked fresh each time rather than cached at construction, because
        MATLAB asks it fresh: a user can add the library while the window is
        open, and :meth:`refresh_availability` is what picks that up.
        """
        return resolve_launcher() is not None

    def status_text(self) -> str:
        """The sentence for the current state."""
        return availability_message(self.is_available())

    # ------------------------------------------------------------------
    # the window
    # ------------------------------------------------------------------
    def build(self) -> Any:
        from .._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtCore, QtWidgets

        from ..cloud_colors import cloud_colors, rgb_to_hex

        c = cloud_colors()
        x, y, w, h = self.position
        navy = rgb_to_hex(c.dark_blue)
        white = rgb_to_hex(c.white)

        self.figure = QtWidgets.QWidget()
        self.figure.setWindowTitle(f"VHLab Spike Sorter: {self.session.reference}")
        self.figure.setObjectName(WINDOW_TAG)
        self.figure.setGeometry(int(x), int(y), int(w), int(h))
        self.figure.setStyleSheet(f"background-color: {navy};")

        root = QtWidgets.QVBoxLayout(self.figure)
        root.setContentsMargins(15, 15, 15, 15)
        root.setSpacing(10)

        title = QtWidgets.QLabel("VH Lab Interactive Spike Sorter")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {white}; font-size: 16px; font-weight: bold;")
        title.setFixedHeight(30)
        root.addWidget(title)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)  # MATLAB's WordWrap: the message is long
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(f"color: {white};")
        root.addWidget(self.status_label, 1)

        self.open_button = QtWidgets.QPushButton("Open Spike Sorter")
        self.open_button.setFixedHeight(40)
        self.open_button.setStyleSheet(
            f"background-color: {rgb_to_hex(c.light_blue)}; color: {navy}; font-weight: bold;"
        )
        self.open_button.setToolTip("Open the VH Lab spike sorting GUI for this session")
        self.open_button.clicked.connect(self.open_sorter)
        root.addWidget(self.open_button)

        self.refresh_availability()
        self.figure.show()
        return self.figure

    def refresh_availability(self) -> bool:
        """Re-ask whether the sorter is there and update the window; returns it."""
        available = self.is_available()
        if self.status_label is not None:
            self.status_label.setText(availability_message(available))
        if self.open_button is not None:
            self.open_button.setEnabled(available)
        return available

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def close(self) -> None:
        if self.figure is not None:
            self.figure.close()

    # ------------------------------------------------------------------
    # launching
    # ------------------------------------------------------------------
    def open_sorter(self) -> Any:
        """Hand the session to the sorter; returns whatever it returns.

        Re-checks availability first, as MATLAB does: the window may have
        been open a while, and a library that has appeared -- or gone --
        since should be reflected rather than assumed.
        """
        launcher = resolve_launcher()
        if launcher is None:
            self.refresh_availability()
            self.alert(NOT_FOUND_ALERT, "Spike sorter not found")
            return None

        try:
            # MATLAB's feval(LauncherFcn, 'ndiSession', obj.session). The
            # keyword is the sorter's, not NDI's, so it keeps MATLAB's
            # spelling: it is the external contract.
            return launcher(ndiSession=self.session)
        except Exception as exc:  # noqa: BLE001 - reported in a dialog, not raised
            self.alert(str(exc), "Could not open the VH Lab spike sorter")
            return None

    # ------------------------------------------------------------------
    # dialogs
    # ------------------------------------------------------------------
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
        self._held.append(box)
        box.finished.connect(lambda _=0, b=box: self._held.remove(b) if b in self._held else None)
        return box

    def __repr__(self) -> str:
        return f"vhNDISpikeSorter(available={self.is_available()})"


#: PascalCase spelling, for code that would rather not write a class name
#: that starts lowercase. The MATLAB spelling is the class itself.
VHNDISpikeSorter = vhNDISpikeSorter
