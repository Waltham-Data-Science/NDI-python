"""ndi.gui.component — Reusable GUI components for NDI.

Provides progress bars, progress monitors, and progress tracking
infrastructure.

Subpackages
-----------
abstract
    Abstract base classes (``ndi_gui_component_abstract_ProgressMonitor``).
internal
    Progress tracking internals (``ndi_gui_component_internal_ProgressTracker``,
    ``ndi_gui_component_internal_AsynchProgressTracker``, event data classes).
"""

from ndi.gui.component.ndi_gui_component_CommandWindowProgressMonitor import (
    ndi_gui_component_CommandWindowProgressMonitor,
)

# Lazy imports for Qt-dependent components to avoid hard PySide6
# dependency at module load time.
__all__ = [
    "ndi_gui_component_CommandWindowProgressMonitor",
    "ndi_gui_component_NDIProgressBar",
    "ndi_gui_component_ProgressBarWindow",
]


def __getattr__(name: str):  # noqa: ANN204
    if name == "ndi_gui_component_NDIProgressBar":
        from ndi.gui.component.ndi_gui_component_NDIProgressBar import ndi_gui_component_NDIProgressBar

        return ndi_gui_component_NDIProgressBar
    if name == "ndi_gui_component_ProgressBarWindow":
        from ndi.gui.component.ndi_gui_component_ProgressBarWindow import ndi_gui_component_ProgressBarWindow

        return ndi_gui_component_ProgressBarWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
