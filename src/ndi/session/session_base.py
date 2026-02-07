"""
ndi.session.session_base - Base class for NDI sessions.

This module provides the Session abstract base class that manages
NDI experiments including DAQ systems, database, syncgraph, and probes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..cache import Cache
from ..database import Database
from ..document import Document
from ..ido import Ido
from ..query import Query
from ..time.syncgraph import SyncGraph
from ..time.syncrule_base import SyncRule


def empty_id() -> str:
    """
    Produce the empty session ID.

    Returns a string that indicates "no specific session"
    or "applies in any session".

    Returns:
        String '0000000000000000_0000000000000000'
    """
    ido = Ido()
    base_id = ido.id
    # Replace all non-underscore characters with '0'
    return "".join("0" if c != "_" else "_" for c in base_id)


class Session(ABC):
    """
    Abstract base class for NDI sessions.

    Session represents a neuroscience experiment/recording session and
    provides access to:
    - Database for document storage
    - DAQ systems for data acquisition
    - SyncGraph for time synchronization
    - Cache for performance optimization

    Subclasses must implement:
    - getpath(): Return the storage path
    - creator_args(): Return arguments needed to recreate the session

    Attributes:
        reference: Human-readable session reference
        identifier: Unique session ID

    Example:
        >>> session = DirSession('/path/to/experiment')
        >>> session.daqsystem_add(my_daq)
        >>> docs = session.database_search(Query('element.type') == 'probe')
    """

    def __init__(self, reference: str):
        """
        Create a new Session.

        Args:
            reference: Human-readable reference for the session
        """
        self._reference = reference
        self._identifier = Ido().id
        self._syncgraph: SyncGraph | None = None
        self._cache = Cache()
        self._database: Database | None = None

    @property
    def reference(self) -> str:
        """Get the session reference."""
        return self._reference

    @property
    def identifier(self) -> str:
        """Get the unique session identifier."""
        return self._identifier

    def id(self) -> str:
        """
        Get the unique session identifier.

        Returns:
            The session's unique identifier string.
        """
        return self._identifier

    @property
    def syncgraph(self) -> SyncGraph | None:
        """Get the session's syncgraph."""
        return self._syncgraph

    @property
    def cache(self) -> Cache:
        """Get the session's cache."""
        return self._cache

    @property
    def database(self) -> Database | None:
        """Get the session's database."""
        return self._database

    # =========================================================================
    # DAQ System Methods
    # =========================================================================

    def daqsystem_add(self, dev: Any) -> Session:
        """
        Add a DAQ system to the session.

        Args:
            dev: The DAQSystem object to add

        Returns:
            self for chaining

        Raises:
            TypeError: If dev is not a DAQSystem
            ValueError: If DAQ system already exists
        """
        from ..daq.system import DAQSystem

        if not isinstance(dev, DAQSystem):
            raise TypeError("dev must be an ndi.daq.DAQSystem")

        # Set the session on the DAQ system
        dev = dev.setsession(self)

        # Check if already exists
        sq = dev.searchquery()
        search_result = self.database_search(sq)

        # Also check by name
        sq1 = Query("").isa("daqsystem") & (Query("base.name") == dev.name)
        search_result1 = self.database_search(sq1)

        if len(search_result) == 0 and len(search_result1) == 0:
            # Can add to database
            doc_set = dev.newdocument()
            if not isinstance(doc_set, list):
                doc_set = [doc_set]
            for doc in doc_set:
                self.database_add(doc)
        else:
            raise ValueError(f"DAQ system '{dev.name}' or one with same ID already exists")

        return self

    def daqsystem_rm(self, dev: Any) -> Session:
        """
        Remove a DAQ system from the session.

        Args:
            dev: The DAQSystem to remove

        Returns:
            self for chaining

        Raises:
            TypeError: If dev is not a DAQSystem
            ValueError: If DAQ system not found
        """
        from ..daq.system import DAQSystem

        if not isinstance(dev, DAQSystem):
            raise TypeError("dev must be an ndi.daq.DAQSystem")

        daqsys = self.daqsystem_load(name=dev.name)
        if not daqsys:
            raise ValueError(f"No DAQ system named '{dev.name}' found")

        if not isinstance(daqsys, list):
            daqsys = [daqsys]

        for daq in daqsys:
            docs = self.database_search(daq.searchquery())
            for doc in docs:
                # Remove dependencies first
                names, deps = doc.dependency()
                for dep in deps:
                    dep_docs = self.database_search(Query("base.id") == dep["value"])
                    for dep_doc in dep_docs:
                        self.database_rm(dep_doc)
                # Remove the document itself
                self.database_rm(doc)

        return self

    def daqsystem_load(self, name: str | None = None, **kwargs) -> list[Any] | Any | None:
        """
        Load DAQ systems from the session.

        Args:
            name: Optional name pattern to match (regex)
            **kwargs: Additional field=value pairs to match

        Returns:
            List of DAQSystem objects, single DAQSystem if only one,
            or None if none found.

        Example:
            >>> all_daqs = session.daqsystem_load(name='(.*)')
            >>> intan_daq = session.daqsystem_load(name='Intan')
        """

        # Build query
        q = Query("").isa("daqsystem")
        q = q & (Query("base.session_id") == self.id())

        # Add name filter (using regex match for compatibility)
        if name is not None:
            q = q & (Query("base.name").match(name))

        # Add other filters
        for field, value in kwargs.items():
            if field == "name":
                continue  # Already handled
            q = q & (Query(field) == value)

        # Search database
        dev_docs = self.database_search(q)

        # Convert to DAQSystem objects
        dev = []
        for doc in dev_docs:
            try:
                daq = self._document_to_object(doc)
                if daq is not None:
                    dev.append(daq)
            except Exception:
                pass

        if len(dev) == 0:
            return None
        elif len(dev) == 1:
            return dev[0]
        else:
            return dev

    def daqsystem_clear(self) -> Session:
        """
        Remove all DAQ systems from the session.

        Returns:
            self for chaining
        """
        devs = self.daqsystem_load(name="(.*)")
        if devs is not None:
            if not isinstance(devs, list):
                devs = [devs]
            for dev in devs:
                self.daqsystem_rm(dev)
        return self

    # =========================================================================
    # Database Methods
    # =========================================================================

    def database_add(self, document: Document | list[Document]) -> Session:
        """
        Add a document to the session database.

        Args:
            document: Document or list of Documents to add

        Returns:
            self for chaining

        Raises:
            ValueError: If document session_id doesn't match
        """
        if self._database is None:
            raise RuntimeError("Session has no database")

        if not isinstance(document, list):
            document = [document]

        # Validate and set session IDs
        for doc in document:
            session_id = doc.session_id
            if session_id and session_id != self.id() and session_id != empty_id():
                raise ValueError(
                    f"Document session_id '{session_id}' doesn't match " f"session id '{self.id()}'"
                )
            # Set session ID if empty or unset
            if not session_id or session_id == empty_id():
                doc = doc.set_session_id(self.id())

            self._database.add(doc)

            # Ingest binary files: copy from original location to binary dir
            self._ingest_binary_files(doc)

        return self

    def _ingest_binary_files(self, doc: Document) -> None:
        """Copy binary file attachments into the database's binary directory.

        For each file location with ``ingest=True``, the source file is
        copied to ``<binary_dir>/<doc.id>_<filename>`` so that
        ``database_openbinarydoc`` can find it.
        """
        import shutil

        if self._database is None:
            return
        props = doc.document_properties
        files = props.get("files", {})
        if not isinstance(files, dict):
            return
        for fi in files.get("file_info", []):
            name = fi.get("name", "")
            if not name:
                continue
            for loc in fi.get("locations", []):
                if not loc.get("ingest", False):
                    continue
                source = loc.get("location", "")
                if not source:
                    continue
                from pathlib import Path

                src_path = Path(source)
                if not src_path.exists():
                    continue
                dest_path = self._database.get_binary_path(doc, name)
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src_path), str(dest_path))

    def database_rm(
        self,
        doc_or_id: Document | str | list[Document | str],
        error_if_not_found: bool = False,
    ) -> Session:
        """
        Remove a document from the session database.

        Args:
            doc_or_id: Document, document ID, or list of either
            error_if_not_found: If True, raise error when not found

        Returns:
            self for chaining
        """
        if self._database is None:
            raise RuntimeError("Session has no database")

        if not isinstance(doc_or_id, list):
            doc_or_id = [doc_or_id]

        doc_list = self._docinput2docs(doc_or_id)

        # Find and remove dependents
        for doc in doc_list:
            dependents = self._find_all_dependencies(doc)
            for dep in dependents:
                self._database.remove(dep)
            self._database.remove(doc)

        return self

    def database_search(self, query: Query) -> list[Document]:
        """
        Search for documents in the session database.

        Args:
            query: Query to match

        Returns:
            List of matching Documents
        """
        if self._database is None:
            return []

        # Add session filter
        in_session = Query("base.session_id") == self.id()
        return self._database.search(query & in_session)

    def database_clear(self, areyousure: str) -> Session:
        """
        Delete all documents from the database.

        Args:
            areyousure: Must be 'yes' to proceed

        Returns:
            self for chaining
        """
        if areyousure.lower() != "yes":
            return self

        if self._database is not None:
            all_docs = self._database.search()
            for doc in all_docs:
                self._database.remove(doc)

        return self

    def validate_documents(self, documents: Document | list[Document]) -> tuple[bool, str]:
        """
        Validate that documents belong to this session.

        Args:
            documents: Document or list to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isinstance(documents, list):
            documents = [documents]

        for doc in documents:
            if not isinstance(doc, Document):
                return False, "All entries must be Document objects"

            session_id = doc.session_id
            if session_id != self.id() and session_id != empty_id():
                return False, (
                    f"Document {doc.id} has session_id '{session_id}' "
                    f"which doesn't match session id '{self.id()}'"
                )

        return True, ""

    # =========================================================================
    # Binary Document Methods
    # =========================================================================

    def database_openbinarydoc(
        self,
        doc_or_id: Document | str,
        filename: str,
    ) -> Any:
        """
        Open a binary document for reading.

        Args:
            doc_or_id: Document or document ID
            filename: Name of the binary file

        Returns:
            File-like object for reading

        Note:
            The file must be closed with database_closebinarydoc()
        """
        if self._database is None:
            raise RuntimeError("Session has no database")

        doc_id = doc_or_id.id if isinstance(doc_or_id, Document) else doc_or_id
        doc = self._database.read(doc_id)
        if doc is None:
            raise FileNotFoundError(f"Document {doc_id} not found")

        file_path = self._database.get_binary_path(doc, filename)
        if not file_path.exists():
            raise FileNotFoundError(f"Binary file {filename} not found")

        return open(file_path, "rb")

    def database_existbinarydoc(
        self,
        doc_or_id: Document | str,
        filename: str,
    ) -> tuple[bool, Path | None]:
        """
        Check if a binary document exists.

        Args:
            doc_or_id: Document or document ID
            filename: Name of the binary file

        Returns:
            Tuple of (exists, file_path)
        """
        if self._database is None:
            return False, None

        doc_id = doc_or_id.id if isinstance(doc_or_id, Document) else doc_or_id
        doc = self._database.read(doc_id)
        if doc is None:
            return False, None

        file_path = self._database.get_binary_path(doc, filename)
        return file_path.exists(), file_path

    def database_closebinarydoc(self, file_obj: Any) -> None:
        """
        Close a binary document file.

        Args:
            file_obj: File object to close
        """
        if hasattr(file_obj, "close"):
            file_obj.close()

    # =========================================================================
    # SyncGraph Methods
    # =========================================================================

    def syncgraph_addrule(self, rule: SyncRule) -> Session:
        """
        Add a sync rule to the session's syncgraph.

        Args:
            rule: SyncRule to add

        Returns:
            self for chaining
        """
        if self._syncgraph is None:
            self._syncgraph = SyncGraph(self)

        self._syncgraph.add_rule(rule)
        self._update_syncgraph_in_db()
        return self

    def syncgraph_rmrule(self, index: int) -> Session:
        """
        Remove a sync rule from the session's syncgraph.

        Args:
            index: Index of the rule to remove

        Returns:
            self for chaining
        """
        if self._syncgraph is not None:
            self._syncgraph.remove_rule(index)
            self._update_syncgraph_in_db()
        return self

    def _update_syncgraph_in_db(self) -> None:
        """Update the syncgraph document in the database."""
        if self._syncgraph is None or self._database is None:
            return

        # Remove old syncgraph docs
        old_docs = self.database_search(
            Query("").isa("syncgraph") & (Query("base.session_id") == self.id())
        )
        for doc in old_docs:
            self._database.remove(doc)

        # Remove old syncrule docs
        old_rules = self.database_search(
            Query("").isa("syncrule") & (Query("base.session_id") == self.id())
        )
        for doc in old_rules:
            self._database.remove(doc)

        # Add new documents
        new_docs = self._syncgraph.new_document()
        for doc in new_docs:
            doc = doc.set_session_id(self.id())
            self._database.add(doc)

    # =========================================================================
    # Ingest Methods
    # =========================================================================

    def ingest(self) -> tuple[bool, str]:
        """
        Ingest all raw data and sync info into the database.

        Returns:
            Tuple of (success, error_message)
        """
        errmsg = ""

        # Ingest syncgraph
        if self._syncgraph is not None:
            d_syncgraph = self._syncgraph.new_document()

        # Get all DAQ systems
        daqs = self.daqsystem_load(name="(.*)")
        if daqs is None:
            daqs = []
        elif not isinstance(daqs, list):
            daqs = [daqs]

        # Ingest each DAQ system
        daq_docs = []
        success = True
        for daq in daqs:
            try:
                b, docs = daq.ingest()
                daq_docs.append(docs)
                if not b:
                    success = False
                    errmsg = f"Error in DAQ {daq.name}"
            except Exception as e:
                success = False
                errmsg = str(e)

        if not success:
            # Clean up on failure
            for docs in daq_docs:
                if docs:
                    for doc in docs if isinstance(docs, list) else [docs]:
                        self.database_rm(doc)
        else:
            # Add syncgraph documents
            if self._syncgraph is not None:
                for doc in d_syncgraph:
                    doc = doc.set_session_id(self.id())
                    self.database_add(doc)

        return success, errmsg

    def get_ingested_docs(self) -> list[Document]:
        """
        Get all documents related to ingested data.

        Returns:
            List of ingested data documents
        """
        q_i1 = Query("").isa("daqreader_mfdaq_epochdata_ingested")
        q_i2 = Query("").isa("daqmetadatareader_epochdata_ingested")
        q_i3 = Query("").isa("epochfiles_ingested")
        q_i4 = Query("").isa("syncrule_mapping")

        return self.database_search(q_i1 | q_i2 | q_i3 | q_i4)

    def is_fully_ingested(self) -> bool:
        """
        Check if the session is fully ingested.

        Returns:
            True if all data has been ingested
        """
        daqs = self.daqsystem_load(name="(.*)")
        if daqs is None:
            return True
        if not isinstance(daqs, list):
            daqs = [daqs]

        for daq in daqs:
            if hasattr(daq, "filenavigator"):
                docs = daq.filenavigator.ingest()
                if docs:
                    return False
        return True

    # =========================================================================
    # Probe and Element Methods
    # =========================================================================

    def getprobes(self, classmatch: str | None = None, **kwargs) -> list[Any]:
        """
        Get all probes in the session.

        Args:
            classmatch: Optional class name to filter by
            **kwargs: Property filters (name, reference, type, subject_id)

        Returns:
            List of Probe objects
        """
        from ..probe import Probe

        # Get probe structs from all DAQ systems
        probestructs = []
        devs = self.daqsystem_load(name="(.*)")
        if devs is not None:
            if not isinstance(devs, list):
                devs = [devs]
            for dev in devs:
                if hasattr(dev, "getprobes"):
                    ps = dev.getprobes()
                    if ps:
                        probestructs.extend(ps)

        # Remove duplicates
        seen = set()
        unique_probes = []
        for ps in probestructs:
            key = (ps.get("name", ""), ps.get("reference", 0), ps.get("type", ""))
            if key not in seen:
                seen.add(key)
                unique_probes.append(ps)

        # Get existing probes from database
        existing_docs = self.database_search(Query("element.ndi_element_class").contains("probe"))

        # Convert existing docs to probe objects
        existing_probes = []
        for doc in existing_docs:
            try:
                obj = self._document_to_object(doc)
                if obj is not None:
                    existing_probes.append(obj)
            except Exception:
                pass

        # Create new probe objects for those not in database
        probes = []
        for ps in unique_probes:
            # Check if already in existing_probes
            found = False
            for ep in existing_probes:
                if (
                    ep.name == ps.get("name")
                    and ep.reference == ps.get("reference")
                    and ep.type == ps.get("type")
                ):
                    found = True
                    break
            if not found:
                probe = Probe(
                    session=self,
                    name=ps.get("name", ""),
                    reference=ps.get("reference", 0),
                    type=ps.get("type", ""),
                    subject_id=ps.get("subject_id", ""),
                )
                probes.append(probe)

        probes.extend(existing_probes)

        # Filter by class
        if classmatch is not None:
            from ..element import Element
            from ..probe import Probe

            _CLASS_LOOKUP = {
                "Probe": Probe,
                "Element": Element,
            }
            cls = _CLASS_LOOKUP.get(classmatch)
            if cls is None:
                raise ValueError(
                    f"Unknown classmatch '{classmatch}'. "
                    f"Valid values: {list(_CLASS_LOOKUP.keys())}"
                )
            probes = [p for p in probes if isinstance(p, cls)]

        # Filter by properties
        if kwargs:
            filtered = []
            for p in probes:
                include = True
                for prop, value in kwargs.items():
                    if hasattr(p, prop):
                        pval = getattr(p, prop)
                        if callable(pval):
                            pval = pval()
                        if isinstance(value, str):
                            include = include and (pval == value)
                        else:
                            include = include and (pval == value)
                    else:
                        include = False
                if include:
                    filtered.append(p)
            probes = filtered

        return probes

    def getelements(self, **kwargs) -> list[Any]:
        """
        Get all elements in the session.

        Args:
            **kwargs: Property filters (e.g., element.name, element.type)

        Returns:
            List of Element objects
        """
        q = Query("").isa("element")

        for field, value in kwargs.items():
            if "reference" in field:
                q = q & (Query(field) == value)
            else:
                q = q & (Query(field) == value)

        docs = self.database_search(q)

        elements = []
        for doc in docs:
            try:
                obj = self._document_to_object(doc)
                if obj is not None:
                    elements.append(obj)
            except Exception:
                pass

        return elements

    # =========================================================================
    # Document Service Methods
    # =========================================================================

    def newdocument(self, document_type: str = "base", **properties) -> Document:
        """
        Create a new document for this session.

        Args:
            document_type: Type of document to create
            **properties: Document properties

        Returns:
            New Document with session_id set
        """
        # Add session_id to properties
        properties["base.session_id"] = self.id()

        return Document(document_type, **properties)

    def searchquery(self) -> Query:
        """
        Create a query for documents in this session.

        Returns:
            Query matching this session's documents
        """
        return Query("base.session_id") == self.id()

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _docinput2docs(self, doc_input: str | Document | list[str | Document]) -> list[Document]:
        """Convert document IDs or Documents to Documents."""
        if not isinstance(doc_input, list):
            doc_input = [doc_input]

        doc_list = []
        for item in doc_input:
            if isinstance(item, Document):
                doc_list.append(item)
            elif isinstance(item, str):
                doc = self._database.read(item) if self._database else None
                if doc is not None:
                    doc_list.append(doc)

        return doc_list

    def _find_all_dependencies(self, document: Document) -> list[Document]:
        """Find all documents that depend on the given document."""
        dependents = []
        if self._database is None:
            return dependents

        q = Query("").depends_on("", document.id)
        results = self.database_search(q)

        for doc in results:
            dependents.append(doc)
            # Recursively find dependents of dependents
            dependents.extend(self._find_all_dependencies(doc))

        return dependents

    def _document_to_object(self, document: Document) -> Any:
        """
        Convert a document to its corresponding NDI object.

        Args:
            document: Document to convert

        Returns:
            The NDI object or None
        """
        # Check document type
        if document.doc_isa("daqsystem"):
            from ..daq.system import DAQSystem

            return DAQSystem(session=self, document=document)
        elif document.doc_isa("probe"):
            from ..probe import Probe

            return Probe(session=self, document=document)
        elif document.doc_isa("element"):
            from ..element import Element

            return Element(session=self, document=document)
        elif document.doc_isa("syncgraph"):
            return SyncGraph(session=self, document=document)

        return None

    # =========================================================================
    # Abstract Methods
    # =========================================================================

    @abstractmethod
    def getpath(self) -> Path | None:
        """
        Return the storage path of the session.

        Returns:
            Path to session storage, or None if not applicable
        """
        pass

    @abstractmethod
    def creator_args(self) -> list[Any]:
        """
        Return arguments needed to recreate the session.

        Returns:
            List of arguments for the constructor
        """
        pass

    # =========================================================================
    # Comparison Methods
    # =========================================================================

    def __eq__(self, other: Any) -> bool:
        """Check equality by identifier."""
        if not isinstance(other, Session):
            return False
        return self.id() == other.id()

    def __hash__(self) -> int:
        """Hash by identifier."""
        return hash(self._identifier)

    def __repr__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}(reference='{self._reference}', id='{self._identifier}')"
