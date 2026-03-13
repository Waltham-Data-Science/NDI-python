"""ndi.gui — Graphical user interface for NDI.

This package provides GUI tools for viewing and interacting with NDI
sessions, documents, and experimental data.  It uses **PySide6** (Qt for
Python) for cross-platform compatibility across macOS, Linux, and Windows.

Top-level functions
-------------------
gui
    Simple session viewer (v1).
gui_v2
    Enhanced viewer with Lab and Database tabs.

Classes
-------
Data
    Document table view with search/filter and graph visualisation.
Icon
    Draggable icon for the Lab view.
Lab
    Experiment view with connection wires.
docViewer
    Standalone document viewer window.

Sub-packages
------------
component
    Progress bars and monitors (``ProgressBarWindow``,
    ``NDIProgressBar``, ``CommandWindowProgressMonitor``).
utility
    Helper functions (``centerFigure``).

Install the GUI dependency with::

    pip install PySide6
"""

__all__ = [
    "gui",
    "gui_v2",
    "Data",
    "Icon",
    "Lab",
    "docViewer",
]


def __getattr__(name: str):  # noqa: ANN204
    """Lazy imports — all symbols are deferred so the package can be
    imported without PySide6 installed."""
    _lazy = {
        "gui": ("ndi.gui.gui", "gui"),
        "gui_v2": ("ndi.gui.gui_v2", "gui_v2"),
        "Data": ("ndi.gui.data", "Data"),
        "Icon": ("ndi.gui.icon", "Icon"),
        "Lab": ("ndi.gui.lab", "Lab"),
        "docViewer": ("ndi.gui.docViewer", "docViewer"),
    }
    if name in _lazy:
        import importlib

        mod_path, attr = _lazy[name]
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
