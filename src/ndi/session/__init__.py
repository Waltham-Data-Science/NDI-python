"""
ndi.session - Session management for NDI.

This module provides session classes for managing NDI experiments:
- Session: Abstract base class for session management
- DirSession: Directory-based session implementation
"""

from .dir import DirSession
from .mock import MockSession
from .session_base import Session, empty_id
from .sessiontable import SessionTable

__all__ = [
    "Session",
    "DirSession",
    "MockSession",
    "SessionTable",
    "empty_id",
]
