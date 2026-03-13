"""ndi.gui.component — Reusable GUI components for NDI.

Provides progress bars, progress monitors, and progress tracking
infrastructure.

Subpackages
-----------
abstract
    Abstract base classes (``ProgressMonitor``).
internal
    Progress tracking internals (``ProgressTracker``,
    ``AsynchProgressTracker``, event data classes).
"""

from ndi.gui.component.CommandWindowProgressMonitor import (
    CommandWindowProgressMonitor,
)

# Lazy imports for Qt-dependent components to avoid hard PySide6
# dependency at module load time.
__all__ = [
    "CommandWindowProgressMonitor",
    "NDIProgressBar",
    "ProgressBarWindow",
]


def __getattr__(name: str):  # noqa: ANN204
    if name == "NDIProgressBar":
        from ndi.gui.component.NDIProgressBar import NDIProgressBar

        return NDIProgressBar
    if name == "ProgressBarWindow":
        from ndi.gui.component.ProgressBarWindow import ProgressBarWindow

        return ProgressBarWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
