"""ndi.gui.nav.session_table - a window showing one summary table of a session.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/sessionTable.m``

Builds one of the session summary tables of :mod:`ndi.fun.doc_table` and
shows it. The target of the navigator's per-session "Session > Tables"
submenu (VH-Lab/NDI-matlab#1243):

=============  ==============================
Menu item      Builds
=============  ==============================
Elements...    ``ndi.fun.doc_table.element``
Epochs...      ``ndi.fun.doc_table.epoch``
Probes...      ``ndi.fun.doc_table.probe``
Subjects...    ``ndi.fun.doc_table.subject``
Treatments...  ``ndi.fun.doc_table.treatment``
=============  ==============================

The window has a heading with the row count, "Assign to workspace..." (puts
the DataFrame in ``__main__``'s globals, the navigator's workspace) and
"Export CSV...", and the table itself with every cell shown as text. The
table is built once, at construction. The helpers that decide what is shown
are module functions, testable without a display.
"""

from __future__ import annotations

import importlib
import math
from typing import Any

from ..cloud_colors import cloud_colors, rgb_to_hex

__all__ = [
    "SessionTable",
    "TABLE_KINDS",
    "table_kinds",
    "kind_info",
    "compute_table",
    "summary_text",
    "table_cells",
    "cell_text",
    "session_ref",
]

#: The session tables, in menu (alphabetical) order. Fields as in MATLAB's
#: tableKinds: Kind, Label, Title, VariableName, Function (the MATLAB
#: function); ``python_function`` is the doc_table function called here.
TABLE_KINDS: tuple[dict[str, str], ...] = (
    {
        "Kind": "element",
        "Label": "Elements...",
        "Title": "Element table",
        "VariableName": "elementTable",
        "Function": "ndi.fun.docTable.element",
        "python_function": "element",
    },
    {
        "Kind": "epoch",
        "Label": "Epochs...",
        "Title": "Epoch table",
        "VariableName": "epochTable",
        "Function": "ndi.fun.docTable.epoch",
        "python_function": "epoch",
    },
    {
        "Kind": "probe",
        "Label": "Probes...",
        "Title": "Probe table",
        "VariableName": "probeTable",
        "Function": "ndi.fun.docTable.probe",
        "python_function": "probe",
    },
    {
        "Kind": "subject",
        "Label": "Subjects...",
        "Title": "Subject table",
        "VariableName": "subjectTable",
        "Function": "ndi.fun.docTable.subject",
        "python_function": "subject",
    },
    {
        "Kind": "treatment",
        "Label": "Treatments...",
        "Title": "Treatment table",
        "VariableName": "treatmentTable",
        "Function": "ndi.fun.docTable.treatment",
        "python_function": "treatment",
    },
)

UNNAMED_SESSION = "(unnamed session)"


def table_kinds() -> list[dict[str, str]]:
    """The session tables, in menu order (copies, safe to modify)."""
    return [dict(k) for k in TABLE_KINDS]


def kind_info(kind: str) -> dict[str, str]:
    """The :data:`TABLE_KINDS` entry for KIND (case-insensitive)."""
    for k in TABLE_KINDS:
        if k["Kind"].lower() == str(kind).lower():
            return dict(k)
    raise ValueError(
        f'Unknown session table kind "{kind}". Expected one of: '
        + ", ".join(k["Kind"] for k in TABLE_KINDS)
        + "."
    )


def compute_table(session: Any, kind: str) -> Any:
    """Build the KIND table for SESSION.

    Calls the :mod:`ndi.fun.doc_table` function for KIND and returns its
    table: a function that returns a tuple (``treatment``) gives its first
    element, as MATLAB keeps its first output. Anything that is not a
    DataFrame becomes an empty DataFrame.
    """
    import pandas as pd

    info = kind_info(kind)
    doc_table = importlib.import_module("ndi.fun.doc_table")
    result = getattr(doc_table, info["python_function"])(session)
    if isinstance(result, tuple):
        result = result[0] if result else None
    if not isinstance(result, pd.DataFrame):
        result = pd.DataFrame()
    return result


def summary_text(title: str, table: Any) -> str:
    """Heading text, e.g. ``'Subject table (3 rows)'``."""
    try:
        n = len(table.index)
    except Exception:  # noqa: BLE001 - not a DataFrame: no rows
        n = 0
    return f"{title} (1 row)" if n == 1 else f"{title} ({n} rows)"


def _is_missing_scalar(v: Any) -> bool:
    if v is None:
        return True
    try:
        import pandas as pd

        if v is pd.NaT:
            return True
    except ImportError:  # pragma: no cover - pandas is required by compute_table
        pass
    return isinstance(v, float) and math.isnan(v)


def _matlab_num(v: Any) -> str:
    """A number the way MATLAB's num2str/mat2str writes it (3, not 3.0)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return f"{v:.5g}" if isinstance(v, float) else str(v)


def cell_text(v: Any) -> str:
    """Format one table value as display text, as MATLAB's cellText does.

    str -> itself; None / NaN / NaT / empty -> ``''``; bool -> ``'true'`` /
    ``'false'``; number -> as MATLAB's num2str writes it; a numeric
    sequence or array -> MATLAB's ``'[1 2]'``; a list/tuple of other things
    -> the elements' texts, blanks dropped, joined with ``', '``; dict ->
    ``'<struct>'``; datetimes and the rest -> ``str``.
    """
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        np = None  # type: ignore[assignment]

    if isinstance(v, str):
        return v
    if np is not None and isinstance(v, np.ndarray):
        v = v.tolist()
    if np is not None and isinstance(v, np.generic):
        v = v.item()
    if _is_missing_scalar(v):
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return _matlab_num(v)
    if isinstance(v, dict):
        return "<struct>"
    if isinstance(v, (list, tuple)):
        if not v:
            return ""
        if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            if all(isinstance(x, float) and math.isnan(x) for x in v):
                return ""
            return "[" + " ".join(_matlab_num(x) for x in v) + "]"
        parts = [cell_text(x) for x in v]
        return ", ".join(p for p in parts if p)
    return str(v)


def table_cells(table: Any) -> tuple[list[str], list[list[str]]]:
    """Column names and an all-text grid of rows for display.

    An empty or non-DataFrame TABLE gives ``([], [])``.
    """
    try:
        names = [str(c) for c in table.columns]
    except Exception:  # noqa: BLE001
        return [], []
    if not names:
        return [], []
    rows = [[cell_text(v) for v in row] for row in table.itertuples(index=False, name=None)]
    return names, rows


def session_ref(session: Any) -> str:
    """A session's reference for the window title, best effort."""
    try:
        ref = str(session.reference or "")
    except Exception:  # noqa: BLE001
        ref = ""
    return ref or UNNAMED_SESSION


class SessionTable:
    """A window showing one summary table of a session.

    Constructing it builds the table (``self.table``, a DataFrame);
    :meth:`build` creates the widgets. They are separate so the table can
    be tested without a display.
    """

    def __init__(self, session: Any, kind: str, *, build: bool = True):
        self.session = session
        self.kind = kind_info(kind)["Kind"]
        self.table = compute_table(session, self.kind)
        self.figure: Any = None
        self.ui_table: Any = None
        if build:
            self.build()

    # ------------------------------------------------------------------
    # actions (no Qt needed when a name / path is given)
    # ------------------------------------------------------------------
    def assign_to_workspace(self, name: str | None = None) -> str | None:
        """Put the table in a workspace variable (``__main__``'s globals).

        Asks for a name (default e.g. ``subjectTable``) unless NAME is given.
        Returns the name assigned, or None when nothing was.
        """
        from . import datasets_model
        from .datasets_text import workspace_name_error

        title = "Assign to workspace"
        if name is None:
            name = self._ask_text(
                "Workspace variable name:", title, kind_info(self.kind)["VariableName"]
            )
            if name is None:
                return None
        name = name.strip()
        message = workspace_name_error(name)
        if message:
            self._alert(message, title)
            return None
        try:
            datasets_model.assign_workspace_var(name, self.table)
        except Exception as exc:  # noqa: BLE001
            self._alert(str(exc), title)
            return None
        return name

    def export_csv(self, path: str | None = None) -> str | None:
        """Write the table (as displayed text) to a CSV file.

        Asks for the file unless PATH is given. Returns the path written,
        or None when nothing was.
        """
        import pandas as pd

        if path is None:
            path = self._ask_save_path(f"{kind_info(self.kind)['VariableName']}.csv")
            if not path:
                return None
        try:
            names, rows = table_cells(self.table)
            pd.DataFrame(rows, columns=names).to_csv(path, index=False)
        except Exception as exc:  # noqa: BLE001
            self._alert(str(exc), "Export CSV")
            return None
        return path

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build(self) -> Any:
        """Create the window and fill the table."""
        from .._qt_helpers import get_or_create_app, require_qt

        require_qt()
        get_or_create_app()
        from PySide6 import QtWidgets

        c = cloud_colors()
        info = kind_info(self.kind)

        self.figure = QtWidgets.QWidget()
        self.figure.setWindowTitle(f"{info['Title']}: {session_ref(self.session)}")
        self.figure.setObjectName("ndiNavigatorSessionTable")
        self.figure.resize(900, 520)
        self.figure.setStyleSheet(f"background-color: {rgb_to_hex(c.dark_blue)};")

        layout = QtWidgets.QVBoxLayout(self.figure)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        header = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel(summary_text(info["Title"], self.table))
        label.setStyleSheet(f"color: {rgb_to_hex(c.white)}; font-weight: bold;")
        header.addWidget(label, 1)
        assign = QtWidgets.QPushButton("Assign to workspace...")
        assign.clicked.connect(lambda: self.assign_to_workspace())
        header.addWidget(assign)
        export = QtWidgets.QPushButton("Export CSV...")
        export.clicked.connect(lambda: self.export_csv())
        header.addWidget(export)
        layout.addLayout(header)

        names, rows = table_cells(self.table)
        table = QtWidgets.QTableWidget(len(rows), len(names))
        table.setHorizontalHeaderLabels(names)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setStyleSheet(
            f"background-color: {rgb_to_hex(c.white)}; color: {rgb_to_hex(c.dark_blue)};"
        )
        for r, row in enumerate(rows):
            for col, value in enumerate(row):
                table.setItem(r, col, QtWidgets.QTableWidgetItem(value))
        layout.addWidget(table, 1)
        self.ui_table = table
        return self.figure

    def show(self) -> None:
        if self.figure is not None:
            self.figure.show()

    def _ask_text(self, prompt: str, title: str, default: str) -> str | None:
        from PySide6 import QtWidgets

        text, ok = QtWidgets.QInputDialog.getText(self.figure, title, prompt, text=default)
        return text if ok else None

    def _ask_save_path(self, default: str) -> str:
        from PySide6 import QtWidgets

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self.figure, "Export CSV", default, "CSV files (*.csv)"
        )
        return path

    def _alert(self, message: str, title: str) -> None:
        if self.figure is None:
            return
        from PySide6 import QtWidgets

        QtWidgets.QMessageBox.warning(self.figure, title, message)

    def __repr__(self) -> str:
        return f"SessionTable(session={session_ref(self.session)!r}, kind={self.kind!r})"
