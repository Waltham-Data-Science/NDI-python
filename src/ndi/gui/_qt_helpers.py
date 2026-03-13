"""Shared Qt import helpers for the ndi.gui package.

PySide6 is the recommended GUI toolkit.  All Qt imports in this package
go through this module so that the dependency is isolated and a clear
error message is shown when PySide6 is not installed.
"""

from __future__ import annotations

_QT_AVAILABLE: bool = False
_QT_IMPORT_ERROR: str = ""

try:
    from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401

    _QT_AVAILABLE = True
except ImportError as exc:
    _QT_IMPORT_ERROR = str(exc)


def require_qt() -> None:
    """Raise *ImportError* with a helpful message if PySide6 is missing."""
    if not _QT_AVAILABLE:
        raise ImportError(
            "PySide6 is required for ndi.gui graphical components.  "
            "Install it with:  pip install PySide6\n"
            f"(Original error: {_QT_IMPORT_ERROR})"
        )


def get_or_create_app() -> QtWidgets.QApplication:
    """Return the running QApplication or create one.

    This is safe to call multiple times; only one QApplication will ever
    exist per process.
    """
    require_qt()
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app
