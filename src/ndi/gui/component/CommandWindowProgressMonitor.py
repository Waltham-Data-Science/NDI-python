"""CommandWindowProgressMonitor — Console-based progress display.

Mirrors MATLAB: ndi.gui.component.CommandWindowProgressMonitor

Displays progress updates in the terminal/console with optional
timestamps and in-place updating.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

from ndi.gui.component.abstract.ProgressMonitor import ProgressMonitor


class CommandWindowProgressMonitor(ProgressMonitor):
    """Progress monitor that prints updates to stdout.

    Parameters
    ----------
    **kwargs
        Property overrides.  In addition to those accepted by
        :class:`ProgressMonitor`, this class supports:

        * ``IndentSize`` (int, default 0)
        * ``ShowTimeStamp`` (bool, default False)
        * ``TimeStampFormat`` (str, default ``"%Y-%m-%d %H:%M:%S"``)
        * ``UpdateInplace`` (bool, default False)
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.IndentSize: int = kwargs.get("IndentSize", 0)
        self.ShowTimeStamp: bool = kwargs.get("ShowTimeStamp", False)
        self.TimeStampFormat: str = kwargs.get("TimeStampFormat", "%Y-%m-%d %H:%M:%S")
        self.UpdateInplace: bool = kwargs.get("UpdateInplace", False)
        self._prev_msg_len: int = 0

    # -- ProgressMonitor overrides ----------------------------------------

    def updateProgressDisplay(self) -> None:
        """Print current progress to stdout."""
        progress = self.getProgressValue()
        title = self.getProgressTitle()
        pct = progress * 100.0
        msg = f"{title}: {pct:.0f}%"
        msg = self.formatMessage(msg)
        self._print(msg)

    def updateMessage(self, message: str) -> None:
        """Print an updated message."""
        msg = self.formatMessage(message)
        self._print(msg)

    def finish(self) -> None:
        """Print the completion message."""
        title = self.getProgressTitle()
        msg = f"{title}: Complete"
        self._print(msg, force_newline=True)

    def reset(self) -> None:
        """Clear state for a fresh start."""
        super().reset()
        self._prev_msg_len = 0

    # -- Private helpers --------------------------------------------------

    def _print(self, message: str, *, force_newline: bool = False) -> None:
        formatted = self._format(message)
        if self.UpdateInplace and not force_newline:
            # Overwrite the previous line
            sys.stdout.write("\r" + " " * self._prev_msg_len + "\r")
            sys.stdout.write(formatted)
            sys.stdout.flush()
            self._prev_msg_len = len(formatted)
        else:
            if self.UpdateInplace and self._prev_msg_len > 0:
                sys.stdout.write("\n")
            print(formatted)  # noqa: T201
            self._prev_msg_len = 0

    def _format(self, message: str) -> str:
        indent = " " * self.IndentSize
        if self.ShowTimeStamp:
            ts = datetime.now().strftime(self.TimeStampFormat)
            return f"{indent}[{ts}] {message}"
        return f"{indent}{message}"
