"""ndi.gui — Graphical user interface for NDI.

This package provides GUI tools for viewing and interacting with NDI
sessions, documents, and experimental data.  It uses **PySide6** (Qt for
Python) for cross-platform compatibility across macOS, Linux, and Windows.

Top-level functions
-------------------
gui
    Simple session viewer (v1).
gui_v2
    Enhanced viewer with ndi_gui_Lab and ndi_database tabs.

Classes
-------
ndi_gui_Data
    ndi_document table view with search/filter and graph visualisation.
ndi_gui_Icon
    Draggable icon for the ndi_gui_Lab view.
ndi_gui_Lab
    Experiment view with connection wires.
ndi_gui_docViewer
    Standalone document viewer window.

Sub-packages
------------
component
    Progress bars and monitors (``ndi_gui_component_ProgressBarWindow``,
    ``ndi_gui_component_NDIProgressBar``, ``ndi_gui_component_CommandWindowProgressMonitor``).
utility
    Helper functions (``centerFigure``).

Install the GUI dependency with::

    pip install PySide6
"""

__all__ = [
    "gui",
    "gui_v2",
    "ndi_gui_Data",
    "ndi_gui_Icon",
    "ndi_gui_Lab",
    "ndi_gui_docViewer",
]


def __getattr__(name: str):  # noqa: ANN204
    """Lazy imports — all symbols are deferred so the package can be
    imported without PySide6 installed."""
    _lazy = {
        "gui": ("ndi.gui.gui", "gui"),
        "gui_v2": ("ndi.gui.gui_v2", "gui_v2"),
        "ndi_gui_Data": ("ndi.gui.data", "ndi_gui_Data"),
        "ndi_gui_Icon": ("ndi.gui.icon", "ndi_gui_Icon"),
        "ndi_gui_Lab": ("ndi.gui.lab", "ndi_gui_Lab"),
        "ndi_gui_docViewer": ("ndi.gui.ndi_gui_docViewer", "ndi_gui_docViewer"),
    }
    if name in _lazy:
        import importlib

        mod_path, attr = _lazy[name]
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
