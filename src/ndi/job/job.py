"""ndi.job.job - a long piece of work that can be paused, resumed and restarted.

MATLAB counterpart: ``+ndi/+job/Job.m``.

A job is one long task, kept as a folder under :meth:`ndi_job_Job.root`
(``~/.ndi/jobs`` unless ``$NDI_JOBS_DIR`` is set) with a ``job.json``
describing it. Everything the job needs to carry on is in that folder, so a
job interrupted by a crash or by quitting can be resumed where it stopped,
and a job started by MATLAB can be listed -- and paused -- from Python, and
the other way round.

THE FORMAT IS SHARED WITH NDI-MATLAB: ``ndi_common/job_schema/job.schema.json``
(formatVersion 1). ``kind`` is a language-neutral name mapped to a class by
each language's registry (:meth:`ndi_job_Job.register`); a job whose kind this
Python does not know (a MATLAB-only kind such as ``lightsheetToCloud``), or
whose formatVersion is newer than it reads, loads as an
:class:`ndi.job.foreign_job.ndi_job_ForeignJob`: listed, never run.

The lifecycle:

    queued       created, never run
    running      RUN is working on it (a vanished runner reads 'interrupted')
    paused       stopped at a request (requestPause), resumable
    interrupted  stopped without finishing (Ctrl+C, a crash), resumable
    failed       WORK raised; the report is in lastError; resumable
    done         finished

Pausing is cooperative: :meth:`requestPause` leaves a ``pause.request`` file
in the job's folder, which the runner sees at its next :meth:`beat`.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import os
import shutil
import socket
import sys
import time
import traceback
from pathlib import Path
from typing import Any, ClassVar

from pydantic import validate_call

from ndi.ido import ndi_ido


class _JobPaused(Exception):
    """Raised by beat() when a pause was requested ('NDI:job:paused' in MATLAB)."""


class ndi_job_Job:
    """A long piece of work that can be paused, resumed and restarted.

    A subclass sets the class attribute ``Kind`` and defines :meth:`work`
    (and may define :meth:`onRestart`); everything else is here.
    """

    #: The job.json format this code writes and reads.
    FormatVersion: ClassVar[int] = 1
    #: The language-neutral kind name a subclass runs.
    Kind: ClassVar[str] = ""

    #: The job.json fields, in the order written (see job.schema.json).
    _SAVED_FIELDS: ClassVar[tuple[str, ...]] = (
        "formatVersion",
        "id",
        "kind",
        "runtime",
        "title",
        "created",
        "updated",
        "state",
        "progress",
        "message",
        "lastError",
        "heartbeat",
        "runStarted",
        "runStartProgress",
        "host",
        "pid",
        "spec",
        "checkpoint",
    )

    #: kind -> class, for this Python process. Python ships no kinds yet.
    _registry: ClassVar[dict[str, type]] = {}

    def __init__(self) -> None:
        self.formatVersion: int = ndi_job_Job.FormatVersion
        self.id: str = ""
        self.kind: str = ""
        self.runtime: str = "python"
        self.title: str = ""
        self.created: str = ""
        self.state: str = "queued"
        self.progress: float = 0.0
        self.message: str = ""
        self.lastError: str = ""
        self.updated: str = ""
        self.heartbeat: str = ""
        self.runStarted: str = ""
        self.runStartProgress: float = 0.0
        self.host: str = ""
        self.pid: int = 0
        self.spec: dict[str, Any] = {}
        self.checkpoint: dict[str, Any] = {}
        # Test hooks, as in MATLAB: Api is handed to whatever cloud writer
        # a job makes; PauseAfterBeats requests a pause after that many beats.
        self.Api: Any = None
        self.PauseAfterBeats: float = math.inf
        # Private, not saved.
        self._lastSaved: float | None = None
        self._beats = 0
        self._catchingUp = False
        self._runBegan: float | None = None
        self._lastPaneRefresh: float | None = None

    # -- the work --------------------------------------------------------

    def work(self) -> None:
        """Do the job's work, calling :meth:`beat` regularly. Subclasses define it."""
        raise NotImplementedError(f"{type(self).__name__} defines no work().")

    def onRestart(self) -> None:
        """Discard what a fresh start must not reuse. Subclasses may define it."""

    # -- public methods (MATLAB names) -----------------------------------

    def folder(self) -> Path:
        """The job's folder."""
        return ndi_job_Job.root() / self.id

    def run(self) -> None:
        """Do the work: from the start, or from where it stopped.

        Returns when the job is done, paused or failed; the outcome is in
        ``state`` (and ``lastError``). Refused while another process is
        running the same job. Ctrl+C (KeyboardInterrupt) is recorded as
        'interrupted' and re-raised.
        """
        if self.effectiveState() == "running":
            raise RuntimeError(
                f'Job "{self.title}" is already running (process {self.pid} on {self.host}).'
            )
        if self.state == "done":
            return
        self._clearPause()
        self.state = "running"
        self.runtime = "python"
        self.host = ndi_job_Job.hostName()
        self.pid = ndi_job_Job.processId()
        self.lastError = ""
        self.message = "Starting..."
        self.runStarted = ndi_job_Job.now()
        self.runStartProgress = self.progress
        self._catchingUp = self.progress > 0
        self._runBegan = time.monotonic()
        self._beats = 0
        self.save()
        self._refreshPane(True)
        try:
            self.work()
            self.state = "done"
            self.progress = 1.0
            self.message = "Done."
        except _JobPaused:
            self.state = "paused"
            self.message = f"Paused at {ndi_job_Job.percentText(self.progress)}."
            self._clearPause()
        except KeyboardInterrupt:
            self.state = "interrupted"
            self.message = f"Interrupted at {ndi_job_Job.percentText(self.progress)}."
            self.pid = 0
            self.save()
            self._refreshPane(True)
            raise
        except Exception as exc:  # noqa: BLE001 -- any failure of the work is recorded
            self.state = "failed"
            self.message = str(exc)
            self.lastError = "".join(traceback.format_exception(exc))
        self.pid = 0
        self.save()
        self._refreshPane(True)

    def beat(self, fraction: float, text: str = "") -> None:
        """WORK's regular sign of life: progress, and the chance to pause.

        Records progress (saved at most every 5 s) and stops the job (with a
        pause) if one was requested. Pass it as a progress callback.
        """
        fraction = max(0.0, min(1.0, float(fraction)))
        if fraction >= self.runStartProgress:
            if self._catchingUp and fraction == self.runStartProgress:
                # Still where it resumed: the pace starts from here.
                self.runStarted = ndi_job_Job.now()
            else:
                self._catchingUp = False
        elif (
            self._catchingUp
            and self._runBegan is not None
            and time.monotonic() - self._runBegan < 1800
        ):
            # A resumed run recounting what is already done: keep showing
            # where it was, and pace from when it is back there.
            self.runStarted = ndi_job_Job.now()
            fraction = self.runStartProgress
        else:
            # Progress went back (counted differently): pace from here.
            self._catchingUp = False
            self.runStarted = ndi_job_Job.now()
            self.runStartProgress = fraction
        self.progress = fraction
        if text:
            self.message = str(text)
        self.heartbeat = ndi_job_Job.now()
        self._beats += 1
        if self._beats >= self.PauseAfterBeats:
            self.requestPause()
        if self._lastSaved is None or time.monotonic() - self._lastSaved >= 5:
            self.save()
        self._refreshPane(False)
        if self.pauseRequested():
            raise _JobPaused(f'Job "{self.title}" was paused.')

    def _refreshPane(self, force: bool) -> None:
        """Keep an open navigator's Jobs pane current (at most every 5 s), and let it redraw.

        MATLAB's refreshPane plus its ``drawnow limitrate``: a job runs in the
        GUI's thread, so this is when Pause and the progress column respond.
        Looks only if the navigator module is already loaded, so a job run
        without the GUI never imports Qt.
        """
        nav_module = sys.modules.get("ndi.gui.navigator")
        if nav_module is None:
            return
        if (
            not force
            and self._lastPaneRefresh is not None
            and time.monotonic() - self._lastPaneRefresh < 5
        ):
            self._processEvents()
            return
        self._lastPaneRefresh = time.monotonic()
        try:
            for nav in nav_module.Navigator.find_open():
                pane = nav.jobs_pane_handle()
                if pane is not None:
                    pane.refresh()
        except Exception:  # noqa: BLE001 -- a GUI hiccup must not stop the work
            pass
        self._processEvents()

    @staticmethod
    def _processEvents() -> None:
        qt = sys.modules.get("PySide6.QtWidgets")
        if qt is None:
            return
        try:
            app = qt.QApplication.instance()
            if app is not None:
                app.processEvents()
        except Exception:  # noqa: BLE001
            pass

    def requestPause(self) -> None:
        """Ask a running job to stop at its next heartbeat (from any process)."""
        self.folder().mkdir(parents=True, exist_ok=True)
        (self.folder() / "pause.request").touch()

    def pauseRequested(self) -> bool:
        return (self.folder() / "pause.request").is_file()

    def restart(self) -> None:
        """Forget the progress, so the next run starts from scratch."""
        if self.effectiveState() == "running":
            raise RuntimeError(f'Pause job "{self.title}" before restarting it.')
        self.onRestart()
        self.checkpoint = {}
        self.progress = 0.0
        self.state = "queued"
        self.message = "Will start over."
        self.lastError = ""
        self._clearPause()
        self.save()

    def remove(self) -> None:
        """Delete the job's record (its folder) from this computer."""
        if self.effectiveState() == "running":
            raise RuntimeError(f'Pause job "{self.title}" before removing it.')
        if self.folder().is_dir():
            shutil.rmtree(self.folder())

    def effectiveState(self) -> str:
        """The state, with a vanished runner on this computer shown as 'interrupted'.

        A job running on another computer is taken at its word.
        """
        s = self.state
        if s != "running":
            return s
        if not ndi_job_Job._sameHost(self.host, ndi_job_Job.hostName()):
            return s
        if self.pid != ndi_job_Job.processId() and not ndi_job_Job.processAlive(self.pid):
            return "interrupted"
        return s

    def remainingSeconds(self) -> float:
        """An estimate of the seconds a running job has left (NaN if none yet).

        From this run's pace: the progress made since it began, over the time
        to its latest heartbeat, carried on to 1, less the time since that
        heartbeat. NaN when not running, or run too briefly (under 30 s), or
        with no progress yet.
        """
        if self.effectiveState() != "running" or not self.runStarted or not self.heartbeat:
            return math.nan
        t0 = ndi_job_Job.fromUtc(self.runStarted)
        t1 = ndi_job_Job.fromUtc(self.heartbeat)
        if t0 is None or t1 is None:
            return math.nan
        elapsed = (t1 - t0).total_seconds()
        done = self.progress - self.runStartProgress
        if elapsed < 30 or done <= 0:
            return math.nan
        since_beat = (_dt.datetime.now(_dt.timezone.utc) - t1).total_seconds()
        return max(0.0, elapsed * (1 - self.progress) / done - max(0.0, since_beat))

    def canResume(self) -> bool:
        return self.effectiveState() in ("queued", "paused", "interrupted", "failed")

    def save(self) -> None:
        """Write job.json (via a temporary file, so a reader never sees half of it)."""
        f = self.folder()
        f.mkdir(parents=True, exist_ok=True)
        self.updated = ndi_job_Job.now()
        self.formatVersion = ndi_job_Job.FormatVersion
        record = {name: getattr(self, name) for name in ndi_job_Job._SAVED_FIELDS}
        record["pid"] = int(record["pid"])
        tmp = f / f"job.json.{ndi_ido.unique_id()}.tmp"
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp, f / "job.json")
        self._lastSaved = time.monotonic()

    # -- for subclasses ----------------------------------------------------

    def initialize(self, title: str, spec: dict[str, Any]) -> None:
        """For a subclass's create: name the job, keep SPEC, write it out."""
        self.id = ndi_ido.unique_id()
        self.kind = type(self).Kind
        self.runtime = "python"
        self.title = str(title)
        self.created = ndi_job_Job.now()
        self.spec = dict(spec)
        self.save()

    def setCheckpoint(self, name: str, value: Any) -> None:
        self.checkpoint[name] = value
        self.save()

    def _clearPause(self) -> None:
        p = self.folder() / "pause.request"
        if p.is_file():
            p.unlink()

    # -- static ------------------------------------------------------------

    @staticmethod
    @validate_call
    def percentText(fraction: float) -> str:
        """FRACTION (0 to 1) as a whole percent, rounded down ('99%' at 0.999)."""
        p = math.floor(100 * max(0.0, min(1.0, float(fraction))) + 1e-9)
        return f"{p}%"

    @staticmethod
    def root() -> Path:
        """The folder jobs are kept in: $NDI_JOBS_DIR, else ~/.ndi/jobs. Created if missing."""
        env = os.environ.get("NDI_JOBS_DIR", "")
        r = Path(env) if env else Path.home() / ".ndi" / "jobs"
        r.mkdir(parents=True, exist_ok=True)
        return r

    @staticmethod
    @validate_call
    def load(idOrFolder: str | os.PathLike) -> Any:
        """The job with this id (or folder), read from its job.json: an ndi_job_Job."""
        f = Path(idOrFolder)
        if not f.is_dir():
            f = ndi_job_Job.root() / str(idOrFolder)
        file = f / "job.json"
        if not file.is_file():
            raise FileNotFoundError(f"There is no job at {f}.")
        s = json.loads(file.read_text(encoding="utf-8"))
        cls = ndi_job_Job.classForKind(str(s.get("kind", "")))
        newer = float(s.get("formatVersion", 0)) > ndi_job_Job.FormatVersion
        if cls is None or newer:
            # Listed, never run here: another language's kind, or a format
            # this Python is too old to read.
            from ndi.job.foreign_job import ndi_job_ForeignJob

            job = ndi_job_ForeignJob()
        else:
            job = cls()
        for name in ndi_job_Job._SAVED_FIELDS:
            if name in s:
                v = s[name]
                if name in ("spec", "checkpoint") and not v:
                    v = {}
                setattr(job, name, v)
        # MATLAB writes whole numbers as JSON numbers that may decode as float.
        job.pid = int(job.pid or 0)
        return job

    @staticmethod
    def list() -> list[ndi_job_Job]:
        """Every job on this computer, oldest first (unreadable ones skipped)."""
        jobs = []
        for d in sorted(ndi_job_Job.root().iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            try:
                jobs.append(ndi_job_Job.load(d))
            except Exception:  # noqa: BLE001 -- an unreadable record is skipped
                continue
        jobs.sort(key=lambda j: j.created)
        return jobs

    @staticmethod
    @validate_call(config={"arbitrary_types_allowed": True})
    def register(kind: str, className: type) -> None:
        """Name the class that runs jobs of KIND in this Python process."""
        ndi_job_Job._registry[str(kind)] = className

    @staticmethod
    def classForKind(kind: str) -> type | None:
        """The class registered for KIND, or None."""
        return ndi_job_Job._registry.get(str(kind))

    @staticmethod
    def processId() -> int:
        return os.getpid()

    @staticmethod
    def processAlive(pid: int | float) -> bool:
        """Is there a process with this id on this computer?"""
        pid = int(pid or 0)
        if pid <= 0:
            return False
        if sys.platform == "win32":
            import ctypes

            # PROCESS_QUERY_LIMITED_INFORMATION; os.kill would TERMINATE it.
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return code.value == 259  # STILL_ACTIVE
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists, owned by someone else
        return True

    @staticmethod
    def now() -> str:
        """The current time as job.json stores it: UTC, ISO 8601, 'Z'."""
        return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def localTime(utc: str) -> str:
        """A stored UTC time for display, in this computer's time zone."""
        if not utc:
            return ""
        d = ndi_job_Job.fromUtc(utc)
        if d is None:
            return str(utc)
        return d.astimezone().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def fromUtc(utc: str) -> _dt.datetime | None:
        """A stored UTC time as an aware datetime (None if unreadable; NaT in MATLAB)."""
        try:
            return _dt.datetime.strptime(str(utc), "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=_dt.timezone.utc
            )
        except ValueError:
            return None

    @staticmethod
    def hostName() -> str:
        return (
            socket.gethostname()
            or os.environ.get("HOSTNAME", "")
            or os.environ.get("COMPUTERNAME", "")
        )

    @staticmethod
    def _sameHost(a: str, b: str) -> bool:
        """Host names compared without case or domain ('kip' == 'Kip.local').

        MATLAB records Java's InetAddress host name and Python the socket
        one, which on the same Mac can differ by a '.local' suffix.
        """

        def short(h: str) -> str:
            return str(h).split(".")[0].lower()

        return short(a) == short(b)
