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

    # Query documents
    results = db.search(ndi_query('element.name') == 'electrode1')

    # Find by ID
    doc = db.read(doc_id)
"""

from pathlib import Path

from .document import ndi_document
from .query import ndi_query


def _normalize_doc_props(props: dict) -> dict:
    """Normalize the list-valued fields a MATLAB database stores as a single
    bare dict into lists, so DID's ``field_search`` can iterate them.

    Covers ``depends_on``, ``document_class.superclasses`` and
    ``files.file_info`` — the same fields ``ndi_document`` normalizes, but as a
    cheap dict rewrite with NO full document construction (which would re-read
    each document's blank definition from disk, catastrophically slow across a
    whole database).
    """
    if not isinstance(props, dict):
        return props
    p = dict(props)
    dep = p.get("depends_on")
    if isinstance(dep, dict):
        p["depends_on"] = [dep]
    dc = p.get("document_class")
    if isinstance(dc, dict) and isinstance(dc.get("superclasses"), dict):
        dc = dict(dc)
        dc["superclasses"] = [dc["superclasses"]]
        p["document_class"] = dc
    files = p.get("files")
    if isinstance(files, dict) and isinstance(files.get("file_info"), dict):
        files = dict(files)
        files["file_info"] = [files["file_info"]]
        p["files"] = files
    return p


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
        self._DIDDocument = DIDDocument

        # Initialize SQLiteDB
        self._db = SQLiteDB(str(db_path))

        # Resolve the branch to read. New Python datasets use "a", but a
        # MATLAB-written database stores its documents on the "main" branch
        # (and opening it with the default "a" would create an empty branch
        # and silently read zero documents). So: if the requested branch holds
        # no documents but another branch does, adopt the populated one.
        existing_branches = self._db.all_branch_ids()
        requested_empty = (branch_id not in existing_branches) or not self._db.get_doc_ids(
            branch_id
        )
        if requested_empty:
            populated = [b for b in existing_branches if b != branch_id and self._db.get_doc_ids(b)]
            if populated:
                branch_id = populated[0]
            elif branch_id not in existing_branches:
                self._db.add_branch(branch_id, "")  # Empty string for root branch
        self._branch_id = branch_id

    def add(self, document: dict) -> None:
        """Add a document to the database."""
        doc_id = document.get("base", {}).get("id", "")
        if not doc_id:
            raise ValueError("Document must have a base.id")

        # Check if document already exists
        existing_ids = self._db.get_doc_ids(self._branch_id)
        if doc_id in existing_ids:
            raise FileExistsError(f"Document {doc_id} already exists")

        # Create DID Document and add (DID-python now populates doc_data)
        did_doc = self._DIDDocument(document)
        self._db.add_docs([did_doc], self._branch_id)

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
            self._db.add_docs([did_doc], self._branch_id)
            existing_ids.add(doc_id)
            added += 1

        return added, skipped

    def bulk_add_documents(self, documents: list[dict]) -> list[tuple[str, str]]:
        """Add many documents in a single O(N) pass.

        Fetches the existing-id set ONCE (not per document, as :meth:`add`
        does) and inserts all new documents with one ``add_docs`` call.
        Loading N documents is therefore O(N) instead of the O(N^2) of a
        per-document ``add`` loop, where each ``add`` re-scans every existing
        id (the cause of multi-minute loads of large datasets).

        Per-document problems (missing ``base.id``, duplicate id, or a
        malformed document that will not construct) are collected and
        returned rather than raised, preserving the resilience of the
        per-document add loop. Returns a list of ``(doc_id, reason)`` for
        each document that was not added.
        """
        existing_ids = set(self._db.get_doc_ids(self._branch_id))
        failures: list[tuple[str, str]] = []
        new_docs = []
        for document in documents:
            doc_id = document.get("base", {}).get("id", "")
            if not doc_id:
                failures.append(("", "ndi_document must have a base.id"))
                continue
            if doc_id in existing_ids:
                failures.append((doc_id, f"ndi_document {doc_id} already exists"))
                continue
            try:
                new_docs.append(self._DIDDocument(document))
            except Exception as exc:  # noqa: BLE001 - mirror per-doc add resilience
                failures.append((doc_id, str(exc)))
                continue
            existing_ids.add(doc_id)
        # DID's add_docs is O(N^2) *within a single call*, so a one-shot insert of
        # tens of thousands of documents takes minutes (a 78k-doc one-shot load is
        # ~9 min). Insert in fixed-size chunks so each call stays bounded and the
        # whole load is linear (the same reason _maybe_import_matlab_db chunks).
        CHUNK = 4000
        for start in range(0, len(new_docs), CHUNK):
            self._db.add_docs(new_docs[start : start + CHUNK], self._branch_id)
        return failures

    def update(self, document: dict) -> None:
        """Update an existing document."""
        doc_id = document.get("base", {}).get("id", "")

        # Check if document exists
        existing_ids = self._db.get_doc_ids(self._branch_id)
        if doc_id not in existing_ids:
            raise FileNotFoundError(f"Document {doc_id} not found")

        # Remove old and add new (DID handles doc_data cleanup and repopulation)
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

        Uses DID-python's SQL-based search against the doc_data table
        for query evaluation, falling back to brute-force for unsupported
        operations.  Retrieval is via DID-python's :meth:`get_doc_ids` +
        :meth:`get_docs` (not ``get_docs_by_branch``, which is absent from
        the released DID-python and was the source of the AttributeError that
        made every "fetch all documents" path fail).
        """
        if query is not None:
            try:
                doc_ids = self._db.search(query, self._branch_id)
            except (AttributeError, TypeError):
                # DID's field_search iterates depends_on/superclasses assuming
                # they are lists of dicts, but a MATLAB-written database stores
                # a single-element depends_on/superclasses as a bare dict, which
                # crashes the native search. Fall back to a normalized
                # brute-force pass over every document.
                return self._brute_force_find(query)
        else:
            doc_ids = self._db.get_doc_ids(self._branch_id)
        if not doc_ids:
            return []
        docs = self._db.get_docs(doc_ids, self._branch_id, OnMissing="ignore")
        # get_docs returns a single object when given one id; normalize to a list.
        if not isinstance(docs, (list, tuple)):
            docs = [docs]
        return [d.document_properties for d in docs if d is not None]

    def _brute_force_find(self, query) -> list[dict]:
        """Evaluate *query* in Python over normalized documents.

        Used when the native DID search cannot handle a MATLAB-written
        database (bare-dict ``depends_on``/``superclasses``). Each document is
        passed through ``_normalize_doc_props`` — which normalizes those
        single-element fields into lists — before applying DID's
        ``field_search`` predicate, so the same query semantics apply.
        """
        from did.datastructures import field_search

        doc_ids = self._db.get_doc_ids(self._branch_id)
        if not doc_ids:
            return []
        docs = self._db.get_docs(doc_ids, self._branch_id, OnMissing="ignore")
        if not isinstance(docs, (list, tuple)):
            docs = [docs]
        results: list[dict] = []
        for d in docs:
            if d is None:
                continue
            props = _normalize_doc_props(d.document_properties)
            try:
                if field_search(props, query):
                    results.append(props)
            except Exception:  # noqa: BLE001 - skip any doc the predicate can't evaluate
                continue
        return results


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

        # Initialize SQLite driver (wraps DID-python's SQLiteDB). Python writes
        # "did-sqlite.sqlite"; MATLAB writes "ndi.db" (same DID schema). When
        # opening an existing directory, use whichever file actually holds
        # documents so MATLAB-written datasets open correctly instead of
        # silently reading an empty Python database.
        db_path = self._resolve_db_file(db_dir)
        # A MATLAB-written ndi.db stores single-element depends_on/superclasses
        # as bare dicts, which the native DID search cannot handle (find() falls
        # back to a slow per-query brute-force pass). Import it once into a
        # normalized Python did-sqlite.sqlite so subsequent queries use DID's
        # fast native search.
        db_path = self._maybe_import_matlab_db(db_path, db_dir)
        self._driver = SQLiteDriver(db_path, **backend_kwargs)

        # Binary/files directory for file attachments
        # Named "files" for compatibility with NDI-MATLAB
        self._binary_dir = self.session_path / db_name / "files"
        self._binary_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _resolve_db_file(db_dir: Path) -> Path:
        """Pick the DID SQLite file to open from *db_dir*.

        Python writes ``did-sqlite.sqlite``; MATLAB writes ``ndi.db`` (identical
        DID schema). When both (or a stale empty one) are present, choose the
        file whose ``branch_docs`` table holds the most rows, so a MATLAB-written
        dataset opens its real documents instead of an empty Python placeholder.
        Defaults to ``did-sqlite.sqlite`` for a brand-new (empty) directory.
        """
        import sqlite3

        default = db_dir / "did-sqlite.sqlite"
        candidates = [default, db_dir / "ndi.db"]
        best: Path | None = None
        best_count = -1
        for cand in candidates:
            if not cand.exists():
                continue
            count = 0
            try:
                con = sqlite3.connect(f"file:{cand}?mode=ro", uri=True)
                try:
                    count = con.execute("SELECT count(*) FROM branch_docs").fetchone()[0]
                finally:
                    con.close()
            except Exception:  # noqa: BLE001 - unreadable/foreign file -> treat as empty
                count = 0
            if count > best_count:
                best_count = count
                best = cand
        return best if best is not None else default

    @staticmethod
    def _maybe_import_matlab_db(db_path: Path, db_dir: Path) -> Path:
        """Import a MATLAB ``ndi.db`` into a normalized Python database, once.

        MATLAB stores single-element ``depends_on``/``superclasses`` as bare
        dicts that DID's native ``field_search`` cannot iterate, so queries on a
        MATLAB database fall back to a slow per-query brute-force scan. This
        reads each document, normalizes its bare-dict fields to lists, and writes a
        sibling ``did-sqlite.sqlite`` that supports DID's
        fast native search. Idempotent: if the Python file already holds at
        least as many documents as ``ndi.db``, it is reused. Returns the path to
        open (the Python database when imported, else *db_path* unchanged).
        """
        if db_path.name != "ndi.db":
            return db_path

        python_db = db_dir / "did-sqlite.sqlite"
        src = SQLiteDriver(db_path)  # branch auto-detected ("main")
        src_ids = src._db.get_doc_ids(src._branch_id)
        if not src_ids:
            return db_path

        # Reuse an already-imported Python database.
        if python_db.exists():
            try:
                existing = SQLiteDriver(python_db)
                if len(existing._db.get_doc_ids(existing._branch_id)) >= len(src_ids):
                    return python_db
            except Exception:  # noqa: BLE001 - stale/corrupt -> re-import below
                pass

        # Import in chunks. DID's add_docs is O(N^2) within a single call, so a
        # one-shot insert of tens of thousands of documents takes minutes; a
        # fixed chunk size keeps each insert bounded (constant per chunk) and the
        # whole import linear. Read + normalize each chunk lazily so peak memory
        # stays bounded too.
        dst = SQLiteDriver(python_db, branch_id="a")
        existing = set(dst._db.get_doc_ids(dst._branch_id))
        CHUNK = 4000
        for start in range(0, len(src_ids), CHUNK):
            chunk_ids = src_ids[start : start + CHUNK]
            raw = src._db.get_docs(chunk_ids, src._branch_id, OnMissing="ignore")
            if not isinstance(raw, (list, tuple)):
                raw = [raw]
            new_docs = []
            for d in raw:
                if d is None:
                    continue
                doc_id = d.document_properties.get("base", {}).get("id", "")
                if not doc_id or doc_id in existing:
                    continue
                new_docs.append(dst._DIDDocument(_normalize_doc_props(d.document_properties)))
                existing.add(doc_id)
            if new_docs:
                dst._db.add_docs(new_docs, dst._branch_id)
        return python_db

    @property
    def database_path(self) -> Path:
        """Path to the SQLite database file."""
        return self.session_path / self._db_name / "did-sqlite.sqlite"

    @property
    def binary_path(self) -> Path:
        """Path where binary files are stored."""
        return self._binary_dir

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
                f"Use update() or add_or_replace()."
            ) from exc
        return document

    def add_documents(self, documents: list[ndi_document]) -> list[tuple[str, str]]:
        """Add many documents in one O(N) pass (single existing-id fetch).

        Use this instead of a per-document :meth:`add` loop when ingesting
        many documents at once (e.g. loading a dataset): repeated ``add``
        re-scans every existing id on each call and is O(N^2), which makes
        large datasets take many minutes to load. Returns a list of
        ``(doc_id, reason)`` for documents that could not be added, instead
        of raising, so one bad document does not abort the whole load.
        """
        return self._driver.bulk_add_documents([d.document_properties for d in documents])

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

    def update(self, document: ndi_document) -> ndi_document:
        """Update an existing document.

        Args:
            document: The ndi_document with updated properties.

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
                f"ndi_document with ID {document.id} not found. " f"Use add() for new documents."
            ) from exc
        return document

    def add_or_replace(self, document: ndi_document) -> ndi_document:
        """Add or replace a document.

        If document exists, replaces it. Otherwise, adds it.

        Args:
            document: The ndi_document to add or replace.

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

    def search(
        self, query: ndi_query | None = None, isa_class: str | None = None
    ) -> list[ndi_document]:
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

        Note:
            Stops on first error. Use add() individually for error handling.
        """
        added = []
        for doc in documents:
            added.append(self.add(doc))
        return added

    def remove_many(
        self, query: ndi_query | None = None, documents: list[ndi_document] | None = None
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
                to_remove.add(doc.id if isinstance(doc, ndi_document) else doc)

        count = 0
        for doc_id in to_remove:
            if self.remove(doc_id):
                count += 1
        return count

    # === File Management ===

    def get_binary_path(self, document: ndi_document, file_name: str) -> Path:
        """Get the path where a document's binary file should be stored.

        Args:
            document: The document that owns the file.
            file_name: Name of the file.

        Returns:
            Path to store the binary file.
        """
        return self._binary_dir / f"{document.id}_{file_name}"

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
