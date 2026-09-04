"""ndi.gui.app.pipeline_editor - open the graphical NDI pipeline editor.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+app/pipelineEditor.m``

A shell that hands the session to :func:`ndi.cpipeline.edit`, which builds
and owns its own window. On MATLAB the editor is a real GUI; on Python
``ndi.cpipeline`` is not ported yet, so the app opens with an unavailable
message and a disabled button rather than dying at construction. Grouped
at the top level of the Apps menu (MATLAB gives it no ``Category``), it is
still listed so users can see the editor as work the port has planned.

THE SAME AVAILABILITY-CHECK SHAPE :mod:`ndi.gui.app.vh_ndi_spike_sorter`
USES, and for the same reasons. MATLAB's pipeline editor lives in the
``ndi.cpipeline.edit`` package, which the port has not yet reached; this
window resolves that name at open time rather than at import, so:

* the app opens whether or not ``ndi.cpipeline`` exists on this Python;
* the unavailable message says what is actually true and what actually
  works, rather than telling a user to install a package that does not
  exist; and
* the day ``ndi.cpipeline`` DOES land, this app picks it up without a
  change here.

If a stack trace greeted the user in the meantime, "the editor is not
ported yet" would look like an installation problem for something that is
not an installation problem.
"""

from __future__ import annotations

import importlib
from typing import Any, ClassVar

from .session_app import SessionApp

__all__ = [
    "pipelineEditor",
    "PipelineEditor",
    "DEFAULT_POSITION",
    "WINDOW_TAG",
    "EDITOR_TARGET",
    "EDITOR_MODULE",
    "EDITOR_FUNCTION",
    "AVAILABLE_MESSAGE",
    "UNAVAILABLE_MESSAGE",
    "NOT_FOUND_ALERT",
    "resolve_editor",
    "availability_message",
]

#: Where the window opens, ``(x, y, width, height)``. MATLAB's editor
#: manages its own geometry, so this is only the small launcher window; its
#: footprint is deliberately similar to :mod:`ndi.gui.app.vh_ndi_spike_sorter`
#: since it plays the same role.
DEFAULT_POSITION: tuple[float, float, float, float] = (100, 100, 460, 200)

#: The window's object name, MATLAB's figure Tag.
WINDOW_TAG = "ndi.gui.app.pipelineEditor"

#: The external entry point this app wraps, as MATLAB spells it.
#: MATLAB resolves it as a package function; Python resolves it as
#: ``EDITOR_FUNCTION`` on the module ``EDITOR_MODULE``.
EDITOR_TARGET = "ndi.cpipeline.edit"
EDITOR_MODULE, EDITOR_FUNCTION = EDITOR_TARGET.rsplit(".", 1)

#: Shown when the editor can be launched.
AVAILABLE_MESSAGE = (
    "The graphical NDI pipeline editor is available. Click below to open it " "for this session."
)

#: Shown when it cannot. MATLAB's editor is a native part of the toolbox
#: there, so MATLAB never has to say this; on Python it is still to port,
#: and the sentence points at MATLAB rather than at a pip install that
#: will not help.
UNAVAILABLE_MESSAGE = (
    f"The graphical NDI pipeline editor ({EDITOR_TARGET}) is not available "
    "from Python. It ships with NDI-matlab and has not been ported yet: run "
    "it from MATLAB with ndi.gui.app.pipelineEditor, or make a Python "
    f"{EDITOR_TARGET} importable to use it here."
)

#: Shown if the button is pressed and the editor has gone away since the
#: window opened.
NOT_FOUND_ALERT = (
    f"{EDITOR_TARGET} could not be imported. See the message in the window: "
    "the NDI pipeline editor is not yet ported to Python."
)


def resolve_editor() -> Any | None:
    """The pipeline editor's entry point, or None when it is not installed.

    Follows :func:`ndi.gui.app.vh_ndi_spike_sorter.resolve_launcher`: every
    failure -- an absent module, a module that raises on import, a module
    without the function, a name that is not callable -- collapses to
    None, since the four mean the same thing to this app.
    """
    try:
        module = importlib.import_module(EDITOR_MODULE)
    except Exception:  # noqa: BLE001 - absent, or broken: not launchable either way
        return None
    editor = getattr(module, EDITOR_FUNCTION, None)
    return editor if callable(editor) else None


def availability_message(available: bool) -> str:
    """The sentence the window shows for each state."""
    return AVAILABLE_MESSAGE if available else UNAVAILABLE_MESSAGE


class pipelineEditor(SessionApp):  # noqa: N801 (MATLAB class name)
    """Open the graphical NDI pipeline editor for a session.

    ``pipelineEditor(session)`` opens the launcher window, which is the
    whole contract :class:`~ndi.gui.app.SessionApp` asks of an app. The
    editor itself, once available, builds and owns its own window; this app
    just hands the session to it and steps aside.

    MATLAB equivalent: ``ndi.gui.app.pipelineEditor``.
    """

    #: The Apps-menu label. Verbatim from MATLAB: it is user-visible text.
    Name: ClassVar[str] = "Pipeline Editor"

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
        """Whether the editor can be launched right now.

        Asked fresh each time rather than cached at construction, so a
        library that appears -- or is removed -- while the window is open
        is reflected by :meth:`refresh_availability` rather than assumed.
        """
        return resolve_editor() is not None

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
        self.figure.setWindowTitle(f"Pipeline Editor: {self.session.reference}")
        self.figure.setObjectName(WINDOW_TAG)
        self.figure.setGeometry(int(x), int(y), int(w), int(h))
        self.figure.setStyleSheet(f"background-color: {navy};")

        root = QtWidgets.QVBoxLayout(self.figure)
        root.setContentsMargins(15, 15, 15, 15)
        root.setSpacing(10)

        title = QtWidgets.QLabel("NDI Pipeline Editor")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {white}; font-size: 16px; font-weight: bold;")
        title.setFixedHeight(30)
        root.addWidget(title)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(f"color: {white};")
        root.addWidget(self.status_label, 1)

        self.open_button = QtWidgets.QPushButton("Open Pipeline Editor")
        self.open_button.setFixedHeight(40)
        self.open_button.setStyleSheet(
            f"background-color: {rgb_to_hex(c.light_blue)}; color: {navy}; font-weight: bold;"
        )
        self.open_button.setToolTip("Open the NDI pipeline editor for this session")
        self.open_button.clicked.connect(self.open_editor)
        root.addWidget(self.open_button)

        self.refresh_availability()
        self.figure.show()
        return self.figure

    def refresh_availability(self) -> bool:
        """Re-ask whether the editor is there and update the window; returns it."""
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
    def open_editor(self) -> Any:
        """Hand the session to the editor; returns whatever it returns.

        Re-checks availability first, as :meth:`refresh_availability` does
        on interaction: the window may have been open a while, and a
        library that appeared -- or went -- since should be reflected
        rather than assumed. MATLAB calls
        ``ndi.cpipeline.edit('command','new','session',SESSION)``; the same
        keyword arguments are handed to the resolved Python function.
        """
        editor = resolve_editor()
        if editor is None:
            self.refresh_availability()
            self.alert(NOT_FOUND_ALERT, "Pipeline editor not found")
            return None

        try:
            return editor(command="new", session=self.session)
        except Exception as exc:  # noqa: BLE001 - reported in a dialog, not raised
            self.alert(str(exc), "Could not open the NDI pipeline editor")
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
        return f"pipelineEditor(available={self.is_available()})"


#: PascalCase spelling, for code that would rather not write a class name
#: that starts lowercase. The MATLAB spelling is the class itself.
PipelineEditor = pipelineEditor
