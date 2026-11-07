"""ndi.gui.nav.jobs_pane - the collapsible "Jobs" pane.

MATLAB counterpart: ``src/ndi/+ndi/+gui/+nav/jobsPane.m``

Lists the jobs on this computer (:meth:`ndi.job.ndi_job_Job.list`) with
their state and progress, and controls the selected one:

    Pause    - ask it to stop at its next heartbeat (it saves its place)
    Resume   - run it again from where it stopped
    Restart  - forget its progress and run it from the beginning
    Remove   - delete its record from this computer

Columns: the job's name (hover for all of it), its state, how much is done,
an estimate of the time left while it runs (from this run's pace so far),
and when it last updated.

A job runs in this process, so while one runs the window is busy; the job
lets the window redraw at every heartbeat (``ndi_job_Job._refreshPane``),
which is when Pause and the progress column respond. Jobs MATLAB runs are
listed too, and Python can pause them (MATLAB sees the request at its next
heartbeat) and resume them -- except a kind only MATLAB defines, which loads
as an ndi_job_ForeignJob and can only be paused.

As elsewhere in this package, what the pane shows -- the rows, the duration
and time text, which buttons are enabled -- is plain Python and tested
without a display; only :meth:`JobsPane.build_body` and the button handlers
touch Qt.
"""

from __future__ import annotations

import datetime as _dt
import math
from typing import Any

from .pane import HEADER_HEIGHT, NavPane

__all__ = ["JobsPane", "BODY_HEIGHT", "COLUMNS", "rows_for", "duration_text", "short_time"]

#: Pixels of body: the table and the button row. MATLAB's BodyPx.
BODY_HEIGHT = 150

#: The table's column names, in MATLAB's order.
COLUMNS = ("Job", "State", "Done", "Left", "Updated")


def _round(x: float) -> int:
    """Round half away from zero, as MATLAB's round does (Python's rounds to even)."""
    return int(math.floor(x + 0.5))


def duration_text(s: float | None) -> str:
    """Seconds as ``'3h 05m'``, ``'12m'``, ``'<1m'``; ``''`` if None or NaN.

    MATLAB: ``ndi.gui.nav.jobsPane.durationText``.
    """
    if s is None or math.isnan(s):
        return ""
    if s < 60:
        return "<1m"
    if s < 3600:
        return f"{_round(s / 60)}m"
    if s < 86400:
        m = _round(s / 60)
        return f"{m // 60}h {m % 60:02d}m"
    h = _round(s / 3600)
    return f"{h // 24}d {h % 24}h"


def short_time(utc: str, now: _dt.datetime | None = None) -> str:
    """A stored UTC time, local: ``'HH:MM:SS'`` today, else ``'Mon d HH:MM'``.

    MATLAB: ``ndi.gui.nav.jobsPane.shortTime``. An unreadable time is shown
    as stored. NOW (local, for tests) defaults to the present.
    """
    from ndi.job import ndi_job_Job

    if not utc:
        return ""
    d = ndi_job_Job.fromUtc(utc)
    if d is None:
        return str(utc)
    d = d.astimezone()
    now = (now or _dt.datetime.now()).astimezone()
    if d.date() == now.date():
        return d.strftime("%H:%M:%S")
    return f"{d.strftime('%b')} {d.day} {d.strftime('%H:%M')}"


def rows_for(jobs: list[Any]) -> list[list[str]]:
    """The table rows for JOBS: title, state, done, time left, updated.

    MATLAB: ``ndi.gui.nav.jobsPane.rowsFor``.
    """
    from ndi.job import ndi_job_Job

    return [
        [
            j.title,
            j.effectiveState(),
            ndi_job_Job.percentText(j.progress),
            duration_text(j.remainingSeconds()),
            short_time(j.updated),
        ]
        for j in jobs
    ]


def button_states(job: Any | None) -> dict[str, bool]:
    """Which of Pause / Resume / Restart / Remove apply to JOB (None: no selection).

    Pause only a running job; Resume one that can resume; Restart and Remove
    anything not running. MATLAB: ``jobsPane.updateButtons``.
    """
    if job is None:
        return {"pause": False, "resume": False, "restart": False, "remove": False}
    st = job.effectiveState()
    return {
        "pause": st == "running",
        "resume": bool(job.canResume()),
        "restart": st != "running",
        "remove": st != "running",
    }


def remove_question(job: Any) -> str:
    """The confirmation asked before removing JOB."""
    msg = f'Remove the job "{job.title}" from this computer?'
    if job.effectiveState() != "done":
        msg += "\n\nIt has not finished, and cannot be resumed once removed."
    return msg


def restart_question(job: Any) -> str:
    """The confirmation asked before restarting JOB."""
    return f'Start "{job.title}" over from the beginning? What it has done so far is not reused.'


class JobsPane(NavPane):
    """The "Jobs" pane: a table of this computer's jobs and four controls."""

    def __init__(self, navigator: Any = None):
        from ndi.job import ndi_job_Job

        h = HEADER_HEIGHT + BODY_HEIGHT
        # Open only when there is something to show.
        super().__init__(
            navigator,
            title="Jobs",
            collapsible=True,
            engaged=bool(ndi_job_Job.list()),
            min_height=h,
            height=h,
        )
        #: The ndi_job_Job objects shown, in table order.
        self.jobs: list[Any] = []
        self.table: Any = None
        self.pause_button: Any = None
        self.resume_button: Any = None
        self.restart_button: Any = None
        self.remove_button: Any = None
        self._selected_id = ""

    def has_body(self) -> bool:
        return True

    # MATLAB's public property names (SetAccess = protected), read-only here.
    @property
    def Table(self) -> Any:
        return self.table

    @property
    def Jobs(self) -> list[Any]:
        return self.jobs

    @property
    def PauseButton(self) -> Any:
        return self.pause_button

    @property
    def ResumeButton(self) -> Any:
        return self.resume_button

    @property
    def RestartButton(self) -> Any:
        return self.restart_button

    @property
    def RemoveButton(self) -> Any:
        return self.remove_button

    # ------------------------------------------------------------------
    # model
    # ------------------------------------------------------------------
    def reload(self) -> list[list[str]]:
        """Re-read the jobs, keeping the selection by id; return the rows.

        Opens the pane (quietly: the window does not move) once a job exists.
        """
        from ndi.job import ndi_job_Job

        current = self.selected_job()
        if current is not None:
            self._selected_id = current.id
        self.jobs = ndi_job_Job.list()
        rows = rows_for(self.jobs)
        if self.jobs and not self.engaged:
            self.set_engaged_quietly(True)
        return rows

    def selected_job(self) -> Any | None:
        """The selected job, or None."""
        k = self._selected_row()
        if k is None or k >= len(self.jobs):
            return None
        return self.jobs[k]

    def select(self, job_id: str) -> None:
        """Select the job with JOB_ID (if listed)."""
        self._selected_id = job_id
        k = self._row_of(job_id)
        if self.table is not None and k is not None:
            self.table.selectRow(k)
        self._update_buttons()

    def refresh(self) -> None:
        """Re-read the jobs into the table; open the pane if one has appeared."""
        rows = self.reload()
        if self.table is not None:
            self._fill_table(rows)
        self._update_buttons()

    # ------------------------------------------------------------------
    # actions (no Qt, so a test can drive them; confirmations are asked
    # by the Qt handlers below before they get here)
    # ------------------------------------------------------------------
    def pause_selected(self) -> None:
        j = self.selected_job()
        if j is None:
            return
        j.requestPause()
        k = self._row_of(j.id)
        if self.table is not None and k is not None:
            self.table.item(k, 1).setText("pausing")

    def resume_selected(self) -> str:
        """Run the selected job; return an error message ('' if it ran)."""
        j = self.selected_job()
        if j is None:
            return ""
        return self._run_job(j)

    def restart_selected(self) -> str:
        j = self.selected_job()
        if j is None:
            return ""
        j.restart()
        return self._run_job(j)

    def remove_selected(self) -> None:
        j = self.selected_job()
        if j is None:
            return
        j.remove()
        self._selected_id = ""
        self.refresh()

    def _run_job(self, j: Any) -> str:
        try:
            j.run()
            err = ""
        except Exception as exc:  # noqa: BLE001 -- shown to the user
            err = str(exc)
        self.refresh()
        return err

    # ------------------------------------------------------------------
    # Qt
    # ------------------------------------------------------------------
    def build_body(self, container: Any) -> None:
        from PySide6 import QtWidgets

        layout = container.layout()
        layout.setContentsMargins(4, 4, 4, 4)

        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        for col, w in enumerate((80, 70, 50, 60)):
            self.table.setColumnWidth(col, w)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 1)

        row = QtWidgets.QWidget()
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        specs = (
            (
                "pause_button",
                "Pause",
                "Stop the selected job at its next step; Resume carries on from there",
                self._on_pause,
            ),
            (
                "resume_button",
                "Resume",
                "Run the selected job from where it stopped",
                self._on_resume,
            ),
            (
                "restart_button",
                "Restart",
                "Forget the selected job's progress and run it from the beginning",
                self._on_restart,
            ),
            (
                "remove_button",
                "Remove",
                "Delete the selected job's record from this computer",
                self._on_remove,
            ),
        )
        for attr, text, tip, slot in specs:
            b = QtWidgets.QPushButton(text)
            b.setToolTip(tip)
            b.setFixedHeight(26)
            b.clicked.connect(slot)
            self.accent_button(b)
            rl.addWidget(b, 1)
            setattr(self, attr, b)
        layout.addWidget(row, 0)
        self.refresh()

    def _fill_table(self, rows: list[list[str]]) -> None:
        from PySide6 import QtWidgets

        t = self.table
        t.blockSignals(True)
        try:
            t.setRowCount(len(rows))
            for r, values in enumerate(rows):
                for c, v in enumerate(values):
                    item = QtWidgets.QTableWidgetItem(v)
                    if c == 0:
                        item.setToolTip(v)
                    t.setItem(r, c, item)
            k = self._row_of(self._selected_id)
            if k is not None:
                t.selectRow(k)
            else:
                t.clearSelection()
        finally:
            t.blockSignals(False)

    def _update_buttons(self) -> None:
        if self.pause_button is None:
            return
        s = button_states(self.selected_job())
        self.pause_button.setEnabled(s["pause"])
        self.resume_button.setEnabled(s["resume"])
        self.restart_button.setEnabled(s["restart"])
        self.remove_button.setEnabled(s["remove"])

    def _on_selection_changed(self) -> None:
        j = self.selected_job()
        self._selected_id = j.id if j is not None else ""
        self._update_buttons()

    def _window(self) -> Any:
        return self.panel.window() if self.panel is not None else None

    def _confirm(self, text: str, title: str, action: str) -> bool:
        from PySide6 import QtWidgets

        box = QtWidgets.QMessageBox(self._window())
        box.setWindowTitle(title)
        box.setText(text)
        ok = box.addButton(action, QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is ok

    def _report_run(self, j: Any, err: str) -> None:
        from PySide6 import QtWidgets

        if err:
            QtWidgets.QMessageBox.warning(self._window(), "Could not run the job", err)
        elif j.state == "failed":
            QtWidgets.QMessageBox.warning(self._window(), f'Job "{j.title}" failed', j.message)

    def _on_pause(self) -> None:
        self.pause_selected()

    def _on_resume(self) -> None:
        j = self.selected_job()
        if j is not None:
            self._report_run(j, self.resume_selected())

    def _on_restart(self) -> None:
        j = self.selected_job()
        if j is None or not self._confirm(restart_question(j), "Restart job", "Restart"):
            return
        self._report_run(j, self.restart_selected())

    def _on_remove(self) -> None:
        j = self.selected_job()
        if j is None or not self._confirm(remove_question(j), "Remove job", "Remove"):
            return
        self.remove_selected()

    # ------------------------------------------------------------------
    # selection bookkeeping
    # ------------------------------------------------------------------
    def _selected_row(self) -> int | None:
        if self.table is not None:
            rows = self.table.selectionModel().selectedRows()
            return rows[0].row() if rows else None
        return self._row_of(self._selected_id)

    def _row_of(self, job_id: str) -> int | None:
        if not job_id:
            return None
        for k, j in enumerate(self.jobs):
            if j.id == job_id:
                return k
        return None
