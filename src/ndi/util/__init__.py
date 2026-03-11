"""
ndi.util - General utility functions for NDI.

MATLAB equivalent: +ndi/+util/

Provides utility functions for datestamp conversion, timeseries
downsampling, hex diffing/dumping, JSON rehydration, and table
cell unwrapping.

MATLAB GUI utilities (``choosefile``, ``choosefileordir``) and
MATLAB-specific helpers (``toolboxdir``) are intentionally not ported.
The ``+openminds`` sub-package is ported separately in
``ndi.openminds_convert``.
"""

from .datestamp2datetime import datestamp2datetime
from .downsampleTimeseries import downsampleTimeseries
from .getHexDiffFromFileObj import getHexDiffFromFileObj
from .hexDiff import hexDiff
from .hexDiffBytes import hexDiffBytes
from .hexDump import hexDump
from .rehydrateJSONNanNull import rehydrateJSONNanNull
from .unwrapTableCellContent import unwrapTableCellContent

__all__ = [
    "datestamp2datetime",
    "downsampleTimeseries",
    "getHexDiffFromFileObj",
    "hexDiff",
    "hexDiffBytes",
    "hexDump",
    "rehydrateJSONNanNull",
    "unwrapTableCellContent",
]
