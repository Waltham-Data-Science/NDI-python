"""Tests for ndi.gui.nav.jobs_pane.

MATLAB counterpart: ndi.gui.nav.jobsPane (tested in MATLAB through
tests/+ndi/+unittest/+job/TestJob.m's rowsFor / durationText checks).

The rows, the text, the button states and the actions are plain Python and
run here without a display; the Qt build test skips without PySide6, as in
test_gui_nav_pane.py.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import pytest

from ndi.gui.nav.jobs_pane import (
    BODY_HEIGHT,
    COLUMNS,
    JobsPane,
    button_states,
    duration_text,
    remove_question,
    rows_for,
    short_time,
)
from ndi.gui.nav.pane import HEADER_HEIGHT
from ndi.job import ndi_job_Job

SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "ndi"
    / "ndi_common"
    / "job_schema"
    / "job.schema.json"
)


class Steps(ndi_job_Job):
    Kind = "test.jobsPane.steps"

    @classmethod
    def create(cls, n: int = 4, title: str = "steps") -> Steps:
        ndi_job_Job.register(cls.Kind, cls)
        job = cls()
        job.initialize(title, {"n": n})
        return job

    def work(self) -> None:
        n = self.spec["n"]
        for k in range(self.checkpoint.get("k", 0) + 1, n + 1):
            self.setCheckpoint("k", k)
            self.beat(k / n)


class FakeNavigator:
    def __init__(self):
        self.layouts = 0

    def pane_toggled(self, pane):
        pass

    def layout(self):
        self.layouts += 1


@pytest.fixture(autouse=True)
def jobs_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NDI_JOBS_DIR", str(tmp_path / "jobs"))
    # No real keep-awake helper (caffeinate / systemd-inhibit) from a test run.
    monkeypatch.setattr(ndi_job_Job, "_holdAwake", staticmethod(lambda key, label: None))
    yield tmp_path / "jobs"


class TestText:
    def test_duration_text(self):
        assert duration_text(float("nan")) == ""
        assert duration_text(None) == ""
        assert duration_text(59) == "<1m"
        assert duration_text(90) == "2m", "half away from zero, as MATLAB rounds"
        assert duration_text(12 * 60) == "12m"
        assert duration_text(3 * 3600 + 5 * 60) == "3h 05m"
        assert duration_text(2 * 86400 + 3 * 3600) == "2d 3h"

    def test_short_time_today_and_earlier(self):
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        today = short_time(now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        assert len(today) == 8 and today[2] == ":" and today[5] == ":"
        earlier = short_time("2020-03-04T12:00:00Z")
        assert earlier.startswith(("Mar 3", "Mar 4", "Mar 5")), earlier
        assert short_time("") == ""
        assert short_time("not a time") == "not a time"


class TestRowsAndButtons:
    def test_rows_follow_the_columns(self):
        job = Steps.create(4, "first")
        job.PauseAfterBeats = 1
        job.run()
        (row,) = rows_for([ndi_job_Job.load(job.id)])
        assert len(row) == len(COLUMNS)
        assert row[:4] == ["first", "paused", "25%", ""]
        assert row[4]

    def test_buttons_follow_the_state(self):
        assert not any(button_states(None).values())
        job = Steps.create(2)
        assert button_states(job) == {
            "pause": False,
            "resume": True,
            "restart": True,
            "remove": True,
        }
        job.state, job.host, job.pid = "running", ndi_job_Job.hostName(), os.getppid()
        assert button_states(job) == {
            "pause": True,
            "resume": False,
            "restart": False,
            "remove": False,
        }

    def test_remove_warns_about_an_unfinished_job(self):
        job = Steps.create(2)
        assert "cannot be resumed" in remove_question(job)
        job.run()
        assert "cannot be resumed" not in remove_question(job)


class TestThePane:
    def test_closed_without_jobs_open_with_one(self):
        p = JobsPane(FakeNavigator())
        assert p.has_body() and p.collapsible
        assert not p.engaged
        assert p.current_height() == HEADER_HEIGHT
        Steps.create(2)
        p.refresh()
        assert p.engaged, "a job appearing opens the pane"
        assert p.current_height() == HEADER_HEIGHT + BODY_HEIGHT
        assert JobsPane().engaged, "opens at once when a job exists"

    def test_pause_resume_restart_remove(self, jobs_dir):
        job = Steps.create(4)
        job.PauseAfterBeats = 2
        job.run()
        p = JobsPane()
        p.refresh()
        p.select(job.id)
        assert p.selected_job().state == "paused"
        assert p.resume_selected() == ""
        assert p.selected_job().state == "done"
        assert p.restart_selected() == ""
        assert p.selected_job().state == "done"
        p.remove_selected()
        assert p.jobs == [] and p.selected_job() is None
        assert not (jobs_dir / job.id).exists()

    def test_the_selection_survives_a_refresh(self):
        a = Steps.create(2, "a")
        b = Steps.create(2, "b")
        p = JobsPane()
        p.refresh()
        p.select(b.id)
        p.refresh()
        assert p.selected_job().id == b.id
        assert {j.id for j in p.jobs} == {a.id, b.id}

    def test_a_foreign_job_can_be_paused_not_resumed(self, jobs_dir):
        rec = json.loads(SCHEMA.read_text())["examples"][0]
        rec["kind"] = "someMatlabOnlyKind"  # one Python has no class for
        (jobs_dir / rec["id"]).mkdir(parents=True)
        (jobs_dir / rec["id"] / "job.json").write_text(json.dumps(rec))
        p = JobsPane()
        p.refresh()
        p.select(rec["id"])
        assert not button_states(p.selected_job())["resume"]
        assert "cannot run" in p.resume_selected()
        p.pause_selected()
        assert (jobs_dir / rec["id"] / "pause.request").is_file()


class TestARunningJobRefreshesThePane:
    def test_without_the_gui_loaded_nothing_is_imported(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "ndi.gui.navigator", raising=False)
        Steps.create(2).run()
        assert "ndi.gui.navigator" not in sys.modules

    def test_open_navigators_are_refreshed(self, monkeypatch):
        import ndi.gui.navigator as navmod

        refreshed = []

        class Pane:
            def refresh(self):
                refreshed.append(1)

        class Nav:
            def jobs_pane_handle(self):
                return Pane()

        monkeypatch.setattr(navmod.Navigator, "find_open", staticmethod(lambda: [Nav()]))
        Steps.create(3).run()
        # Forced at the start and the end; beats inside 5 s are skipped.
        assert len(refreshed) >= 2


def test_builds_under_qt():
    """Skips without PySide6 or a usable platform plugin, as test_gui_nav_pane does."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from ndi.gui._qt_helpers import get_or_create_app

        get_or_create_app()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no usable Qt platform plugin: {exc}")
    from PySide6 import QtWidgets

    job = Steps.create(2, "built")
    holder = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(holder)
    p = JobsPane()
    p.build(layout, 0)
    assert p.table.rowCount() == 1
    assert p.table.item(0, 0).text() == "built"
    p.select(job.id)
    assert p.resume_button.isEnabled()
    assert not p.pause_button.isEnabled()
    p.pause_selected()
    assert p.table.item(0, 1).text() == "pausing"
    p.refresh()
    assert p.table.selectionModel().selectedRows()[0].row() == 0, "kept across a refresh"
