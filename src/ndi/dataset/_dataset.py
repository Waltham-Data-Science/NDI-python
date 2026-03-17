"""
ndi.dataset - Multi-session dataset container.

A ndi_dataset manages multiple sessions, either linked (by reference) or
ingested (copied into the dataset's own database). Datasets have their
own session for storing dataset-level documents and metadata.

MATLAB equivalents:
    ndi.dataset      -> ndi_dataset (base class)
    ndi.dataset.dir  -> ndi_dataset_dir (directory-backed subclass)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..document import ndi_document
from ..query import ndi_query

logger = logging.getLogger(__name__)

# Map Python class names to their MATLAB-compatible equivalents so that
# artifacts written by Python can be opened by MATLAB (which uses ``feval``
# on the stored ``session_creator`` string).
_PYTHON_TO_MATLAB_CREATOR: dict[str, str] = {
    "ndi_session_dir": "ndi.session.dir",
}


def _matlab_creator_name(session: Any) -> str:
    """Return the MATLAB-compatible creator name for *session*."""
    py_name = type(session).__name__
    return _PYTHON_TO_MATLAB_CREATOR.get(py_name, py_name)


# ============================================================================
# ndi_dataset base class  (mirrors MATLAB ndi.dataset)
# ============================================================================


class ndi_dataset:
    """
    Multi-session dataset container (base class).

    MATLAB equivalent: ndi.dataset

    A ndi_dataset aggregates multiple sessions for cross-session analysis.
    Sessions can be:
    - **Linked**: Referenced by path/id, data stays in original location
    - **Ingested**: Documents copied into the dataset's own database

    The ``session`` attribute is set by the subclass (e.g. ndi_dataset_dir).

    Attributes:
        reference: Human-readable dataset reference name (from session)
    """

    def __init__(self) -> None:
        self._session: Any = None
        self._session_info: list[dict[str, Any]] = []
        self._session_array: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Properties delegated to the internal session
    # ------------------------------------------------------------------

    @property
    def reference(self) -> str:
        """Get the dataset reference name.

        MATLAB equivalent: ``ndi_dataset_obj.session.reference``
        """
        if self._session is None:
            return ""
        return self._session.reference

    @property
    def cloud_client(self) -> Any:
        """Get/set the cloud client for on-demand file fetching."""
        return self._session.cloud_client

    @cloud_client.setter
    def cloud_client(self, value: Any) -> None:
        self._session.cloud_client = value

    def id(self) -> str:
        """Get the unique dataset identifier.

        MATLAB equivalent: ``ndi_dataset_obj.session.id()``
        """
        return self._session.id()

    def getpath(self) -> Path:
        """Get the dataset directory path.

        MATLAB equivalent: ``ndi_dataset_obj.session.getpath()``
        """
        return self._session.getpath()

    # =========================================================================
    # ndi_session Management
    # =========================================================================

    def add_linked_session(self, session: Any) -> ndi_dataset:
        """
        Link an ndi.session to this dataset without ingesting.

        MATLAB equivalent: ``ndi.dataset/add_linked_session``

        Args:
            session: ndi_session object to link

        Returns:
            self for chaining

        Raises:
            ValueError: If the session is already part of this dataset
        """
        if not self._session_array:
            self.build_session_info()

        existing = self._find_session_in_info(session.id())
        if existing is not None:
            raise ValueError(
                f"ndi_session with id {session.id()} is already part of " f"dataset {self.id()}."
            )

        session_info_here = self._make_session_info(session, is_linked=True)
        new_doc = self.addSessionInfoToDataset(self, session_info_here)
        session_info_here["session_doc_in_dataset_id"] = new_doc.id

        self._session_info.append(session_info_here)
        self._session_array.append({"session_id": session.id(), "session": session})

        return self

    def add_ingested_session(self, session: Any) -> ndi_dataset:
        """
        Ingest a session into this dataset by copying documents.

        MATLAB equivalent: ``ndi.dataset/add_ingested_session``

        Args:
            session: ndi_session object to ingest

        Returns:
            self for chaining

        Raises:
            ValueError: If the session is already part of this dataset
            ValueError: If the session is not fully ingested
        """
        if not self._session_array:
            self.build_session_info()

        existing = self._find_session_in_info(session.id())
        if existing is not None:
            raise ValueError(
                f"ndi_session with id {session.id()} is already part of " f"dataset {self.id()}."
            )

        if hasattr(session, "is_fully_ingested") and not session.is_fully_ingested():
            raise ValueError(
                f"ndi_session with id {session.id()} and reference "
                f"{session.reference} is not yet fully ingested. "
                f"It must be fully ingested before it can be added "
                f"in ingested form to a dataset."
            )

        # Copy all documents from source session into the dataset's database.
        # We add directly via _database.add() because session.database_add()
        # enforces session_id == self._session.id(), but ingested docs retain
        # their *original* session_id so we can tell which session they came from.
        # Binary files are also copied from the source session.
        all_docs = session.database_search(ndi_query("").isa("base"))
        for doc in all_docs:
            try:
                self._session._database.add(doc)
                self._copy_binary_files(session, doc)
            except Exception as exc:
                logger.debug("Skipping document %s during ingestion: %s", doc.id, exc)

        session_info_here = self._make_session_info(session, is_linked=False)
        # For ingested sessions, clear the path arg (matches MATLAB kludge)
        session_info_here["session_creator_input2"] = ""

        new_doc = self.addSessionInfoToDataset(self, session_info_here)
        session_info_here["session_doc_in_dataset_id"] = new_doc.id

        self._session_info.append(session_info_here)
        self._session_array.append({"session_id": session.id(), "session": None})

        return self

    def unlink_session(
        self,
        session_id: str,
        are_you_sure: bool = False,
    ) -> ndi_dataset:
        """
        Unlink a linked session from this dataset.

        MATLAB equivalent: ``ndi.dataset/unlink_session``

        Args:
            session_id: ID of the session to unlink
            are_you_sure: Must be True to proceed

        Returns:
            self for chaining

        Raises:
            ValueError: If not confirmed, session not found, or session is ingested
        """
        if not are_you_sure:
            raise ValueError("Must set are_you_sure=True to unlink a session.")

        if not self._session_info:
            self.build_session_info()

        match = self._find_session_in_info(session_id)
        if match is None:
            raise ValueError(
                f"ndi_session with ID {session_id} not found in " f"dataset {self.id()}."
            )

        if not match.get("is_linked", False):
            raise ValueError(
                f"ndi_session with ID {session_id} is an INGESTED session, "
                f"not a linked session. Cannot unlink. Use "
                f"deleteIngestedSession() instead."
            )

        self.removeSessionInfoFromDataset(self, session_id)
        self.build_session_info()

        return self

    def open_session(self, session_id: str) -> Any | None:
        """
        Open a session by its ID.

        MATLAB equivalent: ``ndi.dataset/open_session``

        Args:
            session_id: ndi_session identifier

        Returns:
            ndi_session object, or None if not found
        """
        if not self._session_array:
            self.build_session_info()

        # Find in session_array
        match_idx = None
        for i, sa in enumerate(self._session_array):
            if sa["session_id"] == session_id:
                match_idx = i
                break

        if match_idx is None:
            return None

        # Already open?
        if self._session_array[match_idx]["session"] is not None:
            return self._session_array[match_idx]["session"]

        # Find matching info
        info_idx = None
        for i, si in enumerate(self._session_info):
            if si["session_id"] == session_id:
                info_idx = i
                break

        if info_idx is None:
            return None

        info = self._session_info[info_idx]
        is_linked = info.get("is_linked", False)
        if isinstance(is_linked, (int, float)):
            is_linked = bool(is_linked)

        # For ingested sessions, use the dataset path
        path_arg = info.get("session_creator_input2", "")
        if not is_linked:
            path_arg = str(self.getpath())

        session = self._recreate_session(info, path_arg, session_id)
        if session is not None:
            self._session_array[match_idx]["session"] = session

        return session

    def session_list(
        self,
    ) -> tuple[list[str], list[str], list[str], str]:
        """
        List all sessions in this dataset.

        MATLAB equivalent: ``ndi.dataset/session_list``

        Returns:
            A tuple of (ref_list, id_list, session_doc_ids, dataset_session_doc_id):
                - ref_list: List of session reference strings
                - id_list: List of session ID strings
                - session_doc_ids: List of document IDs for the
                  session_in_a_dataset documents
                - dataset_session_doc_id: ndi_document ID of the dataset's
                  own session document (empty string if not found)
        """
        if not self._session_info:
            self.build_session_info()

        ref_list = [si.get("session_reference", "") for si in self._session_info]
        id_list = [si.get("session_id", "") for si in self._session_info]
        session_doc_ids = [si.get("session_doc_in_dataset_id", "") for si in self._session_info]

        dataset_session_doc_id = ""
        q_ds = ndi_query("").isa("session") & (ndi_query("base.session_id") == self.id())
        ds_docs = self._session.database_search(q_ds)
        if len(ds_docs) == 1:
            dataset_session_doc_id = ds_docs[0].id
        elif len(ds_docs) > 1:
            raise ValueError("More than 1 session document for the dataset session found.")

        return ref_list, id_list, session_doc_ids, dataset_session_doc_id

    # =========================================================================
    # ndi_database Operations (delegated to internal session)
    # =========================================================================

    def database_add(self, document: ndi_document | list[ndi_document]) -> ndi_dataset:
        """Add document(s) to the dataset database.

        MATLAB equivalent: ``ndi.dataset/database_add``

        Routes documents to the appropriate session based on their
        ``base.session_id``. Documents whose session_id matches the
        dataset's id go through the session's database_add (which
        handles binary files etc.). Others are added directly.
        """
        if isinstance(document, list):
            docs = document
        else:
            docs = [document]

        from ..session import empty_id

        ds_id = self.id()
        for doc in docs:
            sid = doc.session_id
            if not sid or sid == empty_id() or sid == ds_id:
                # Belongs to the dataset's own session
                self._session.database_add(doc)
            else:
                # Belongs to another session - add directly to database
                self._session._database.add(doc)
        return self

    def database_rm(
        self,
        doc_or_id: ndi_document | str | list,
        error_if_not_found: bool = False,
    ) -> ndi_dataset:
        """Remove document(s) from the dataset database.

        MATLAB equivalent: ``ndi.dataset/database_rm``
        """
        if isinstance(doc_or_id, list):
            for item in doc_or_id:
                self._session.database_rm(item, error_if_not_found)
        else:
            self._session.database_rm(doc_or_id, error_if_not_found)
        return self

    def database_search(self, query: ndi_query) -> list[ndi_document]:
        """Search the dataset database and all linked sessions.

        MATLAB equivalent: ``ndi.dataset/database_search``

        Searches the session's database directly (not filtered by
        session_id), then also searches linked sessions.
        """
        if self._session._database is None:
            results: list[ndi_document] = []
        else:
            results = list(self._session._database.search(query))

        # Also search linked sessions
        self._open_linked_sessions()
        for i, si in enumerate(self._session_info):
            if si.get("is_linked", False):
                sa = self._session_array[i] if i < len(self._session_array) else None
                if sa and sa.get("session") is not None:
                    try:
                        linked_results = sa["session"].database_search(query)
                        results.extend(linked_results)
                    except Exception:
                        pass

        return results

    def database_openbinarydoc(
        self,
        doc_or_id: Any,
        filename: str,
    ) -> Any:
        """Open a binary document file."""
        return self._session.database_openbinarydoc(doc_or_id, filename)

    def database_existbinarydoc(
        self,
        doc_or_id: Any,
        filename: str,
    ) -> tuple[bool, Path | None]:
        """
        Check if a binary document file exists.

        MATLAB equivalent: ``ndi.dataset/database_existbinarydoc``

        Args:
            doc_or_id: ndi_document or document ID.
            filename: Name of the binary file.

        Returns:
            Tuple of (exists, file_path).
        """
        return self._session.database_existbinarydoc(doc_or_id, filename)

    def database_closebinarydoc(self, fid: Any) -> None:
        """Close a binary document file."""
        self._session.database_closebinarydoc(fid)

    # =========================================================================
    # Ingested ndi_session Management
    # =========================================================================

    def deleteIngestedSession(
        self,
        session_id: str,
        are_you_sure: bool = False,
    ) -> ndi_dataset:
        """
        Delete an ingested session and all its documents.

        MATLAB equivalent: ``ndi.dataset/deleteIngestedSession``
        """
        if not are_you_sure:
            raise ValueError("Must set are_you_sure=True to delete session data")

        if not self._session_info:
            self.build_session_info()

        match = self._find_session_in_info(session_id)
        if match is None:
            raise ValueError(f"ndi_session {session_id} not found in dataset.")

        if match.get("is_linked", False):
            raise ValueError(
                f"ndi_session {session_id} is a linked session, not an "
                f"ingested one. Use unlink_session() instead."
            )

        # Remove all documents with base.session_id == session_id
        q_docs = ndi_query("base.session_id") == session_id
        docs_to_delete = self.database_search(q_docs)

        # Remove the session_in_a_dataset doc
        doc_id = match.get("session_doc_in_dataset_id", "")
        if doc_id:
            self._session.database_rm(doc_id)

        # Remove other docs
        for doc in docs_to_delete:
            try:
                self._session.database_rm(doc)
            except Exception as exc:
                logger.warning("Failed to remove document %s: %s", doc.id, exc)

        self.build_session_info()

        return self

    def document_session(self, document: ndi_document) -> Any | None:
        """Find which session a document belongs to.

        MATLAB equivalent: ``ndi.dataset/document_session``
        """
        session_id = document.session_id
        if session_id:
            return self.open_session(session_id)
        return None

    # =========================================================================
    # ndi_session info management (mirrors MATLAB build_session_info)
    # =========================================================================

    def build_session_info(self) -> None:
        """Build the session info data structures.

        MATLAB equivalent: ``ndi.dataset/build_session_info`` (protected)

        Reads ``session_in_a_dataset`` documents from the database and
        populates ``_session_info`` and ``_session_array``.
        """
        # Check for legacy dataset_session_info docs and repair
        q_legacy = ndi_query("").isa("dataset_session_info") & (
            ndi_query("base.session_id") == self.id()
        )
        legacy_docs = self._session.database_search(q_legacy)
        if legacy_docs:
            self.repairDatasetSessionInfo(self, legacy_docs)

        # Find session_in_a_dataset docs belonging to this dataset
        q = ndi_query("").isa("session_in_a_dataset") & (ndi_query("base.session_id") == self.id())
        info_docs = self._session.database_search(q)

        self._session_info = []
        for doc in info_docs:
            props = doc.document_properties.get("session_in_a_dataset", {})
            info = dict(props)
            info["session_doc_in_dataset_id"] = doc.id
            self._session_info.append(info)

        # Build session_array (sessions opened lazily)
        self._session_array = []
        for si in self._session_info:
            self._session_array.append(
                {
                    "session_id": si.get("session_id", ""),
                    "session": None,
                }
            )

    # =========================================================================
    # Static methods (mirrors MATLAB ndi.dataset static methods)
    # =========================================================================

    @staticmethod
    def repairDatasetSessionInfo(
        dataset_obj: ndi_dataset,
        docs: list[ndi_document],
    ) -> list[ndi_document]:
        """Repair legacy dataset_session_info into session_in_a_dataset docs.

        MATLAB equivalent: ``ndi.dataset.repairDatasetSessionInfo``
        """
        new_docs: list[ndi_document] = []
        if not docs:
            return new_docs

        if len(docs) > 1:
            raise ValueError(
                f"Found too many dataset session info documents ({len(docs)}) "
                f"for dataset {dataset_obj.id()}."
            )

        doc = docs[0]
        current_dataset_id = doc.document_properties.get("base", {}).get("session_id", "")
        dsi = doc.document_properties.get("dataset_session_info", {})
        info_list = dsi.get("dataset_session_info", [])
        if isinstance(info_list, dict):
            info_list = [info_list]

        fields = [
            "session_id",
            "session_reference",
            "is_linked",
            "session_creator",
            "session_creator_input1",
            "session_creator_input2",
            "session_creator_input3",
            "session_creator_input4",
            "session_creator_input5",
            "session_creator_input6",
        ]

        for s in info_list:
            props = {}
            for f in fields:
                val = s.get(f, "")
                if f == "is_linked" and val == "":
                    val = False
                props[f"session_in_a_dataset.{f}"] = val

            new_doc = ndi_document("session_in_a_dataset", **props)
            new_doc = new_doc.set_session_id(current_dataset_id)
            new_docs.append(new_doc)

        # Apply: add new docs, remove old
        if new_docs:
            for nd in new_docs:
                dataset_obj._session.database_add(nd)
        dataset_obj._session.database_rm(doc)

        return new_docs

    @staticmethod
    def addSessionInfoToDataset(
        dataset_obj: ndi_dataset,
        session_info: dict[str, Any],
    ) -> ndi_document:
        """Add a session_in_a_dataset document to the dataset.

        MATLAB equivalent: ``ndi.dataset.addSessionInfoToDataset``
        """
        props = {}
        for key, val in session_info.items():
            if key != "session_doc_in_dataset_id":
                props[f"session_in_a_dataset.{key}"] = val

        new_doc = ndi_document("session_in_a_dataset", **props)
        new_doc = new_doc.set_session_id(dataset_obj.id())
        dataset_obj._session.database_add(new_doc)
        return new_doc

    @staticmethod
    def removeSessionInfoFromDataset(
        dataset_obj: ndi_dataset,
        session_id: str,
    ) -> None:
        """Remove session_in_a_dataset document(s) for a given session ID.

        MATLAB equivalent: ``ndi.dataset.removeSessionInfoFromDataset``
        """
        q = (ndi_query("session_in_a_dataset.session_id") == session_id) & (
            ndi_query("base.session_id") == dataset_obj.id()
        )
        docs = dataset_obj._session.database_search(q)
        for doc in docs:
            dataset_obj._session.database_rm(doc)

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _find_session_in_info(self, session_id: str) -> dict[str, Any] | None:
        """Find session info entry by session_id."""
        for si in self._session_info:
            if si.get("session_id", "") == session_id:
                return si
        return None

    @staticmethod
    def _make_session_info(session: Any, is_linked: bool) -> dict[str, Any]:
        """Build a session_info dict from a session object."""
        creator_args = session.creator_args() if hasattr(session, "creator_args") else []
        info: dict[str, Any] = {
            "session_id": session.id(),
            "session_reference": session.reference,
            "is_linked": is_linked,
            "session_creator": _matlab_creator_name(session),
        }
        for i in range(1, 7):
            key = f"session_creator_input{i}"
            info[key] = str(creator_args[i - 1]) if i <= len(creator_args) else ""
        return info

    def _recreate_session(
        self,
        info: dict[str, Any],
        path_arg: str,
        session_id: str,
    ) -> Any | None:
        """Recreate a session from stored creator args."""
        creator = info.get("session_creator", "")

        if creator == "ndi_session_dir" or creator == "ndi.session.dir":
            from ..session.dir import ndi_session_dir

            ref = info.get("session_creator_input1", "")
            if ref and path_arg:
                try:
                    return ndi_session_dir(ref, path_arg, session_id=session_id)
                except Exception:
                    pass
            elif path_arg:
                try:
                    return ndi_session_dir(path_arg)
                except Exception:
                    pass

        return None

    def _copy_binary_files(self, source_session: Any, doc: ndi_document) -> None:
        """Copy binary file attachments from a source session to this dataset."""
        import shutil

        if self._session._database is None:
            return
        props = doc.document_properties
        files = props.get("files", {})
        if not isinstance(files, dict):
            return
        for fi in files.get("file_info", []):
            name = fi.get("name", "")
            if not name:
                continue
            if hasattr(source_session, "_database") and source_session._database is not None:
                src_path = source_session._database.get_binary_path(doc, name)
                if src_path.exists():
                    dest_path = self._session._database.get_binary_path(doc, name)
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src_path), str(dest_path))
                    continue
            for loc in fi.get("locations", []):
                source = loc.get("location", "")
                if source:
                    src_path = Path(source)
                    if src_path.exists():
                        dest_path = self._session._database.get_binary_path(doc, name)
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(str(src_path), str(dest_path))
                        break

    def _open_linked_sessions(self) -> None:
        """Ensure all linked sessions are open and cached.

        MATLAB equivalent: ``ndi.dataset/open_linked_sessions`` (protected)
        """
        if not self._session_info:
            self.build_session_info()

        for i, si in enumerate(self._session_info):
            is_linked = si.get("is_linked", False)
            if isinstance(is_linked, (int, float)):
                is_linked = bool(is_linked)
            if is_linked:
                if i < len(self._session_array) and self._session_array[i]["session"] is None:
                    self.open_session(si["session_id"])

    # =========================================================================
    # Representation
    # =========================================================================

    def __repr__(self) -> str:
        """String representation."""
        refs, _ids, _doc_ids, _ds_doc_id = self.session_list()
        return f"ndi_dataset('{self.reference}', sessions={len(refs)})"


# ============================================================================
# ndi_dataset_dir  (mirrors MATLAB ndi.dataset.dir)
# ============================================================================


class ndi_dataset_dir(ndi_dataset):
    """
    Directory-backed dataset.

    MATLAB equivalent: ndi.dataset.dir

    Creates or opens a dataset at a local directory path. The session
    database lives in ``<path>/.ndi/``.

    The constructor supports three calling conventions (mirroring MATLAB):

    1. ``ndi_dataset_dir(path)``             — open existing dataset
    2. ``ndi_dataset_dir(reference, path)``  — create / open with reference
    3. ``ndi_dataset_dir(reference, path, documents=docs)`` — create from
       pre-loaded documents (used by ``downloadDataset``)

    Example:
        >>> dataset = ndi_dataset_dir('/path/to/dataset')
        >>> dataset = ndi_dataset_dir('my_experiment', '/path/to/dataset')
    """

    def __init__(
        self,
        reference_or_path: str | Path,
        path_or_ref: str | Path | None = None,
        *,
        reference: str | None = None,
        documents: list[ndi_document] | None = None,
    ):
        """
        Create or open a directory-based ndi_dataset.

        Supports multiple calling conventions:

        - ``ndi_dataset_dir(path)``                      — open existing
        - ``ndi_dataset_dir(reference, path)``            — MATLAB style
        - ``ndi_dataset_dir(path, reference='name')``     — keyword style

        Args:
            reference_or_path: Either the dataset reference or path
            path_or_ref: Optional second positional arg (path or reference)
            reference: Keyword-only reference override
            documents: Optional list of pre-loaded ndi_document objects.
                When provided, documents are bulk-inserted and the
                session is configured from them (hidden argument,
                used by downloadDataset).
        """
        from ..session.dir import ndi_session_dir

        super().__init__()

        # Determine reference and path from arguments.
        # MATLAB convention: dir(reference, path_name)
        # Old Python convention: ndi_dataset(path, reference)
        # We support both by detecting whether the second arg is a path.
        if path_or_ref is None:
            # 1-arg form: ndi_dataset_dir(path)
            self._path = Path(reference_or_path)
            ref = reference or ""
        elif isinstance(path_or_ref, Path) or (
            isinstance(path_or_ref, str) and ("/" in path_or_ref or "\\" in path_or_ref)
        ):
            # MATLAB-style: ndi_dataset_dir(reference, path)
            ref = str(reference_or_path) if reference_or_path else ""
            self._path = Path(path_or_ref)
        else:
            # Old Python-style: ndi_dataset_dir(path, "reference_string")
            self._path = Path(reference_or_path)
            ref = str(path_or_ref)

        # Keyword reference overrides positional
        if reference is not None:
            ref = reference

        self._path.mkdir(parents=True, exist_ok=True)

        if documents is not None and documents:
            # Hidden 3rd argument: create from pre-loaded documents.
            # Mirrors MATLAB ndi.dataset.dir(reference, path_name, docs).
            dataset_session_id = self._dataset_session_id_from_docs(documents)
            # Create session with forced ID so docs can be inserted
            self._session = ndi_session_dir(
                ref or "temp",
                self._path,
                session_id=dataset_session_id,
            )
            # Bulk-add all documents to the database
            for doc in documents:
                try:
                    self._session._database.add(doc)
                except Exception:
                    pass
            # Re-create session without forced ID (reads from database)
            self._session = ndi_session_dir(ref or "temp", self._path)
        elif path_or_ref is None and not ref:
            # 1-arg form: try opening existing, or create with dir name as reference
            try:
                self._session = ndi_session_dir(self._path)
            except ValueError:
                self._session = ndi_session_dir(self._path.name, self._path)
        else:
            # 2-arg form
            self._session = ndi_session_dir(ref or self._path.name, self._path)

        # ndi_session discovery: find the correct session ID and reference
        # from documents in the database. Mirrors the MATLAB
        # ndi.dataset.dir constructor logic.
        self._discover_correct_session(ref)

        # Build session info from session_in_a_dataset documents
        # Also discovers sessions from session-type documents (for
        # datasets that don't yet have session_in_a_dataset tracking).
        self._ensure_session_tracking()

    def _discover_correct_session(self, initial_reference: str) -> None:
        """Find the correct session ID and reference from database documents.

        Mirrors the MATLAB ndi.dataset.dir constructor logic that searches
        for dataset_session_info → session_in_a_dataset → session documents
        to determine the correct session ID and reference.
        """
        from ..session.dir import ndi_session_dir

        correct_session_id = ""

        # 1. Check for legacy dataset_session_info docs
        dsi_docs = self.database_search(ndi_query("").isa("dataset_session_info"))
        if dsi_docs:
            correct_session_id = (
                dsi_docs[0].document_properties.get("base", {}).get("session_id", "")
            )
        else:
            # 2. Check for session_in_a_dataset docs
            sia_docs = self.database_search(ndi_query("").isa("session_in_a_dataset"))
            if sia_docs:
                correct_session_id = (
                    sia_docs[0].document_properties.get("base", {}).get("session_id", "")
                )
            else:
                # 3. Check for a single session doc
                session_docs = self.database_search(ndi_query("").isa("session"))
                if len(session_docs) == 1:
                    correct_session_id = (
                        session_docs[0].document_properties.get("base", {}).get("session_id", "")
                    )

        if correct_session_id:
            # Find the session document with this ID
            q = ndi_query("").isa("session") & (ndi_query("base.session_id") == correct_session_id)
            candidate_docs = self.database_search(q)
            if len(candidate_docs) == 1:
                ref = candidate_docs[0].document_properties.get("session", {}).get("reference", "")
                sid = candidate_docs[0].document_properties.get("base", {}).get("session_id", "")
                # Re-create session with the correct reference and ID
                self._session = ndi_session_dir(ref, self._path, session_id=sid)

        # Repair legacy dataset_session_info if found
        if dsi_docs:
            dsi_docs2 = self.database_search(ndi_query("").isa("dataset_session_info"))
            if dsi_docs2:
                self.repairDatasetSessionInfo(self, dsi_docs2)

    def _ensure_session_tracking(self) -> None:
        """Ensure all sessions in the database have session_in_a_dataset tracking.

        For datasets that have session documents but no session_in_a_dataset
        tracking records (e.g. freshly created datasets or datasets where
        sessions were added outside the normal flow), this method creates
        the missing tracking records.
        """
        if self._session._database is None:
            return

        # Find already-tracked session IDs
        q_tracked = ndi_query("").isa("session_in_a_dataset") & (
            ndi_query("base.session_id") == self.id()
        )
        tracked_docs = self._session.database_search(q_tracked)
        tracked_ids: set[str] = set()
        for doc in tracked_docs:
            props = doc.document_properties.get("session_in_a_dataset", {})
            sid = props.get("session_id", "")
            if sid:
                tracked_ids.add(sid)

        # Find session documents in the database
        q_session = ndi_query("").isa("session")
        session_docs = list(self._session._database.search(q_session))

        ds_session_id = self._session.id()

        for sdoc in session_docs:
            props = sdoc.document_properties
            sid = props.get("base", {}).get("session_id", "")
            if not sid or sid == ds_session_id or sid in tracked_ids:
                continue
            ref = props.get("session", {}).get("reference", "")
            tracking_doc = ndi_document(
                "session_in_a_dataset",
                **{
                    "session_in_a_dataset.session_id": sid,
                    "session_in_a_dataset.session_reference": ref,
                    "session_in_a_dataset.is_linked": False,
                    "session_in_a_dataset.session_creator": "ndi_session_dir",
                },
            )
            tracking_doc = tracking_doc.set_session_id(ds_session_id)
            try:
                self._session.database_add(tracking_doc)
                tracked_ids.add(sid)
            except Exception:
                logger.debug("Could not register session %s: skipping", sid)

    @staticmethod
    def dataset_erase(ndi_dataset_dir_obj: ndi_dataset_dir, areyousure: str = "no") -> None:
        """
        Delete the entire dataset database folder.

        MATLAB equivalent: ``ndi.dataset.dir.dataset_erase``

        Use with care. If *areyousure* is ``'yes'`` the ``.ndi``
        directory inside the dataset path will be permanently removed.

        Args:
            ndi_dataset_dir_obj: The ndi_dataset_dir instance to erase.
            areyousure: Must be ``'yes'`` to proceed.
        """
        import shutil

        if areyousure.lower() == "yes":
            ndi_dir = ndi_dataset_dir_obj.getpath() / ".ndi"
            if ndi_dir.exists():
                shutil.rmtree(ndi_dir)
        else:
            logger.info(
                "Not erasing dataset directory folder because "
                "user did not indicate they are sure."
            )

    @staticmethod
    def _dataset_session_id_from_docs(documents: list[ndi_document]) -> str:
        """Extract the dataset session ID from a list of documents.

        MATLAB equivalent: ``ndi.cloud.sync.internal.datasetSessionIdFromDocs``

        Looks for ``session_in_a_dataset`` or ``dataset_session_info``
        documents first.  Falls back to finding the most common session_id.
        """
        # Try session_in_a_dataset docs first
        for doc in documents:
            props = doc.document_properties if hasattr(doc, "document_properties") else {}
            if not isinstance(props, dict):
                continue
            doc_class = props.get("document_class", {})
            class_name = ""
            if isinstance(doc_class, dict):
                class_name = doc_class.get("class_name", "")
            elif isinstance(doc_class, list) and doc_class:
                class_name = doc_class[-1].get("class_name", "")
            if class_name in ("session_in_a_dataset", "dataset_session_info"):
                sid = props.get("base", {}).get("session_id", "")
                if sid:
                    return sid

        # Fallback: most common session_id
        from collections import Counter

        session_ids: list[str] = []
        for doc in documents:
            props = doc.document_properties if hasattr(doc, "document_properties") else {}
            if isinstance(props, dict):
                sid = props.get("base", {}).get("session_id", "")
                if sid:
                    session_ids.append(sid)

        if session_ids:
            counts = Counter(session_ids)
            return counts.most_common(1)[0][0]

        return ""

    def __repr__(self) -> str:
        """String representation."""
        refs, _ids, _doc_ids, _ds_doc_id = self.session_list()
        return f"ndi_dataset('{self.reference}', sessions={len(refs)})"
