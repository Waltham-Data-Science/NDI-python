"""
ndi.dataset - Multi-session dataset container.

A Dataset manages multiple sessions, either linked (by reference) or
ingested (copied into the dataset's own database). Datasets have their
own session for storing dataset-level documents and metadata.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .ido import Ido
from .document import Document
from .query import Query


class Dataset:
    """
    Multi-session dataset container.

    A Dataset aggregates multiple sessions for cross-session analysis.
    Sessions can be:
    - **Linked**: Referenced by path/id, data stays in original location
    - **Ingested**: Documents copied into the dataset's own database

    Each dataset has its own internal session for dataset-level documents
    (e.g., session_in_a_dataset records).

    Attributes:
        reference: Human-readable dataset reference name

    Example:
        >>> dataset = Dataset('/path/to/dataset', 'my_experiment')
        >>> dataset.add_linked_session(session1)
        >>> dataset.add_ingested_session(session2)
        >>> sessions = dataset.session_list()
    """

    def __init__(
        self,
        path: Union[str, Path],
        reference: str = '',
    ):
        """
        Create or open a Dataset.

        Args:
            path: Directory path for the dataset
            reference: Human-readable reference name
        """
        from .session.dir import DirSession

        self._path = Path(path)
        self._reference = reference or self._path.name
        self._ido = Ido()

        # Create internal session for dataset-level documents
        dataset_session_path = self._path / '.ndi_dataset'
        dataset_session_path.mkdir(parents=True, exist_ok=True)
        self._session = DirSession(
            f"dataset:{self._reference}",
            dataset_session_path,
        )

        # Cache of open sessions
        self._session_cache: Dict[str, Any] = {}

    @property
    def reference(self) -> str:
        """Get the dataset reference name."""
        return self._reference

    def id(self) -> str:
        """Get the unique dataset identifier."""
        return self._session.id()

    def getpath(self) -> Path:
        """Get the dataset directory path."""
        return self._path

    # =========================================================================
    # Session Management
    # =========================================================================

    def add_linked_session(self, session: Any) -> 'Dataset':
        """
        Add a linked session to this dataset.

        The session data stays in its original location. The dataset
        stores a reference to the session.

        Args:
            session: Session object to link

        Returns:
            self for chaining
        """
        # Check if already linked
        existing = self._find_session_doc(session.id())
        if existing is not None:
            return self

        # Create session_in_a_dataset document
        doc = self._create_session_doc(session, is_linked=True)
        self._session.database_add(doc)

        return self

    def add_ingested_session(self, session: Any) -> 'Dataset':
        """
        Ingest a session into this dataset.

        Copies all documents from the source session into the
        dataset's internal database.

        Args:
            session: Session object to ingest

        Returns:
            self for chaining
        """
        # Check if already present
        existing = self._find_session_doc(session.id())
        if existing is not None:
            return self

        # Copy all documents from source session into the dataset's database.
        # We bypass session.database_add() because it enforces session_id ==
        # self._session.id(), but ingested docs retain their *original*
        # session_id so we can tell which session they came from.
        all_docs = session.database_search(Query('').isa('base'))
        for doc in all_docs:
            try:
                self._session._database.add(doc)
                # Copy binary files from source session to dataset
                self._copy_binary_files(session, doc)
            except Exception:
                pass  # Skip documents that fail (e.g., duplicates)

        # Create session_in_a_dataset document
        doc = self._create_session_doc(session, is_linked=False)
        self._session.database_add(doc)

        return self

    def unlink_session(
        self,
        session_id: str,
        remove_documents: bool = False,
    ) -> 'Dataset':
        """
        Remove a session from this dataset.

        Args:
            session_id: ID of the session to unlink
            remove_documents: If True, also remove ingested documents

        Returns:
            self for chaining
        """
        doc = self._find_session_doc(session_id)
        if doc is None:
            return self

        # Optionally remove ingested documents
        if remove_documents:
            self._remove_session_documents(session_id)

        # Remove the session_in_a_dataset document
        self._session.database_rm(doc)

        # Remove from cache
        self._session_cache.pop(session_id, None)

        return self

    def open_session(self, session_id: str) -> Optional[Any]:
        """
        Open a session by its ID.

        For linked sessions, recreates the session from stored creator args.
        For ingested sessions, returns the dataset's internal session.

        Args:
            session_id: Session identifier

        Returns:
            Session object, or None if not found
        """
        # Check cache
        if session_id in self._session_cache:
            return self._session_cache[session_id]

        doc = self._find_session_doc(session_id)
        if doc is None:
            return None

        props = doc.document_properties.get('session_in_a_dataset', {})
        is_linked = props.get('is_linked', False)

        if is_linked:
            # Recreate from creator args
            session = self._recreate_linked_session(props)
        else:
            # For ingested sessions, use internal session
            session = self._session

        if session is not None:
            self._session_cache[session_id] = session

        return session

    def session_list(self) -> List[Dict[str, Any]]:
        """
        List all sessions in this dataset.

        Returns:
            List of dicts with keys:
                - session_id: Session identifier
                - session_reference: Session reference name
                - is_linked: True if linked, False if ingested
                - document_id: ID of the session_in_a_dataset document
        """
        q = Query('').isa('session_in_a_dataset')
        docs = self._session.database_search(q)

        result = []
        for doc in docs:
            props = doc.document_properties.get('session_in_a_dataset', {})
            result.append({
                'session_id': props.get('session_id', ''),
                'session_reference': props.get('session_reference', ''),
                'is_linked': bool(props.get('is_linked', False)),
                'document_id': doc.id,
            })

        return result

    # =========================================================================
    # Database Operations (delegated to internal session)
    # =========================================================================

    def database_add(self, document: Document) -> 'Dataset':
        """Add a document to the dataset database."""
        self._session.database_add(document)
        return self

    def database_rm(
        self,
        doc_or_id: Union[Document, str],
        error_if_not_found: bool = False,
    ) -> 'Dataset':
        """Remove a document from the dataset database."""
        self._session.database_rm(doc_or_id, error_if_not_found)
        return self

    def database_search(self, query: Query) -> List[Document]:
        """Search the dataset database.

        Unlike Session.database_search(), this does NOT filter by session_id
        because a dataset stores documents from multiple ingested sessions.
        """
        if self._session._database is None:
            return []
        return self._session._database.search(query)

    def database_openbinarydoc(
        self,
        doc_or_id: Any,
        filename: str,
    ) -> Any:
        """Open a binary document file."""
        return self._session.database_openbinarydoc(doc_or_id, filename)

    def database_closebinarydoc(self, fid: Any) -> None:
        """Close a binary document file."""
        self._session.database_closebinarydoc(fid)

    # =========================================================================
    # Ingested Session Management
    # =========================================================================

    def delete_ingested_session(
        self,
        session_id: str,
        are_you_sure: bool = False,
    ) -> 'Dataset':
        """
        Delete an ingested session and all its documents.

        Args:
            session_id: ID of session to delete
            are_you_sure: Must be True to proceed

        Returns:
            self for chaining

        Raises:
            ValueError: If are_you_sure is not True
        """
        if not are_you_sure:
            raise ValueError("Must set are_you_sure=True to delete session data")

        doc = self._find_session_doc(session_id)
        if doc is None:
            return self

        props = doc.document_properties.get('session_in_a_dataset', {})
        if props.get('is_linked', False):
            raise ValueError(
                "Cannot delete a linked session. Use unlink_session() instead."
            )

        # Remove all documents from this session
        self._remove_session_documents(session_id)

        # Remove the session_in_a_dataset document
        self._session.database_rm(doc)

        # Remove from cache
        self._session_cache.pop(session_id, None)

        return self

    def document_session(self, document: Document) -> Optional[Any]:
        """
        Find which session a document belongs to.

        Args:
            document: Document to look up

        Returns:
            Session object, or None if not found
        """
        session_id = document.session_id
        if session_id:
            return self.open_session(session_id)
        return None

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _copy_binary_files(self, source_session: Any, doc: Document) -> None:
        """Copy binary file attachments from a source session to this dataset."""
        import shutil
        if self._session._database is None:
            return
        props = doc.document_properties
        files = props.get('files', {})
        if not isinstance(files, dict):
            return
        for fi in files.get('file_info', []):
            name = fi.get('name', '')
            if not name:
                continue
            # Try the source session's binary dir first
            if hasattr(source_session, '_database') and source_session._database is not None:
                src_path = source_session._database.get_binary_path(doc, name)
                if src_path.exists():
                    dest_path = self._session._database.get_binary_path(doc, name)
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src_path), str(dest_path))
                    continue
            # Fallback: try the original file location from file_info
            for loc in fi.get('locations', []):
                source = loc.get('location', '')
                if source:
                    src_path = Path(source)
                    if src_path.exists():
                        dest_path = self._session._database.get_binary_path(doc, name)
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(src_path), str(dest_path))
                        break

    def _create_session_doc(self, session: Any, is_linked: bool) -> Document:
        """Create a session_in_a_dataset document."""
        # Get creator args for recreating the session
        creator_args = session.creator_args() if hasattr(session, 'creator_args') else []

        props = {
            'session_in_a_dataset.session_id': session.id(),
            'session_in_a_dataset.session_reference': session.reference,
            'session_in_a_dataset.is_linked': is_linked,
            'session_in_a_dataset.session_creator': type(session).__name__,
        }

        # Store up to 6 creator args
        for i, arg in enumerate(creator_args[:6], 1):
            props[f'session_in_a_dataset.session_creator_input{i}'] = str(arg)

        doc = Document('session_in_a_dataset', **props)
        return doc

    def _find_session_doc(self, session_id: str) -> Optional[Document]:
        """Find the session_in_a_dataset document for a given session ID."""
        q = (
            Query('').isa('session_in_a_dataset') &
            (Query('session_in_a_dataset.session_id') == session_id)
        )
        docs = self._session.database_search(q)
        return docs[0] if docs else None

    def _remove_session_documents(self, session_id: str) -> None:
        """Remove all documents belonging to a session."""
        q = Query('base.session_id') == session_id
        # Search directly on the database, not through Session which
        # filters to its own session_id.
        docs = self._session._database.search(q) if self._session._database else []
        for doc in docs:
            try:
                self._session.database_rm(doc)
            except Exception:
                pass

    def _recreate_linked_session(self, props: Dict[str, Any]) -> Optional[Any]:
        """Recreate a linked session from stored creator args."""
        creator = props.get('session_creator', '')

        if creator == 'DirSession':
            from .session.dir import DirSession

            # Get creator args
            args = []
            for i in range(1, 7):
                arg = props.get(f'session_creator_input{i}', '')
                if arg:
                    args.append(arg)

            if len(args) >= 2:
                try:
                    return DirSession(args[0], args[1])
                except Exception:
                    pass
            elif len(args) >= 1:
                try:
                    return DirSession(args[0])
                except Exception:
                    pass

        return None

    # =========================================================================
    # Representation
    # =========================================================================

    def __repr__(self) -> str:
        """String representation."""
        sessions = self.session_list()
        return f"Dataset('{self._reference}', sessions={len(sessions)})"
