"""
ndi.session - ndi_session management for NDI.

This module provides session classes for managing NDI experiments:
- ndi_session: Abstract base class for session management
- ndi_session_dir: Directory-based session implementation

MATLAB equivalents:
    ndi.session      -> ndi.session.ndi_session (or ndi.ndi_session)
    ndi.session.dir  -> ndi.session.dir (constructor for directory-based sessions)
"""

from .dir import ndi_session_dir
from .mock import ndi_session_mock
from .session_base import ndi_session, empty_id
from .sessiontable import ndi_session_sessiontable

# MATLAB compatibility: ``ndi.session.dir(path)`` creates a directory-based
# session, mirroring the MATLAB constructor ``ndi.session.dir``.
dir = ndi_session_dir

__all__ = [
    "ndi_session",
    "ndi_session_dir",
    "ndi_session_mock",
    "ndi_session_sessiontable",
    "empty_id",
    "dir",
]
