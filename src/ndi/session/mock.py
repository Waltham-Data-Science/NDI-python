"""
ndi.session.mock - Mock session for testing.

Provides MockSession that creates a temporary directory-based session,
useful for unit tests and interactive experimentation.

MATLAB equivalent: Conceptual (MATLAB tests create sessions manually)
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .dir import DirSession


class MockSession(DirSession):
    """
    Temporary session for testing.

    Creates a DirSession backed by a temporary directory that is
    automatically cleaned up when the session is closed or garbage
    collected.

    Example:
        >>> with MockSession('test') as session:
        ...     doc = Document('base')
        ...     session.database_add(doc)
        ...     results = session.database_search(Query('').isa('base'))
        >>> # temp directory is cleaned up

        >>> # Or without context manager:
        >>> session = MockSession('test')
        >>> # ... use session ...
        >>> session.close()  # cleans up temp directory
    """

    def __init__(
        self,
        reference: str = "mock",
        prefix: str = "ndi_mock_",
        cleanup: bool = True,
    ):
        """
        Create a mock session with a temporary directory.

        Args:
            reference: Session reference string
            prefix: Prefix for temp directory name
            cleanup: If True, remove temp dir on close/del
        """
        self._tmpdir = tempfile.mkdtemp(prefix=prefix)
        self._cleanup = cleanup
        super().__init__(reference, self._tmpdir)

    def close(self) -> None:
        """Close the session and clean up the temporary directory."""
        if self._cleanup and Path(self._tmpdir).exists():
            shutil.rmtree(self._tmpdir, ignore_errors=True)

    def __enter__(self) -> MockSession:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        return f"MockSession(path='{self._tmpdir}')"
