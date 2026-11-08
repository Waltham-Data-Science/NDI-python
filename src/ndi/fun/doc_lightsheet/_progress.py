"""The 'default' progress callback of fromOMEZarr / fromSPIM.

MATLAB opens an ndi.gui.component.ProgressBarWindow bar (and reports nothing
if it cannot). Python opens the same bar when a Qt application is running,
and otherwise prints a line to standard error at most every 10 seconds --
a Python build is as often run from a terminal or a job as from the GUI.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Any


def resolveProgressCallback(spec: Any, barLabel: str, kind: str) -> Callable | None:
    """A callable(fraction, text) for SPEC: a callable, None/'' (none), or 'default'/'auto'."""
    if callable(spec):
        return spec
    if spec is None or (isinstance(spec, str) and not spec):
        return None
    if not isinstance(spec, str) or spec.lower() not in ("default", "auto"):
        raise ValueError(f"progressFcn must be 'default', a function, or None; got {spec!r}.")
    try:
        from PySide6 import QtWidgets

        if QtWidgets.QApplication.instance() is not None:
            from ndi.gui.component.ProgressBarWindow import ndi_gui_component_ProgressBarWindow
            from ndi.ido import ndi_ido

            tag = f"lightsheet-{kind}-{ndi_ido.unique_id()[:12]}"
            pbw = ndi_gui_component_ProgressBarWindow("NDI lightsheet ingest")
            pbw.addBar(Label=barLabel, Tag=tag, Auto=True)
            return lambda frac, txt: pbw.updateBar(tag, min(1.0, max(0.0, float(frac))))
    except Exception:  # noqa: BLE001 -- no GUI: report on the terminal instead
        pass
    last = [0.0]

    def printer(frac: float, txt: str) -> None:
        now = time.monotonic()
        if frac >= 1 or now - last[0] >= 10:
            last[0] = now
            print(f"{barLabel}: {100 * float(frac):5.1f}%  {txt}", file=sys.stderr, flush=True)

    return printer
