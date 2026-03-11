"""
ndi.database.fun - Database utility functions for NDI.

MATLAB equivalents: +ndi/+database/+fun/*.m

Provides dependency traversal, batch retrieval, graph construction,
and document analysis utilities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


def findallantecedents(
    session_or_dataset: Any,
    *documents: Any,
    visited: set[str] | None = None,
) -> list[Any]:
    """Find all documents that the given documents depend on (upstream).

    MATLAB equivalent: ndi.database.fun.findallantecedents

    Recursively walks the depends_on chain upwards.

    Args:
        session_or_dataset: An ndi.session or ndi.dataset with database_search.
        *documents: One or more ndi.Document objects.
        visited: Set of already-visited IDs (for recursion).

    Returns:
        List of all antecedent Document objects.
    """
    from .query import Query

    if visited is None:
        visited = set()

    antecedents: list[Any] = []
    dep_ids: list[str] = []

    for doc in documents:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue

        doc_id = props.get("base", {}).get("id", "")
        if doc_id in visited:
            continue
        visited.add(doc_id)

        # Extract depends_on IDs
        for dep in props.get("depends_on", []):
            val = dep.get("value", "")
            if val and val not in visited:
                dep_ids.append(val)

    if not dep_ids:
        return antecedents

    # Batch query for all dependency IDs
    q = Query("base.id") == dep_ids[0]
    for did in dep_ids[1:]:
        q = q | (Query("base.id") == did)

    try:
        found = session_or_dataset.database_search(q)
    except Exception:
        try:
            found = session_or_dataset.session.database_search(q)
        except Exception:
            found = []

    antecedents.extend(found)

    # Recurse
    if found:
        deeper = findallantecedents(session_or_dataset, *found, visited=visited)
        antecedents.extend(deeper)

    return antecedents


def findalldependencies(
    session_or_dataset: Any,
    *documents: Any,
    visited: set[str] | None = None,
) -> list[Any]:
    """Find all documents that depend on the given documents (downstream).

    MATLAB equivalent: ndi.database.fun.findalldependencies

    Recursively walks the dependency chain downwards.
    """
    from .query import Query

    if visited is None:
        visited = set()

    dependents: list[Any] = []

    for doc in documents:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue

        doc_id = props.get("base", {}).get("id", "")
        if doc_id in visited or not doc_id:
            continue
        visited.add(doc_id)

        # Find documents whose depends_on references this doc
        q = Query("").depends_on("*", doc_id)

        try:
            found = session_or_dataset.database_search(q)
        except Exception:
            try:
                found = session_or_dataset.session.database_search(q)
            except Exception:
                found = []

        new_found = []
        for f in found:
            fp = f.document_properties if hasattr(f, "document_properties") else f
            fid = fp.get("base", {}).get("id", "") if isinstance(fp, dict) else ""
            if fid not in visited:
                new_found.append(f)

        dependents.extend(new_found)

        # Recurse
        if new_found:
            deeper = findalldependencies(session_or_dataset, *new_found, visited=visited)
            dependents.extend(deeper)

    return dependents


def docs_from_ids(
    session_or_dataset: Any,
    document_ids: list[str],
) -> list[Any | None]:
    """Retrieve documents by IDs in a single batch query.

    MATLAB equivalent: ndi.database.fun.docs_from_ids

    Args:
        session_or_dataset: Database-containing object.
        document_ids: List of document IDs.

    Returns:
        List aligned with document_ids, each element the matching
        Document or None if not found.
    """
    from .query import Query

    if not document_ids:
        return []

    # Build OR query for all IDs
    q = Query("base.id") == document_ids[0]
    for did in document_ids[1:]:
        q = q | (Query("base.id") == did)

    try:
        found = session_or_dataset.database_search(q)
    except Exception:
        try:
            found = session_or_dataset.session.database_search(q)
        except Exception:
            found = []

    # Build lookup
    found_map: dict[str, Any] = {}
    for doc in found:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if isinstance(props, dict):
            did = props.get("base", {}).get("id", "")
            if did:
                found_map[did] = doc

    return [found_map.get(did) for did in document_ids]


def docs2graph(
    documents: list[Any],
) -> tuple[dict[str, list[str]], list[str]]:
    """Build a dependency graph from document objects.

    MATLAB equivalent: ndi.database.fun.docs2graph

    Args:
        documents: List of ndi.Document objects.

    Returns:
        Tuple of (adjacency_dict, node_ids) where adjacency_dict maps
        each node ID to its list of dependency IDs (edges).
    """
    # Collect all node IDs
    nodes: list[str] = []
    for doc in documents:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if isinstance(props, dict):
            did = props.get("base", {}).get("id", "")
            if did:
                nodes.append(did)

    node_set = set(nodes)
    adjacency: dict[str, list[str]] = {n: [] for n in nodes}

    for doc in documents:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue

        doc_id = props.get("base", {}).get("id", "")
        if not doc_id:
            continue

        for dep in props.get("depends_on", []):
            dep_id = dep.get("value", "")
            if dep_id and dep_id in node_set:
                adjacency[doc_id].append(dep_id)

    return adjacency, nodes


def find_ingested_docs(session_or_dataset: Any) -> list[Any]:
    """Find all documents corresponding to ingested data.

    MATLAB equivalent: ndi.database.fun.find_ingested_docs
    """
    from .query import Query

    q = (
        Query("").isa("daqreader_mfdaq_epochdata_ingested")
        | Query("").isa("daqmetadatareader_epochdata_ingested")
        | Query("").isa("epochfiles_ingested")
    )

    try:
        return session_or_dataset.database_search(q)
    except Exception:
        try:
            return session_or_dataset.session.database_search(q)
        except Exception:
            return []


def finddocs_element_epoch_type(
    session_or_dataset: Any,
    element_id: str,
    epoch_id: str,
    document_type: str,
) -> list[Any]:
    """Find documents matching an element, epoch, and document type.

    MATLAB equivalent: ndi.database.fun.finddocs_elementEpochType

    Builds a compound query combining document type (isa),
    element_id dependency, and epoch_id exact match.

    Args:
        session_or_dataset: Database-containing object.
        element_id: The element document ID.
        epoch_id: The epoch ID string.
        document_type: The document type name (e.g. ``'spectrogram'``).

    Returns:
        List of matching Documents.
    """
    from .query import Query

    q1 = Query("").isa(document_type)
    q2 = Query("").depends_on("element_id", element_id)
    q3 = Query("epochid") == epoch_id
    q = q1 & q2 & q3

    try:
        return session_or_dataset.database_search(q)
    except Exception:
        try:
            return session_or_dataset.session.database_search(q)
        except Exception:
            return []


def ndi_document2ndi_object(
    ndi_document_obj: Any,
    ndi_session_obj: Any,
) -> Any:
    """Convert an NDI document into its corresponding Python object.

    MATLAB equivalent: ndi.database.fun.ndi_document2ndi_object

    Inspects the document's class hierarchy and instantiates the
    appropriate Python object (e.g. Element, Probe, Subject).

    Args:
        ndi_document_obj: An ndi.Document or a document ID string.
        ndi_session_obj: The session object for database lookups.

    Returns:
        The reconstructed NDI object, or None if reconstruction fails.
    """
    from .query import Query

    # If given an ID string, look up the document
    if isinstance(ndi_document_obj, str):
        results = ndi_session_obj.database_search(Query("base.id") == ndi_document_obj)
        if not results:
            return None
        ndi_document_obj = results[0]

    props = ndi_document_obj.document_properties
    if not isinstance(props, dict):
        return None

    # Get class info
    doc_class = props.get("document_class", {})
    class_name = doc_class.get("class_name", "")

    # Try to reconstruct based on class_name
    class_map = _get_class_map()
    if class_name in class_map:
        constructor = class_map[class_name]
        try:
            return constructor(ndi_document_obj, ndi_session_obj)
        except Exception:
            pass

    return None


def _get_class_map() -> dict[str, Any]:
    """Build mapping of document class names to constructor functions."""
    constructors: dict[str, Any] = {}

    def _make_element(doc: Any, session: Any) -> Any:
        from .element import Element

        p = doc.document_properties
        el = p.get("element", {})
        return Element(
            session=session,
            name=el.get("name", ""),
            reference=el.get("reference", 0),
            type=el.get("type", ""),
        )

    def _make_subject(doc: Any, session: Any) -> Any:
        from .subject import Subject

        p = doc.document_properties
        subj = p.get("subject", {})
        return Subject(
            session=session,
            local_identifier=subj.get("local_identifier", ""),
            description=subj.get("description", ""),
        )

    constructors["element"] = _make_element
    constructors["subject"] = _make_subject
    return constructors


def copy_session_to_dataset(
    ndi_session_obj: Any,
    ndi_dataset_obj: Any,
) -> tuple[bool, str]:
    """Copy database documents from a session to a dataset.

    MATLAB equivalent: ndi.database.fun.copy_session_to_dataset

    Checks for duplicate sessions, extracts all documents, assigns
    session IDs, and adds them to the dataset's database.

    Args:
        ndi_session_obj: Source session object.
        ndi_dataset_obj: Destination dataset object.

    Returns:
        Tuple ``(success, errmsg)`` where success is True/False.
    """
    from .query import Query

    # Check for already-copied sessions
    try:
        refs, session_ids = ndi_dataset_obj.session_list()
        session_id = ndi_session_obj.id()
        if session_id in session_ids:
            return (
                False,
                f"Session with ID {session_id} is already part of " f"the dataset.",
            )
    except Exception:
        pass

    # Get all documents from source session
    try:
        all_docs = ndi_session_obj.database_search(Query("").isa("base"))
    except Exception:
        return False, "Failed to search source session database."

    # Fix empty session_ids
    session_id = ndi_session_obj.id()
    fixed_count = 0
    for i, doc in enumerate(all_docs):
        p = doc.document_properties
        sid = p.get("base", {}).get("session_id", "")
        if not sid:
            all_docs[i] = doc.set_session_id(session_id)
            fixed_count += 1

    if fixed_count > 0:
        import warnings

        warnings.warn(
            f"Found {fixed_count} documents with empty session_id. "
            f"Setting them to match the current session.",
            stacklevel=2,
        )

    # Add documents to the dataset
    for doc in all_docs:
        try:
            ndi_dataset_obj.database_add(doc)
        except Exception:
            pass

    return True, ""


def finddocs_missing_dependencies(
    session_or_dataset: Any,
    *dep_names: str,
) -> list[Any]:
    """Find documents with unresolved dependency references.

    MATLAB equivalent: ndi.database.fun.finddocs_missing_dependencies
    """
    from .query import Query

    # Find all docs with depends_on
    try:
        all_docs = session_or_dataset.database_search(Query("").isa("base"))
    except Exception:
        try:
            all_docs = session_or_dataset.session.database_search(Query("").isa("base"))
        except Exception:
            return []

    # Build cache of known IDs
    known_ids: set[str] = set()
    for doc in all_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if isinstance(props, dict):
            did = props.get("base", {}).get("id", "")
            if did:
                known_ids.add(did)

    missing: list[Any] = []
    for doc in all_docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue
        for dep in props.get("depends_on", []):
            dep_name = dep.get("name", "")
            dep_val = dep.get("value", "")
            if not dep_val:
                continue
            if dep_names and dep_name not in dep_names:
                continue
            if dep_val not in known_ids:
                missing.append(doc)
                break

    return missing


# =========================================================================
# Presentation time binary I/O
# =========================================================================


def write_presentation_time_structure(
    filename: str,
    presentation_time: list[dict[str, Any]],
) -> None:
    """Write presentation time structure to a binary file.

    MATLAB equivalent: ndi.database.fun.write_presentation_time_structure

    Binary format:
        - 512-byte header: ASCII header line, uint64 entry count, zero-padding
        - Per entry: clocktype string + newline, 4 float64 timing values,
          uint32 event count, then Nx2 float64 stimevents matrix

    Args:
        filename: Output file path.
        presentation_time: List of dicts with keys ``clocktype``,
            ``stimopen``, ``onset``, ``offset``, ``stimclose``,
            ``stimevents`` (Nx2 array).
    """
    import struct

    import numpy as np

    with open(filename, "wb") as f:
        # Header
        header_line = b"presentation_time structure\n"
        f.write(header_line)
        num_entries = len(presentation_time)
        f.write(struct.pack("<Q", num_entries))
        # Zero-pad to 512 bytes
        current = f.tell()
        f.write(b"\x00" * (512 - current))

        for entry in presentation_time:
            # Clocktype as string + newline
            ct = entry.get("clocktype", "")
            f.write(f"{ct}\n".encode("ascii"))
            # Timing values
            f.write(struct.pack("<d", float(entry.get("stimopen", 0))))
            f.write(struct.pack("<d", float(entry.get("onset", 0))))
            f.write(struct.pack("<d", float(entry.get("offset", 0))))
            f.write(struct.pack("<d", float(entry.get("stimclose", 0))))
            # Stimevents
            stimevents = np.asarray(
                entry.get("stimevents", []),
                dtype="<f8",
            )
            if stimevents.ndim == 1:
                stimevents = (
                    stimevents.reshape(-1, 2) if stimevents.size else np.empty((0, 2), dtype="<f8")
                )
            num_events = stimevents.shape[0]
            f.write(struct.pack("<I", num_events))
            # Write column-major (transposed), matching MATLAB's reshape
            if num_events > 0:
                f.write(stimevents.T.astype("<f8").tobytes())


def read_presentation_time_structure(
    filename: str,
    n0: int | None = None,
    n1: int | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Read presentation time structure from a binary file.

    MATLAB equivalent: ndi.database.fun.read_presentation_time_structure

    Args:
        filename: Binary file path.
        n0: Start index (0-based, inclusive). Default: 0.
        n1: End index (0-based, inclusive). Default: last entry.

    Returns:
        Tuple ``(header, entries)`` where header is the description
        string and entries is a list of dicts.
    """
    import struct

    import numpy as np

    with open(filename, "rb") as f:
        # Read header line
        header = b""
        while True:
            c = f.read(1)
            if c == b"\n" or c == b"":
                break
            header += c
        header_str = header.decode("ascii")

        # Read number of entries
        num_entries = struct.unpack("<Q", f.read(8))[0]

        # Seek to 512
        f.seek(512)

        if n0 is None:
            n0 = 0
        if n1 is None:
            n1 = num_entries - 1
        n1 = min(n1, num_entries - 1)

        entries: list[dict[str, Any]] = []

        # Read all entries up to n1
        for _i in range(n1 + 1):
            # Clocktype
            ct = b""
            while True:
                c = f.read(1)
                if c == b"\n" or c == b"":
                    break
                ct += c
            clocktype = ct.decode("ascii")

            stimopen = struct.unpack("<d", f.read(8))[0]
            onset = struct.unpack("<d", f.read(8))[0]
            offset = struct.unpack("<d", f.read(8))[0]
            stimclose = struct.unpack("<d", f.read(8))[0]

            num_events = struct.unpack("<I", f.read(4))[0]
            if num_events > 0:
                raw = np.frombuffer(f.read(num_events * 2 * 8), dtype="<f8")
                stimevents = raw.reshape(2, num_events).T.copy()
            else:
                stimevents = np.empty((0, 2), dtype="float64")

            entries.append(
                {
                    "clocktype": clocktype,
                    "stimopen": stimopen,
                    "onset": onset,
                    "offset": offset,
                    "stimclose": stimclose,
                    "stimevents": stimevents,
                }
            )

        # Slice to [n0, n1]
        entries = entries[n0:]

    return header_str, entries


# =========================================================================
# Database export / extraction
# =========================================================================


def database_to_json(
    session: Any,
    output_path: str,
) -> int:
    """Export all session documents to JSON files in a directory.

    MATLAB equivalent: ndi.database.fun.database2json

    Each document is written as ``{doc_id}.json``.

    Args:
        session: An NDI session instance.
        output_path: Directory path to write JSON files.

    Returns:
        Number of documents exported.
    """
    import json
    from pathlib import Path

    from .query import Query

    out = Path(output_path)
    out.mkdir(parents=True, exist_ok=True)

    docs = session.database_search(Query("").isa("base"))

    count = 0
    for doc in docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue
        doc_id = props.get("base", {}).get("id", f"doc_{count}")
        filepath = out / f"{doc_id}.json"
        with open(filepath, "w") as f:
            json.dump(props, f, indent=2, default=str)
        count += 1

    return count


def copy_doc_file_to_temp(
    doc: Any,
    session: Any,
    filename: str,
    extension: str = "",
) -> tuple[str, str]:
    """Copy a binary file from a document's database storage to a temp file.

    MATLAB equivalent: ndi.database.fun.copydocfile2temp

    Args:
        doc: The NDI document containing the file.
        session: The session the document belongs to.
        filename: The filename within the document's file storage.
        extension: File extension including leading dot (e.g. ``'.dat'``).

    Returns:
        Tuple of ``(temp_path, temp_path_without_extension)``.
        The caller should delete the temp file when finished.
    """
    import tempfile

    f = session.database_openbinarydoc(doc, filename)
    data = f.read()
    if hasattr(f, "close"):
        f.close()

    # Create temp file
    fd, base_path = tempfile.mkstemp(suffix=extension)
    import os

    os.close(fd)

    with open(base_path, "wb") as out:
        out.write(data)

    # Compute path without extension
    if extension:
        path_without_ext = base_path[: -len(extension)]
    else:
        path_without_ext = base_path

    return base_path, path_without_ext


def extract_docs_files(
    session: Any,
    target_path: str | None = None,
) -> tuple[list[Any], str]:
    """Extract all documents and their binary files to a directory.

    MATLAB equivalent: ndi.database.fun.extract_doc_files

    Args:
        session: An NDI session or dataset.
        target_path: Directory to write files. If None, creates a temp dir.

    Returns:
        Tuple of ``(documents, target_path)``.
    """
    import json
    import tempfile
    from pathlib import Path

    from .query import Query

    if target_path is None:
        target_path = tempfile.mkdtemp(prefix="ndi_extract_")

    out = Path(target_path)
    out.mkdir(parents=True, exist_ok=True)

    docs = session.database_search(Query("").isa("base"))

    for doc in docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue

        doc_id = props.get("base", {}).get("id", "")
        if not doc_id:
            continue

        # Write JSON
        doc_dir = out / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)

        with open(doc_dir / "document.json", "w") as f:
            json.dump(props, f, indent=2, default=str)

        # Copy binary files
        files_info = props.get("files", {})
        if isinstance(files_info, dict):
            file_list = files_info.get("file_list", [])
            for fname in file_list:
                if not fname:
                    continue
                try:
                    fobj = session.database_openbinarydoc(doc, fname)
                    data = fobj.read()
                    if hasattr(fobj, "close"):
                        fobj.close()
                    with open(doc_dir / fname, "wb") as bf:
                        bf.write(data)
                except Exception:
                    pass

    return docs, target_path
