"""
ndi.session.mock - Mock session for testing.

Provides ndi_session_mock that creates a temporary directory-based session,
useful for unit tests and interactive experimentation.

MATLAB equivalent: Conceptual (MATLAB tests create sessions manually)
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .dir import ndi_session_dir


class ndi_session_mock(ndi_session_dir):
    """
    Temporary session for testing.

    Creates a ndi_session_dir backed by a temporary directory that is
    automatically cleaned up when the session is closed or garbage
    collected.

    Example:
        >>> with ndi_session_mock('test') as session:
        ...     doc = ndi_document('base')
        ...     session.database_add(doc)
        ...     results = session.database_search(ndi_query('').isa('base'))
        >>> # temp directory is cleaned up

        >>> # Or without context manager:
        >>> session = ndi_session_mock('test')
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
        """Close the session and clean up the temporary directory.

        Releases the SQLite handle before removing the tree: the temp
        directory holds ``.ndi/did-sqlite.sqlite``, and on Windows an open
        file cannot be deleted — with ``ignore_errors=True`` that failure is
        silent and leaks the whole directory. MATLAB fixed the same exposure
        in its ``closeAndRemoveDir`` test helper (NDI-matlab ``26d0638bf``,
        issue #870).
        """
        if self._cleanup and Path(self._tmpdir).exists():
            self._close_database()
            shutil.rmtree(self._tmpdir, ignore_errors=True)

    def __enter__(self) -> ndi_session_mock:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        return f"ndi_session_mock(path='{self._tmpdir}')"
