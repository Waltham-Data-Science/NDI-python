"""ndi.job - long pieces of work that can be paused, resumed and restarted.

MATLAB counterpart: ``+ndi/+job/``. The ``job.json`` format is shared with
NDI-matlab (``ndi_common/job_schema/job.schema.json``), so jobs MATLAB runs
can be listed and paused from Python. See ``ndi_matlab_python_bridge.yaml``.
"""

from ndi.job.foreign_job import ndi_job_ForeignJob
from ndi.job.job import ndi_job_Job

__all__ = ["ndi_job_Job", "ndi_job_ForeignJob"]
