"""ndi.job: the job record shared with NDI-matlab, and the run lifecycle.

MATLAB counterpart: tests/+ndi/+unittest/+job/TestJob.m. The job.json
format is ndi_common/job_schema/job.schema.json; a record written here must
validate against it, and a MATLAB record of a kind Python lacks must load
here as a listed, unrunnable job (the schema's own lightsheetToCloud
example, a kind Python runs too, is tested in test_job_lightsheet_to_cloud).
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path

import pytest

from ndi.job import ndi_job_ForeignJob, ndi_job_Job

SCHEMA = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "ndi"
    / "ndi_common"
    / "job_schema"
    / "job.schema.json"
)


class ScriptedJob(ndi_job_Job):
    """Beats spec['beats'] times (progress k/beats), resuming from the last beat reached."""

    Kind = "test.scripted"

    def __init__(self) -> None:
        super().__init__()
        self.RecountOnResume = False

    @classmethod
    def create(cls, beats: int = 5, outcome: str = "succeed") -> ScriptedJob:
        ndi_job_Job.register(cls.Kind, cls)
        job = cls()
        job.initialize(f"scripted {outcome}", {"beats": beats, "outcome": outcome})
        return job

    def work(self) -> None:
        n = self.spec["beats"]
        first = self.checkpoint.get("reached", 0) + 1
        if self.RecountOnResume and first > 1:
            self.beat(0, "recounting")
            self.setCheckpoint("shownWhileRecounting", self.progress)
            self.beat((first - 1) / n, "found what was done")
        for k in range(first, n + 1):
            self.setCheckpoint("reached", k)
            self.beat(k / n, f"step {k} of {n}")
        if self.spec["outcome"] == "fail":
            raise ValueError("The script failed on purpose.")


@pytest.fixture(autouse=True)
def jobs_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("NDI_JOBS_DIR", str(tmp_path / "jobs"))
    # No real keep-awake helper (caffeinate / systemd-inhibit) from a test run.
    monkeypatch.setattr(ndi_job_Job, "_holdAwake", staticmethod(lambda key, label: None))
    yield tmp_path / "jobs"


def write_record(folder: Path, record: dict) -> None:
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(json.dumps(record))


def matlab_example() -> dict:
    """The schema's example record: a lightsheetToCloud job MATLAB wrote."""
    return json.loads(SCHEMA.read_text())["examples"][0]


class TestTheLifecycle:
    def test_a_job_runs_to_done(self):
        job = ScriptedJob.create(3)
        job.run()
        assert job.state == "done"
        assert job.progress == 1
        again = ndi_job_Job.load(job.id)
        assert isinstance(again, ScriptedJob)
        assert again.state == "done"
        assert again.pid == 0

    def test_a_paused_job_resumes_where_it_stopped(self):
        job = ScriptedJob.create(4)
        job.PauseAfterBeats = 2
        job.run()
        assert job.state == "paused"
        assert job.message == "Paused at 50%."
        assert not job.pauseRequested(), "the runner clears the request"
        again = ndi_job_Job.load(job.id)
        again.run()
        assert again.state == "done"
        assert again.checkpoint["reached"] == 4
        assert math.isclose(again.runStartProgress, 0.5), "paced from where it resumed"

    def test_a_failure_is_recorded(self):
        job = ScriptedJob.create(2, "fail")
        job.run()
        assert job.state == "failed"
        assert "on purpose" in job.message
        assert "ValueError" in job.lastError
        assert job.canResume()

    def test_ctrl_c_is_recorded_as_interrupted(self):
        class Interrupted(ScriptedJob):
            def work(self):
                self.beat(0.3)
                raise KeyboardInterrupt

        job = Interrupted.create(2)
        with pytest.raises(KeyboardInterrupt):
            job.run()
        again = ndi_job_Job.load(job.id)
        assert again.state == "interrupted"
        assert again.message == "Interrupted at 30%."

    def test_restart_and_remove(self):
        job = ScriptedJob.create(4)
        job.PauseAfterBeats = 1
        job.run()
        job.restart()
        assert job.state == "queued"
        assert job.progress == 0
        assert job.checkpoint == {}
        folder = job.folder()
        job.remove()
        assert not folder.exists()

    def test_a_resume_that_recounts_keeps_its_place(self):
        job = ScriptedJob.create(10)
        job.PauseAfterBeats = 4
        job.run()
        again = ndi_job_Job.load(job.id)
        again.RecountOnResume = True
        again.run()
        assert again.state == "done"
        assert math.isclose(again.checkpoint["shownWhileRecounting"], 0.4)
        assert math.isclose(again.runStartProgress, 0.4)


class TestWhoIsRunningIt:
    def pretend_running(self, job, host, pid):
        job.state = "running"
        job.host = host
        job.pid = pid
        job.save()

    def test_a_vanished_runner_reads_interrupted(self):
        job = ScriptedJob.create(2)
        dead = 2**22 + 12345  # beyond any pid in use on a test machine
        assert not ndi_job_Job.processAlive(dead)
        self.pretend_running(job, ndi_job_Job.hostName(), dead)
        assert ndi_job_Job.load(job.id).effectiveState() == "interrupted"
        assert ndi_job_Job.load(job.id).canResume()

    def test_a_live_runner_is_not_overruled(self):
        job = ScriptedJob.create(2)
        self.pretend_running(job, ndi_job_Job.hostName(), os.getppid())
        again = ndi_job_Job.load(job.id)
        assert again.effectiveState() == "running"
        with pytest.raises(RuntimeError, match="already running"):
            again.run()
        with pytest.raises(RuntimeError, match="Pause"):
            again.remove()

    def test_another_computer_is_taken_at_its_word(self):
        job = ScriptedJob.create(2)
        self.pretend_running(job, "some-other-computer", 1)
        assert ndi_job_Job.load(job.id).effectiveState() == "running"

    def test_host_names_compare_without_domain(self):
        assert ndi_job_Job._sameHost("kip", "Kip.local")
        assert not ndi_job_Job._sameHost("kip", "kap")


class TestTheSharedFormat:
    def test_a_saved_record_matches_the_schema(self):
        jsonschema = pytest.importorskip("jsonschema")
        job = ScriptedJob.create(2)
        job.PauseAfterBeats = 1
        job.run()
        record = json.loads((job.folder() / "job.json").read_text())
        jsonschema.validate(record, json.loads(SCHEMA.read_text()))
        assert list(record) == list(ndi_job_Job._SAVED_FIELDS), "written in the MATLAB order"
        assert record["runtime"] == "python"

    def test_a_kind_python_lacks_is_listed_but_not_run(self, jobs_dir):
        rec = matlab_example()
        rec["kind"] = "someMatlabOnlyKind"
        write_record(jobs_dir / rec["id"], rec)
        jobs = ndi_job_Job.list()
        assert len(jobs) == 1
        job = jobs[0]
        assert isinstance(job, ndi_job_ForeignJob)
        assert job.kind == "someMatlabOnlyKind"
        assert job.runtime == "matlab"
        assert job.spec["numWorkers"] == 12
        assert not job.canResume()
        with pytest.raises(RuntimeError, match="cannot run"):
            job.run()
        # It can still be asked to pause: MATLAB sees the file at its next beat.
        job.requestPause()
        assert (jobs_dir / rec["id"] / "pause.request").is_file()

    def test_a_newer_format_is_not_run(self, jobs_dir):
        ScriptedJob.create(2)  # registers the kind
        rec = matlab_example()
        rec.update(kind=ScriptedJob.Kind, formatVersion=2, id="newer")
        write_record(jobs_dir / "newer", rec)
        assert isinstance(ndi_job_Job.load("newer"), ndi_job_ForeignJob)

    def test_an_unreadable_record_is_skipped(self, jobs_dir):
        (jobs_dir / "broken").mkdir(parents=True)
        (jobs_dir / "broken" / "job.json").write_text("{not json")
        ScriptedJob.create(2)
        assert len(ndi_job_Job.list()) == 1


class TestPercentAndTimeLeft:
    def test_one_hundred_percent_means_done(self):
        pct = ndi_job_Job.percentText
        assert pct(0.999) == "99%"
        assert pct(0.995) == "99%"
        assert pct(1) == "100%"
        assert pct(0.29) == "29%"
        assert pct(0) == "0%"

    def pretend_pace(self, job, start_progress, progress, started_seconds_ago):
        job.state = "running"
        job.host = ndi_job_Job.hostName()
        job.pid = ndi_job_Job.processId()
        now = dt.datetime.now(dt.timezone.utc)
        job.runStarted = (now - dt.timedelta(seconds=started_seconds_ago)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        job.runStartProgress = start_progress
        job.progress = progress
        job.heartbeat = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_time_left_follows_this_runs_pace(self):
        job = ScriptedJob.create(2)
        self.pretend_pace(job, 0, 0.25, 100)
        assert job.remainingSeconds() == pytest.approx(300, abs=5)
        self.pretend_pace(job, 0.5, 0.6, 60)
        assert job.remainingSeconds() == pytest.approx(240, abs=5)

    def test_no_time_left_without_a_pace(self):
        job = ScriptedJob.create(2)
        assert math.isnan(job.remainingSeconds()), "queued"
        self.pretend_pace(job, 0.2, 0.2, 300)
        assert math.isnan(job.remainingSeconds()), "no progress yet"
        self.pretend_pace(job, 0, 0.1, 10)
        assert math.isnan(job.remainingSeconds()), "too soon to say"

    def test_times_are_shown_in_local_time(self):
        t = ndi_job_Job.localTime("2026-01-01T00:00:00Z")
        assert len(t) == 19 and t[4] == "-" and t[10] == " "
        assert ndi_job_Job.localTime("") == ""
        assert ndi_job_Job.fromUtc("not a time") is None
