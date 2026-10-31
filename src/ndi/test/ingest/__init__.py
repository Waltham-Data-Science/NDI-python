"""Check that ingestion stored a session's data faithfully.

MATLAB equivalent: +ndi/+test/+ingest
"""

from .compare import compare
from .mfdaq_compare import mfdaq_compare

__all__ = ["compare", "mfdaq_compare"]
