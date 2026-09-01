"""ndi.gui.nav - the panes that make up ndi.gui.navigator.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/``

A pane is a single horizontal region of the navigator window. The first
(header) row of a pane is always visible and holds a disclosure triangle for
collapsible panes, a title, and an optional right-hand control. Panes that
carry a body render it in a second row shown only while the pane is engaged.

WHY THE LOGIC AND THE WIDGETS ARE SEPARATED HERE
MATLAB's panes interleave layout arithmetic with widget construction, which
is fine there and untestable here: this port has no cross-language artifact
to compare a layout against, the way the VHSB and parseText batteries compare
computed results. So the parts that CAN be checked -- the engaged/collapsed
state machine, the height arithmetic, the disclosure glyph and tooltip, the
palette -- are plain Python on ``NavPane`` and are unit-tested without a
display. ``build()`` is the only method that touches Qt, and it is tested too,
under QT_QPA_PLATFORM=offscreen: the wiring is checkable even though the
appearance is not.
"""

from __future__ import annotations

from . import datasets_cloud, datasets_model, datasets_text
from .cloud_pane import CloudPane
from .datasets_pane import DatasetsPane
from .ndi_pane import NdiPane
from .pane import NavPane
from .progress_pane import ProgressPane
from .session_info import SessionInfo
from .status_icon import status_icon, statusIcon

__all__ = [
    "datasets_cloud",
    "datasets_model",
    "datasets_text",
    "CloudPane",
    "DatasetsPane",
    "NavPane",
    "NdiPane",
    "ProgressPane",
    "SessionInfo",
    "status_icon",
    "statusIcon",
]
