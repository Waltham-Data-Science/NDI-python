"""
ndi.session.dir - Directory-based NDI session.

This module provides ndi_session_dir, a ndi_session implementation that
stores all data in a directory on the filesystem.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..database import ndi_database
from ..ido import ndi_ido
from ..query import ndi_query
from ..time.syncgraph import ndi_time_syncgraph
from .session_base import ndi_session


class ndi_session_dir(ndi_session):
    """
    Directory-based session implementation.

    ndi_session_dir stores session data in a directory structure with:
    - .ndi/ subdirectory for database and metadata
    - reference.txt and unique_reference.txt for session identification

    Example:
        # Create or open a session
        >>> session = ndi_session_dir('/path/to/experiment')

        # Create with explicit reference
        >>> session = ndi_session_dir('MyExperiment', '/path/to/experiment')

        # Access session data
        >>> probes = session.getprobes()

    CROSS-LANGUAGE NAMING
    Methods that mirror MATLAB keep MATLAB's exact name, and each also has a
    snake_case alias bound to the same function -- ``isIngestedInDataset`` and
    ``is_ingested_in_dataset`` are one method under two names. Neither
    audience should have to remember which spelling a given method happens to
    carry: a script ported from MATLAB keeps working, and Python code can read
    idiomatically.

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
        - ndi_session_dir(path) - Open existing session from path
        - ndi_session_dir(reference, path) - Create/open with explicit reference

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
                self._identifier = ndi_ido().id

        # Initialize database
        self._database = ndi_database(self._ndi_pathname(), db_name=".")

        # Try to load session info from database
        read_from_database = False
        if should_read_from_database:
            # Search without the session_id filter so we can discover the
            # existing session_id from documents already in the database
            # (e.g. artifacts produced by MATLAB).
            session_docs = self._database.search(ndi_query("").isa("session"))
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
                if "base" in props and isinstance(props["base"], dict):
                    self._identifier = props["base"].get("session_id", self._identifier)
                if "session" in props and isinstance(props["session"], dict):
                    self._reference = props["session"].get("reference", self._reference)
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
            from ..document import ndi_document

            session_doc = ndi_document("session", **{"session.reference": self._reference})
            session_doc = session_doc.set_session_id(self._identifier)
            self.database_add(session_doc)

        # Load or create syncgraph
        syncgraph_docs = self.database_search(
            ndi_query("").isa("syncgraph") & (ndi_query("base.session_id") == self.id())
        )

        if not syncgraph_docs:
            self._syncgraph = ndi_time_syncgraph(self)
        else:
            if len(syncgraph_docs) > 1:
                raise ValueError("Too many syncgraph documents found. There should be only 1.")
            self._syncgraph = ndi_time_syncgraph(session=self, document=syncgraph_docs[0])

        # Write reference files
        self._write_reference_files()

        # Record what this directory holds, so MATLAB (and a file-open dialog)
        # can tell a session from a dataset without opening it. See #73.
        self.updateObjectTypeMarker()

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

    # =========================================================================
    # Object-type marker
    #
    # MATLAB records what a directory holds in a small file inside .ndi so the
    # type can be told cheaply -- by a file-open dialog, say -- without fully
    # instantiating the object. NDI-python never wrote it, so MATLAB reading a
    # Python-generated directory got 'unknown' where it expected 'dataset'
    # (issue #73).
    # =========================================================================

    @staticmethod
    def objecttypemarkerfilename() -> str:
        """Filename of the .ndi object-type marker.

        MATLAB equivalent: ``ndi.session.dir.objecttypemarkerfilename()``.
        """
        return "ndi_object_type.txt"

    def setObjectTypeMarker(self, typestr: str) -> None:  # noqa: N802 (MATLAB mirror)
        """Write the .ndi object-type marker directly, unconditionally.

        Use this to force a directory's recorded type; ``ndi_dataset_dir``
        uses it to mark its directory as a dataset. Most callers should use
        :meth:`updateObjectTypeMarker`, which chooses the type safely.

        MATLAB equivalent: ``ndi.session.dir/setObjectTypeMarker``.
        """
        if typestr not in ("session", "dataset"):
            raise ValueError(f"typestr must be 'session' or 'dataset'; got {typestr!r}.")
        markerfile = self._ndi_pathname() / self.objecttypemarkerfilename()
        markerfile.write_text(typestr)

    #: Snake-case alias; same method, see the class note on naming.
    set_object_type_marker = setObjectTypeMarker

    def updateObjectTypeMarker(self) -> None:  # noqa: N802 (MATLAB mirror)
        """Write or refresh the .ndi object-type marker.

        A directory already marked as a dataset is never downgraded, and one
        that holds dataset bookkeeping documents is marked as a dataset. That
        matters because ``ndi_dataset_dir`` keeps an underlying session at the
        same path, and ingesting a session into a dataset builds a temporary
        session there -- without the guard, either would relabel a dataset
        directory as a plain session.

        An empty dataset has no bookkeeping documents yet, so it is marked
        'session' here and corrected by the ``ndi_dataset_dir`` constructor.

        MATLAB equivalent: ``ndi.session.dir/updateObjectTypeMarker``.
        """
        markerfile = self._ndi_pathname() / self.objecttypemarkerfilename()
        if markerfile.is_file():
            existing = markerfile.read_text().strip().lower()
            if existing == "dataset":
                return  # never downgrade a directory already known to be a dataset

        # Datasets store 'session_in_a_dataset' (current) or
        # 'dataset_session_info' (legacy) bookkeeping; standalone sessions
        # never do.
        is_dataset = False
        try:
            from ..query import ndi_query

            docs = self.database_search(ndi_query("").isa("session_in_a_dataset"))
            if not docs:
                docs = self.database_search(ndi_query("").isa("dataset_session_info"))
            is_dataset = bool(docs)
        except Exception:
            # A directory whose database cannot be searched yet is not a
            # reason to fail construction; it is simply not known to be a
            # dataset, which is what 'session' records.
            is_dataset = False

        self.setObjectTypeMarker("dataset" if is_dataset else "session")

    #: Snake-case alias; same method, see the class note on naming.
    update_object_type_marker = updateObjectTypeMarker

    @staticmethod
    def directorytype(path: str | Path) -> str:
        """Determine the NDI object type in a directory without opening it.

        Returns one of:

        ``'session'``
            The directory holds a standalone session.
        ``'dataset'``
            The directory holds a dataset.
        ``'unknown'``
            An NDI directory created before object-type markers existed, or
            whose marker is unreadable. Open it once to record its type.
        ``'none'``
            Not an NDI session or dataset directory.

        MATLAB equivalent: ``ndi.session.dir.directorytype``.
        """
        path = Path(path)
        if not ndi_session_dir.exists(path):
            return "none"
        markerfile = path / ".ndi" / ndi_session_dir.objecttypemarkerfilename()
        if markerfile.is_file():
            t = markerfile.read_text().strip().lower()
            return t if t in ("session", "dataset") else "unknown"
        return "unknown"

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

    def deleteSessionDataStructures(
        self,
        are_you_sure: bool = False,
        ask_user: bool = True,
    ) -> ndi_session_dir | None:
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

    #: Snake-case alias; same method, see the class note on naming.
    delete_session_data_structures = deleteSessionDataStructures

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
    def database_erase(session: ndi_session_dir, areyousure: str) -> None:
        """
        Delete the entire session database.

        Args:
            session: ndi_session to erase
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
        if not isinstance(other, ndi_session_dir):
            return False
        if not super().__eq__(other):
            return False
        return self._path == other._path

    def __repr__(self) -> str:
        """String representation."""
        return f"ndi_session_dir(reference='{self._reference}', path='{self._path}')"


# Pythonic alias
DirSession = ndi_session_dir
