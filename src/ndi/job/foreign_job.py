"""ndi.job.foreign_job - a job this Python can list but not run.

MATLAB counterpart: ``+ndi/+job/ForeignJob.m``.

:meth:`ndi.job.job.ndi_job_Job.load` returns one for a job.json whose kind no
class here is registered for (a job made by NDI-matlab, such as a
``lightsheetToCloud`` build), or whose formatVersion is newer than this code
reads. Its state and progress can be listed, and it can be asked to pause
(the runner is another process, which sees the request at its next
heartbeat); run, restart and resume are refused, and remove only deletes the
record.
"""

from __future__ import annotations

from ndi.job.job import ndi_job_Job


class ndi_job_ForeignJob(ndi_job_Job):
    Kind = ""

    def run(self) -> None:
        raise RuntimeError(
            f'Job "{self.title}" is of kind "{self.kind}" (last run by {self.runtime}, '
            f"format {self.formatVersion}), which this Python cannot run."
        )

    def restart(self) -> None:
        self.run()

    def canResume(self) -> bool:
        return False

    def work(self) -> None:
        self.run()
