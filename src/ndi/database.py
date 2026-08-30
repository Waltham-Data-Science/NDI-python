"""
ndi.database - NDI database interface

Provides database functionality for storing and querying NDI documents.
Uses DID-python's SQLiteDB for storage, ensuring compatibility with
existing DID-python and NDI-Matlab databases.

Example:
    # Create a database for a session
    db = ndi_database('/path/to/session')

    # Add documents
    db.add(doc)

    # ndi_query documents
    results = db.search(ndi_query('element.name') == 'electrode1')

    # Find by ID
    doc = db.read(doc_id)
"""

from pathlib import Path

from .document import ndi_document
from .query import ndi_query


def _cloud_file_handler(dest_path, source_path):
    """DID's ``custom_file_handler``, wired to NDI's cloud retrieval.

    DID downloads nothing itself; a downstream package supplies retrieval.
    NDI-matlab passes ``@download_file_from_cloud`` to both ``add_docs`` and
    ``open_doc`` in didsqlite.m, and this is the same handler.

    Imported lazily and tolerant of failure: the cloud extra may be absent,
    and a session that never touches a remote location must not require it.
    DID reports a handler that produced no file as a retrieval failure naming
    the location, which is a better error than an ImportError from here.
    """
    try:
        from .cloud.filehandler import download_file_from_cloud
    except ImportError:
        return
    download_file_from_cloud(dest_path, source_path)


class SQLiteDriver:
    """SQLite database driver using DID-python's SQLiteDB.

    This driver wraps DID-python's SQLiteDB implementation to provide
    a consistent interface for the NDI ndi_database class. DID-python handles
    doc_data population and SQL-based search natively.
    """

    def __init__(self, db_path: Path, branch_id: str = "a"):
        """Initialize the SQLite driver.

        Args:
            db_path: Path to the SQLite database file.
            branch_id: Default branch ID to use.  DID-matlab and
                NDI-matlab have always used ``"a"`` as the default
                branch, so we match that for cross-language compatibility.
        """
        from did.document import Document as DIDDocument
        from did.implementations.sqlitedb import SQLiteDB

        self._db_path = db_path
        self._branch_id = branch_id
        self._DIDDocument = DIDDocument

        # Initialize SQLiteDB
        self._db = SQLiteDB(str(db_path))

        # Create the branch, but only where it can be created as a root.
        #
        # DID's add_branch reads an empty or omitted parent as "the current
        # branch", not "no parent" (DID-python#51, matching MATLAB's isempty,
        # which covers both [] and ''). A root is made only when there is no
        # current branch. With no branches at all there cannot be one, so
        # omitting the parent here is structurally a root -- as NDI-matlab's
        # didsqlite.m gets it from the same isempty(bid) guard.
        #
        # The previous "" argument happened to work only because did.database
        # initialises current_branch_id to empty and never restores it from
        # the file; that is DID's implementation detail, not a guarantee this
        # constructor can make.
        existing_branches = self._db.all_branch_ids()
        if not existing_branches:
            self._db.add_branch(branch_id)
        elif branch_id not in existing_branches:
            # Creating it now would attach it to whatever the current branch
            # happens to be, so name the problem instead. get_doc_ids on a
            # branch that does not exist raises in current DID, so leaving it
            # missing only defers the failure to a less informative place.
            raise ValueError(
                f"The DID database at {db_path} has branches "
                f"{sorted(existing_branches)} but not {branch_id!r}."
            )

    def add(self, document: dict) -> None:
        """Add a document to the database."""
        doc_id = document.get("base", {}).get("id", "")
        if not doc_id:
            raise ValueError("ndi_document must have a base.id")

        # Check if document already exists
        existing_ids = self._db.get_doc_ids(self._branch_id)
        if doc_id in existing_ids:
            raise FileExistsError(f"ndi_document {doc_id} already exists")

        # Create DID ndi_document and add (DID-python now populates doc_data)
        did_doc = self._DIDDocument(document)
        self._db.add_docs([did_doc], self._branch_id, custom_file_handler=_cloud_file_handler)

    def bulk_add(self, documents: list[dict]) -> tuple[int, int]:
        """Add many documents at once, bypassing per-doc duplicate checks.

        Duplicates (by ``base.id``) are silently skipped.

        Returns:
            ``(added, skipped)`` counts.
        """
        existing_ids = set(self._db.get_doc_ids(self._branch_id))

        added = 0
        skipped = 0
        for doc in documents:
            doc_id = doc.get("base", {}).get("id", "")
            if not doc_id or doc_id in existing_ids:
                skipped += 1
                continue

            did_doc = self._DIDDocument(doc)
            self._db.add_docs([did_doc], self._branch_id, custom_file_handler=_cloud_file_handler)
            existing_ids.add(doc_id)
            added += 1

        return added, skipped

    def open_binary(self, doc_id: str, filename: str) -> str:
        """Resolve a document's file to a local path, retrieving it if needed.

        Delegates to DID's ``open_doc``, which serves a local location
        directly and hands a remote one to ``custom_file_handler``. Mirrors
        NDI-matlab's ``didsqlite/do_openbinarydoc``.

        Returns the path rather than DID's file object: NDI's public
        ``database_openbinarydoc`` contract is an ordinary Python file object
        carrying ``fullpathfilename``, and DID's ``Fileobj`` is neither. The
        path is what both need.
        """
        handle = self._db.open_doc(doc_id, filename, custom_file_handler=_cloud_file_handler)
        return handle.fullpathfilename

    def exist_binary(self, doc_id: str, filename: str) -> tuple[bool, str | None]:
        """Is this document's file on disk, and where?

        Delegates to DID's ``exist_doc``, the port of MATLAB's
        ``check_exist_doc``. True exactly when ``open_binary`` would succeed
        without needing to retrieve anything.
        """
        return self._db.exist_doc(doc_id, filename)

    def delete_by_id(self, doc_id: str) -> bool:
        """Delete a document by ID."""
        existing_ids = self._db.get_doc_ids(self._branch_id)
        if doc_id not in existing_ids:
            return False

        self._db.remove_docs([doc_id], self._branch_id)
        return True

    def find_by_id(self, doc_id: str) -> dict | None:
        """Find a document by ID."""
        try:
            doc = self._db.get_docs(doc_id, self._branch_id, OnMissing="ignore")
            if doc is None:
                return None
            return doc.document_properties
        except Exception:
            return None

    def find(self, query=None) -> list[dict]:
        """Find all documents matching query.

        Uses DID-python's SQL-based search against the doc_data table
        for query evaluation, falling back to brute-force for unsupported
        operations.  Retrieval and MATLAB normalization are handled by
        DID-python's :meth:`get_docs` / :meth:`get_docs_by_branch`.
        """
        if query is not None:
            doc_ids = self._db.search(query, self._branch_id)
            if not doc_ids:
                return []
            docs = self._db.get_docs(doc_ids, self._branch_id, OnMissing="ignore")
        else:
            docs = self._db.get_docs_by_branch(self._branch_id)

        return [d.document_properties for d in docs if d is not None]


class ndi_database:
    """NDI database interface.

    Provides document storage and querying using DID-python's SQLiteDB.
    This ensures compatibility with existing DID-python and NDI-Matlab databases.

    Attributes:
        session_path: Path to the session directory.

    Example:
        db = ndi_database('/path/to/session')
        db.add(doc)
        docs = db.search(ndi_query('element.type') == 'probe')
    """

    def __init__(self, session_path: str | Path, db_name: str = ".ndi", **backend_kwargs):
        """Initialize NDI database.

        Args:
            session_path: Path to the session directory.
            db_name: Name of the database directory within session.
                     Default is '.ndi'.
            **backend_kwargs: Additional arguments passed to SQLiteDriver
                             (e.g., branch_id='a').
        """
        self.session_path = Path(session_path)
        self._db_name = db_name

        # Create session directory if it doesn't exist
        self.session_path.mkdir(parents=True, exist_ok=True)

        # Create db directory
        db_dir = self.session_path / db_name
        db_dir.mkdir(parents=True, exist_ok=True)

        # Initialize SQLite driver (wraps DID-python's SQLiteDB)
        db_path = db_dir / "did-sqlite.sqlite"
        self._driver = SQLiteDriver(db_path, **backend_kwargs)

    @property
    def database_path(self) -> Path:
        """Path to the SQLite database file."""
        return self.session_path / self._db_name / "did-sqlite.sqlite"

    @property
    def binary_path(self) -> Path:
        """Directory DID keeps ingested files in.

        NDI used to keep its own directory beside the database and name files
        ``{doc_id}_{filename}``. Files are DID's now, as they already were in
        NDI-matlab, so this reports DID's location rather than a second one.
        """
        # Reaching into DID for a private name, deliberately and with a
        # caveat: DID-matlab exposes this as a public FileDir property on
        # sqlitedb, and DID-python has only _file_dir(). Duplicating the rule
        # here ("files/ beside the database file") would put DID's storage
        # layout in two places, which is the mistake this whole change
        # removes. The asymmetry belongs in DID-python's bridge; until it is
        # closed, this is the single point that breaks if DID renames it.
        return Path(self._driver._db._file_dir())

    # === CRUD Operations ===

    def add(self, document: ndi_document) -> ndi_document:
        """Add a document to the database.

        Args:
            document: The ndi_document to add.

        Returns:
            The added document.

        Raises:
            ValueError: If document already exists in database.

        Example:
            doc = ndi_document({'base': {'id': '...', ...}})
            db.add(doc)
        """
        try:
            self._driver.add(document.document_properties)
        except FileExistsError as exc:
            raise ValueError(
                f"ndi_document with ID {document.id} already exists. "
                f"Documents are immutable once added; remove it first, or "
                f"give the new document its own id."
            ) from exc
        return document

    def read(self, doc_id: str, isa_class: str | None = None) -> ndi_document | None:
        """Read a document by ID.

        Args:
            doc_id: The document ID to find.
            isa_class: Optional class filter. If provided, returns None
                      if document is not of that class.

        Returns:
            The ndi_document, or None if not found.

        Example:
            doc = db.read('abc123')
        """
        result = self._driver.find_by_id(doc_id)
        if result is None:
            return None

        doc = ndi_document(result)

        if isa_class and not doc.doc_isa(isa_class):
            return None

        return doc

    def remove(self, document: ndi_document | str) -> bool:
        """Remove a document from the database.

        Args:
            document: The ndi_document or document ID to remove.

        Returns:
            True if removed, False if not found.

        Example:
            db.remove(doc)
            db.remove('abc123')
        """
        doc_id = document.id if isinstance(document, ndi_document) else document
        return self._driver.delete_by_id(doc_id)

    # === ndi_query Operations ===

    def search(
        self, query: ndi_query | None = None, isa_class: str | None = None
    ) -> list[ndi_document]:
        """Search for documents matching a query.

        Args:
            query: The ndi_query to match. If None, returns all documents.
            isa_class: Optional class filter. If provided, only returns
                      documents that are instances of that class.

        Returns:
            List of matching Documents.

        Example:
            # Find all documents
            all_docs = db.search()

            # Find by query
            probes = db.search(ndi_query('element.type') == 'probe')

            # Find all of a class
            elements = db.search(isa_class='element')

            # Combined
            my_probes = db.search(
                ndi_query('element.name').contains('elec'),
                isa_class='probe'
            )
        """
        # Build combined query
        combined = query
        if isa_class:
            isa_query = ndi_query("").isa(isa_class)
            combined = (combined & isa_query) if combined else isa_query

        # Execute search
        results = self._driver.find(combined)

        # Convert results to ndi.ndi_document
        return [ndi_document(r) for r in results]

    def find_by_id(self, doc_id: str) -> ndi_document | None:
        """Find a document by its ID.

        Alias for read() for MATLAB compatibility.

        Args:
            doc_id: The document ID.

        Returns:
            The ndi_document or None.
        """
        return self.read(doc_id)

    def alldocids(self) -> list[str]:
        """Get all document IDs in the database.

        Returns:
            List of document IDs.
        """
        all_docs = self._driver.find(None)
        return [doc.get("base", {}).get("id", "") for doc in all_docs]

    def numdocs(self) -> int:
        """Get the number of documents in the database.

        Returns:
            Number of documents.
        """
        return len(self._driver.find(None))

    # === Dependency Operations ===

    def find_depends_on(self, document: ndi_document | str) -> list[ndi_document]:
        """Find all documents that depend on a given document.

        Args:
            document: The ndi_document or document ID.

        Returns:
            List of Documents that depend on the given document.
        """
        doc_id = document.id if isinstance(document, ndi_document) else document
        # DID's depends_on query requires both name and value, but we want
        # all documents that depend on doc_id regardless of dependency name.
        # Search all documents and filter by depends_on value.
        all_docs = self.search(ndi_query.all())
        return [
            doc
            for doc in all_docs
            if any(
                dep.get("value") == doc_id
                for dep in doc.document_properties.get("depends_on", [])
                if isinstance(dep, dict)
            )
        ]

    def find_dependencies(self, document: ndi_document | str) -> list[ndi_document]:
        """Find all documents that a given document depends on.

        Args:
            document: The ndi_document or document ID.

        Returns:
            List of Documents that the given document depends on.
        """
        if isinstance(document, str):
            document = self.read(document)
            if not document:
                return []

        names, deps = document.dependency()
        results = []
        for dep in deps:
            dep_doc = self.read(dep["value"])
            if dep_doc:
                results.append(dep_doc)
        return results

    # === Batch Operations ===

    def add_many(self, documents: list[ndi_document]) -> list[ndi_document]:
        """Add multiple documents.

        Args:
            documents: List of Documents to add.

        Returns:
            List of added Documents.

        Adds the whole list in a single ``did.database.add_docs`` call, as
        MATLAB does. Validation checks each dependency against the ids already
        stored *plus the ids in this batch*, so a set of documents that refer
        to one another only validates when it is offered together -- added one
        at a time, anything referring to a document later in the list looks
        like a dangling reference.

        Note:
            Atomic: nothing is added if any document fails validation.
        """
        did_docs = []
        for doc in documents:
            props = doc.document_properties if hasattr(doc, "document_properties") else doc
            doc_id = props.get("base", {}).get("id", "")
            if not doc_id:
                raise ValueError("ndi_document must have a base.id")
            did_docs.append(self._driver._DIDDocument(props))

        if did_docs:
            self._driver._db.add_docs(
                did_docs,
                self._driver._branch_id,
                custom_file_handler=_cloud_file_handler,
            )
        return list(documents)

    def remove_many(
        self, query: ndi_query | None = None, documents: list[ndi_document] | None = None
    ) -> int:
        """Remove multiple documents.

        Args:
            query: ndi_query to select documents to remove.
            documents: Explicit list of documents to remove.

        Returns:
            Number of documents removed.

        Note:
            If both query and documents provided, removes union of both.
        """
        to_remove = set()

        if query:
            matches = self.search(query)
            for doc in matches:
                to_remove.add(doc.id)

        if documents:
            for doc in documents:
                to_remove.add(doc.id if isinstance(doc, ndi_document) else doc)

        count = 0
        for doc_id in to_remove:
            if self.remove(doc_id):
                count += 1
        return count

    # === File Management ===

    def open_binary(self, doc_or_id: ndi_document | str, file_name: str) -> Path:
        """Resolve a document's file to a local path, retrieving it if needed.

        Replaces ``get_binary_path``, which composed a path in NDI's own store
        and told the caller nothing about whether a file was there. DID owns
        the mapping from (document, filename) to a location now, so ask it.

        Raises:
            FileNotFoundError: subclassed by DID's FileAccessError, when no
                location can be reached.
        """
        doc_id = doc_or_id.id if isinstance(doc_or_id, ndi_document) else doc_or_id
        return Path(self._driver.open_binary(doc_id, file_name))

    def exist_binary(
        self, doc_or_id: ndi_document | str, file_name: str
    ) -> tuple[bool, Path | None]:
        """Is this document's file on disk, and where?"""
        doc_id = doc_or_id.id if isinstance(doc_or_id, ndi_document) else doc_or_id
        found, path = self._driver.exist_binary(doc_id, file_name)
        return found, (Path(path) if path else None)

    def __repr__(self) -> str:
        return f"ndi_database('{self.session_path}')"


# Convenience function
def open_database(session_path: str | Path, **kwargs) -> ndi_database:
    """Open or create an NDI database.

    This is a convenience function for ndi_database(). Uses DID-python's
    SQLiteDB for storage, ensuring compatibility with existing databases.

    Args:
        session_path: Path to the session directory.
        **kwargs: Additional options (e.g., db_name, branch_id).

    Returns:
        ndi_database instance.

    Example:
        db = open_database('/path/to/session')
    """
    return ndi_database(session_path, **kwargs)
