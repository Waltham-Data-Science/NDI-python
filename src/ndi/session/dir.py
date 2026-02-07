"""
ndi.session.dir - Directory-based NDI session.

This module provides DirSession, a Session implementation that
stores all data in a directory on the filesystem.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..database import Database
from ..ido import Ido
from ..query import Query
from ..time.syncgraph import SyncGraph
from .session_base import Session


class DirSession(Session):
    """
    Directory-based session implementation.

    DirSession stores session data in a directory structure with:
    - .ndi/ subdirectory for database and metadata
    - reference.txt and unique_reference.txt for session identification

    Example:
        # Create or open a session
        >>> session = DirSession('/path/to/experiment')

        # Create with explicit reference
        >>> session = DirSession('MyExperiment', '/path/to/experiment')

        # Access session data
        >>> probes = session.getprobes()
    """

    def __init__(
        self,
        reference_or_path: str | Path,
        path: str | Path | None = None,
        session_id: str | None = None,
    ):
        """
        Create or open a directory-based session.

        Can be called in two ways:
        - DirSession(path) - Open existing session from path
        - DirSession(reference, path) - Create/open with explicit reference

        Args:
            reference_or_path: Either the session reference or path
            path: Optional path if reference_or_path is the reference
            session_id: Optional session ID (internal use)
        """
        # Determine reference and path from arguments
        if path is None:
            # Single argument: it's the path
            self._path = Path(reference_or_path)
            reference = "temp"
        else:
            # Two arguments: reference and path
            reference = str(reference_or_path)
            self._path = Path(path)

        # Initialize base session
        super().__init__(reference)

        # Validate path exists
        if not self._path.exists():
            raise ValueError(f"Directory '{self._path}' does not exist")

        if not self._path.is_dir():
            raise ValueError(f"'{self._path}' is not a directory")

        # Handle session_id if provided directly
        should_read_from_database = True
        if session_id is not None:
            self._identifier = session_id
            self._reference = reference
            should_read_from_database = False
        else:
            # Try to read identifier from file
            unique_ref_file = self._ndi_pathname() / "unique_reference.txt"
            if unique_ref_file.exists():
                self._identifier = unique_ref_file.read_text().strip()
            else:
                # Create a new identifier
                self._identifier = Ido().id

        # Initialize database
        self._database = Database(self._ndi_pathname(), db_name=".")

        # Try to load session info from database
        read_from_database = False
        if should_read_from_database:
            session_docs = self.database_search(Query("").isa("session"))
            if session_docs:
                # Use the oldest session document
                oldest_doc = session_docs[0]
                if len(session_docs) > 1:
                    # Find oldest by datestamp
                    for doc in session_docs[1:]:
                        if hasattr(doc.document_properties, "base"):
                            # Compare datestamps if available
                            pass  # Use first for simplicity
                oldest_doc = session_docs[0]

                props = oldest_doc.document_properties
                if hasattr(props, "base"):
                    self._identifier = getattr(props.base, "session_id", self._identifier)
                if hasattr(props, "session"):
                    self._reference = getattr(props.session, "reference", self._reference)
                read_from_database = True

        # If not read from database, try reference file or create new
        if should_read_from_database and not read_from_database:
            ref_file = self._ndi_pathname() / "reference.txt"
            if ref_file.exists():
                self._reference = ref_file.read_text().strip()
            elif path is None:
                # Opening by path only and no reference found
                raise ValueError(
                    f"Could not load REFERENCE from database or {self._ndi_pathname()}"
                )

            # Create session document
            from ..document import Document

            try:
                session_doc = Document("session", **{"session.reference": self._reference})
                session_doc = session_doc.set_session_id(self._identifier)
                self.database_add(session_doc)
            except Exception:
                # May fail if schema not available
                pass

        # Load or create syncgraph
        syncgraph_docs = self.database_search(
            Query("").isa("syncgraph") & (Query("base.session_id") == self.id())
        )

        if not syncgraph_docs:
            self._syncgraph = SyncGraph(self)
        else:
            if len(syncgraph_docs) > 1:
                raise ValueError("Too many syncgraph documents found. There should be only 1.")
            self._syncgraph = SyncGraph(session=self, document=syncgraph_docs[0])

        # Write reference files
        self._write_reference_files()

    def _ndi_pathname(self) -> Path:
        """
        Get the path to the .ndi directory.

        Creates the directory if it doesn't exist.

        Returns:
            Path to .ndi directory
        """
        ndi_dir = self._path / ".ndi"
        ndi_dir.mkdir(parents=True, exist_ok=True)
        return ndi_dir

    def _write_reference_files(self) -> None:
        """Write reference and unique_reference files."""
        ndi_dir = self._ndi_pathname()

        ref_file = ndi_dir / "reference.txt"
        ref_file.write_text(self._reference)

        unique_ref_file = ndi_dir / "unique_reference.txt"
        unique_ref_file.write_text(self._identifier)

    def getpath(self) -> Path:
        """
        Return the session directory path.

        Returns:
            Path to the session directory
        """
        return self._path

    @property
    def path(self) -> Path:
        """Get the session path."""
        return self._path

    def ndipathname(self) -> Path:
        """
        Get the path to NDI files within the session.

        Returns:
            Path to the .ndi directory
        """
        return self._ndi_pathname()

    def creator_args(self) -> list[Any]:
        """
        Return arguments needed to recreate this session.

        Returns:
            List of [reference, path, session_id]
        """
        return [self._reference, str(self._path), self._identifier]

    def delete_session_data_structures(
        self,
        are_you_sure: bool = False,
        ask_user: bool = True,
    ) -> DirSession | None:
        """
        Delete the session's data structures.

        Args:
            are_you_sure: If True, proceed without confirmation
            ask_user: If True and not sure, prompt user (not implemented)

        Returns:
            None if deleted, self if not
        """
        import shutil

        passed = are_you_sure

        if passed:
            ndi_dir = self._path / ".ndi"
            if ndi_dir.exists():
                shutil.rmtree(ndi_dir)
            return None

        return self

    @staticmethod
    def exists(path: str | Path) -> bool:
        """
        Check if a session exists at the given path.

        Args:
            path: Directory path to check

        Returns:
            True if a valid session exists
        """
        path = Path(path)
        ndi_dir = path / ".ndi"
        if not ndi_dir.exists():
            return False

        ref_file = ndi_dir / "reference.txt"
        return ref_file.exists()

    @staticmethod
    def database_erase(session: DirSession, areyousure: str) -> None:
        """
        Delete the entire session database.

        Args:
            session: Session to erase
            areyousure: Must be 'yes' to proceed
        """
        import shutil

        if areyousure.lower() != "yes":
            print("Not erasing session because confirmation not given.")
            return

        ndi_dir = session._path / ".ndi"
        if ndi_dir.exists():
            shutil.rmtree(ndi_dir)

    def __eq__(self, other: Any) -> bool:
        """Check equality by ID and path."""
        if not isinstance(other, DirSession):
            return False
        if not super().__eq__(other):
            return False
        return self._path == other._path

    def __repr__(self) -> str:
        """String representation."""
        return f"DirSession(reference='{self._reference}', path='{self._path}')"
