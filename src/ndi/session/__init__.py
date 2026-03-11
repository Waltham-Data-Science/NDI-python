"""
ndi.session - Session management for NDI.

This module provides session classes for managing NDI experiments:
- Session: Abstract base class for session management
- DirSession: Directory-based session implementation

MATLAB equivalents:
    ndi.session      -> ndi.session.Session (or ndi.Session)
    ndi.session.dir  -> ndi.session.dir (constructor for directory-based sessions)
"""

from .dir import DirSession
from .mock import MockSession
from .session_base import Session, empty_id
from .sessiontable import SessionTable

# MATLAB compatibility: ``ndi.session.dir(path)`` creates a directory-based
# session, mirroring the MATLAB constructor ``ndi.session.dir``.
dir = DirSession

__all__ = [
    "Session",
    "DirSession",
    "MockSession",
    "SessionTable",
    "empty_id",
    "dir",
]
