"""
ndi.database - NDI database interface

Provides database functionality for storing and querying NDI documents.
Uses DID-python's SQLiteDB for storage, ensuring compatibility with
existing DID-python and NDI-Matlab databases.

Example:
    # Create a database for a session
    db = Database('/path/to/session')

    # Add documents
    db.add(doc)

    # Query documents
    results = db.search(Query('element.name') == 'electrode1')

    # Find by ID
    doc = db.read(doc_id)
"""

from pathlib import Path

from .document import Document
from .query import Query


class SQLiteDriver:
    """SQLite database driver using DID-python's SQLiteDB.

    This driver wraps DID-python's SQLiteDB implementation to provide
    a consistent interface for the NDI Database class. Uses DID-python's
    field_search() for query evaluation.
    """

    def __init__(self, db_path: Path, branch_id: str = "main"):
        """Initialize the SQLite driver.

        Args:
            db_path: Path to the SQLite database file.
            branch_id: Default branch ID to use.
        """
        from did.datastructures import field_search
        from did.document import Document as DIDDocument
        from did.implementations.sqlitedb import SQLiteDB

        self._db_path = db_path
        self._branch_id = branch_id
        self._DIDDocument = DIDDocument
        self._field_search = field_search

        # Initialize SQLiteDB
        self._db = SQLiteDB(str(db_path))

        # Create main branch if it doesn't exist
        existing_branches = self._db.all_branch_ids()
        if branch_id not in existing_branches:
            self._db.add_branch(branch_id, "")  # Empty string for root branch

    def add(self, document: dict) -> None:
        """Add a document to the database."""
        doc_id = document.get("base", {}).get("id", "")
        if not doc_id:
            raise ValueError("Document must have a base.id")

        # Check if document already exists
        existing_ids = self._db.get_doc_ids(self._branch_id)
        if doc_id in existing_ids:
            raise FileExistsError(f"Document {doc_id} already exists")

        # Create DID Document and add
        did_doc = self._DIDDocument(document)
        self._db.add_docs([did_doc], self._branch_id)

    def bulk_add(self, documents: list[dict]) -> tuple[int, int]:
        """Add many documents at once, bypassing per-doc duplicate checks.

        Uses a single transaction for all inserts.  Duplicates (by
        ``base.id``) are silently skipped.

        Returns:
            ``(added, skipped)`` counts.
        """
        import json as json_mod
        import time

        existing_ids = set(self._db.get_doc_ids(self._branch_id))

        added = 0
        skipped = 0
        cursor = self._db.dbid.cursor()
        try:
            for doc in documents:
                doc_id = doc.get("base", {}).get("id", "")
                if not doc_id or doc_id in existing_ids:
                    skipped += 1
                    continue

                json_code = json_mod.dumps(doc)
                cursor.execute(
                    "INSERT INTO docs (doc_id, json_code, timestamp) VALUES (?, ?, ?)",
                    (doc_id, json_code, time.time()),
                )
                doc_idx = cursor.lastrowid
                try:
                    cursor.execute(
                        "INSERT INTO branch_docs (branch_id, doc_idx, timestamp) VALUES (?, ?, ?)",
                        (self._branch_id, doc_idx, time.time()),
                    )
                except Exception:
                    pass
                existing_ids.add(doc_id)
                added += 1
            self._db.dbid.commit()
        except Exception:
            self._db.dbid.rollback()
            raise

        return added, skipped

    def update(self, document: dict) -> None:
        """Update an existing document."""
        doc_id = document.get("base", {}).get("id", "")

        # Check if document exists
        existing_ids = self._db.get_doc_ids(self._branch_id)
        if doc_id not in existing_ids:
            raise FileNotFoundError(f"Document {doc_id} not found")

        # Remove old and add new (SQLiteDB doesn't have direct update)
        self._db.remove_docs([doc_id], self._branch_id)
        did_doc = self._DIDDocument(document)
        self._db.add_docs([did_doc], self._branch_id)

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

        Uses DID-python's field_search() for query evaluation.
        """
        import json as json_mod

        # Fetch all JSON blobs in a single SQL query instead of one-by-one.
        rows = self._db.do_run_sql_query(
            "SELECT d.json_code FROM docs d "
            "JOIN branch_docs bd ON d.doc_idx = bd.doc_idx "
            "WHERE bd.branch_id = ?",
            (self._branch_id,),
        )

        if not rows:
            return []

        documents = [json_mod.loads(r["json_code"]) for r in rows]

        # Filter by query if provided using DID-python's field_search
        if query is not None:
            # Convert to DID-python compatible format
            search_params = query.to_search_structure()
            documents = [d for d in documents if self._field_search(d, search_params)]

        return documents


class Database:
    """NDI database interface.

    Provides document storage and querying using DID-python's SQLiteDB.
    This ensures compatibility with existing DID-python and NDI-Matlab databases.

    Attributes:
        session_path: Path to the session directory.

    Example:
        db = Database('/path/to/session')
        db.add(doc)
        docs = db.search(Query('element.type') == 'probe')
    """

    def __init__(self, session_path: str | Path, db_name: str = ".ndi", **backend_kwargs):
        """Initialize NDI database.

        Args:
            session_path: Path to the session directory.
            db_name: Name of the database directory within session.
                     Default is '.ndi'.
            **backend_kwargs: Additional arguments passed to SQLiteDriver
                             (e.g., branch_id='main').
        """
        self.session_path = Path(session_path)
        self._db_name = db_name

        # Create session directory if it doesn't exist
        self.session_path.mkdir(parents=True, exist_ok=True)

        # Create db directory
        db_dir = self.session_path / db_name
        db_dir.mkdir(parents=True, exist_ok=True)

        # Initialize SQLite driver (wraps DID-python's SQLiteDB)
        db_path = db_dir / "ndi.db"
        self._driver = SQLiteDriver(db_path, **backend_kwargs)

        # Binary directory for file attachments
        self._binary_dir = self.session_path / db_name / "binary"
        self._binary_dir.mkdir(parents=True, exist_ok=True)

    @property
    def database_path(self) -> Path:
        """Path to the SQLite database file."""
        return self.session_path / self._db_name / "ndi.db"

    @property
    def binary_path(self) -> Path:
        """Path where binary files are stored."""
        return self._binary_dir

    # === CRUD Operations ===

    def add(self, document: Document) -> Document:
        """Add a document to the database.

        Args:
            document: The Document to add.

        Returns:
            The added document.

        Raises:
            ValueError: If document already exists in database.

        Example:
            doc = Document({'base': {'id': '...', ...}})
            db.add(doc)
        """
        try:
            self._driver.add(document.document_properties)
        except FileExistsError as exc:
            raise ValueError(
                f"Document with ID {document.id} already exists. "
                f"Use update() or add_or_replace()."
            ) from exc
        return document

    def read(self, doc_id: str, isa_class: str | None = None) -> Document | None:
        """Read a document by ID.

        Args:
            doc_id: The document ID to find.
            isa_class: Optional class filter. If provided, returns None
                      if document is not of that class.

        Returns:
            The Document, or None if not found.

        Example:
            doc = db.read('abc123')
        """
        result = self._driver.find_by_id(doc_id)
        if result is None:
            return None

        doc = Document(result)

        if isa_class and not doc.doc_isa(isa_class):
            return None

        return doc

    def remove(self, document: Document | str) -> bool:
        """Remove a document from the database.

        Args:
            document: The Document or document ID to remove.

        Returns:
            True if removed, False if not found.

        Example:
            db.remove(doc)
            db.remove('abc123')
        """
        doc_id = document.id if isinstance(document, Document) else document
        return self._driver.delete_by_id(doc_id)

    def update(self, document: Document) -> Document:
        """Update an existing document.

        Args:
            document: The Document with updated properties.

        Returns:
            The updated document.

        Raises:
            ValueError: If document doesn't exist.

        Example:
            doc = db.read('abc123')
            doc = doc.setproperties(**{'base.name': 'new_name'})
            db.update(doc)
        """
        try:
            self._driver.update(document.document_properties)
        except FileNotFoundError as exc:
            raise ValueError(
                f"Document with ID {document.id} not found. " f"Use add() for new documents."
            ) from exc
        return document

    def add_or_replace(self, document: Document) -> Document:
        """Add or replace a document.

        If document exists, replaces it. Otherwise, adds it.

        Args:
            document: The Document to add or replace.

        Returns:
            The document.

        Example:
            db.add_or_replace(doc)
        """
        existing = self._driver.find_by_id(document.id)
        if existing:
            self._driver.update(document.document_properties)
        else:
            self._driver.add(document.document_properties)

        return document

    # === Query Operations ===

    def search(self, query: Query | None = None, isa_class: str | None = None) -> list[Document]:
        """Search for documents matching a query.

        Args:
            query: The Query to match. If None, returns all documents.
            isa_class: Optional class filter. If provided, only returns
                      documents that are instances of that class.

        Returns:
            List of matching Documents.

        Example:
            # Find all documents
            all_docs = db.search()

            # Find by query
            probes = db.search(Query('element.type') == 'probe')

            # Find all of a class
            elements = db.search(isa_class='element')

            # Combined
            my_probes = db.search(
                Query('element.name').contains('elec'),
                isa_class='probe'
            )
        """
        # Build combined query
        combined = query
        if isa_class:
            isa_query = Query("").isa(isa_class)
            combined = (combined & isa_query) if combined else isa_query

        # Execute search
        results = self._driver.find(combined)

        # Convert results to ndi.Document
        return [Document(r) for r in results]

    def find_by_id(self, doc_id: str) -> Document | None:
        """Find a document by its ID.

        Alias for read() for MATLAB compatibility.

        Args:
            doc_id: The document ID.

        Returns:
            The Document or None.
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

    def find_depends_on(self, document: Document | str) -> list[Document]:
        """Find all documents that depend on a given document.

        Args:
            document: The Document or document ID.

        Returns:
            List of Documents that depend on the given document.
        """
        doc_id = document.id if isinstance(document, Document) else document
        # DID's depends_on query requires both name and value, but we want
        # all documents that depend on doc_id regardless of dependency name.
        # Search all documents and filter by depends_on value.
        all_docs = self.search(Query.all())
        return [
            doc
            for doc in all_docs
            if any(
                dep.get("value") == doc_id
                for dep in doc.document_properties.get("depends_on", [])
                if isinstance(dep, dict)
            )
        ]

    def find_dependencies(self, document: Document | str) -> list[Document]:
        """Find all documents that a given document depends on.

        Args:
            document: The Document or document ID.

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

    def add_many(self, documents: list[Document]) -> list[Document]:
        """Add multiple documents.

        Args:
            documents: List of Documents to add.

        Returns:
            List of added Documents.

        Note:
            Stops on first error. Use add() individually for error handling.
        """
        added = []
        for doc in documents:
            added.append(self.add(doc))
        return added

    def remove_many(
        self, query: Query | None = None, documents: list[Document] | None = None
    ) -> int:
        """Remove multiple documents.

        Args:
            query: Query to select documents to remove.
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
                to_remove.add(doc.id if isinstance(doc, Document) else doc)

        count = 0
        for doc_id in to_remove:
            if self.remove(doc_id):
                count += 1
        return count

    # === File Management ===

    def get_binary_path(self, document: Document, file_name: str) -> Path:
        """Get the path where a document's binary file should be stored.

        Args:
            document: The document that owns the file.
            file_name: Name of the file.

        Returns:
            Path to store the binary file.
        """
        return self._binary_dir / f"{document.id}_{file_name}"

    def __repr__(self) -> str:
        return f"Database('{self.session_path}')"


# Convenience function
def open_database(session_path: str | Path, **kwargs) -> Database:
    """Open or create an NDI database.

    This is a convenience function for Database(). Uses DID-python's
    SQLiteDB for storage, ensuring compatibility with existing databases.

    Args:
        session_path: Path to the session directory.
        **kwargs: Additional options (e.g., db_name, branch_id).

    Returns:
        Database instance.

    Example:
        db = open_database('/path/to/session')
    """
    return Database(session_path, **kwargs)
