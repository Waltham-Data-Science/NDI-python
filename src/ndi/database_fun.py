"""
ndi.database.fun - ndi_database utility functions for NDI.

MATLAB equivalents: +ndi/+database/+fun/*.m

Provides dependency traversal, batch retrieval, graph construction,
and document analysis utilities.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _require_pandas() -> None:
    if pd is None:
        raise ImportError(
            "pandas is required for ndi.database.fun table utilities. "
            "Install it with: pip install pandas"
        )


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
        *documents: One or more ndi.ndi_document objects.
        visited: Set of already-visited IDs (for recursion).

    Returns:
        List of all antecedent ndi_document objects.
    """
    from .query import ndi_query

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
    q = ndi_query("base.id") == dep_ids[0]
    for did in dep_ids[1:]:
        q = q | (ndi_query("base.id") == did)

    try:
        found = session_or_dataset.database_search(q)
    except Exception:  # noqa: BLE001 - logged; callers expect a list
        logger.debug("database_search failed; treating as no documents", exc_info=True)
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
    from .query import ndi_query

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
        q = ndi_query("").depends_on("*", doc_id)

        try:
            found = session_or_dataset.database_search(q)
        except Exception:  # noqa: BLE001 - logged; callers expect a list
            logger.debug("database_search failed; treating as no documents", exc_info=True)
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
        session_or_dataset: ndi_database-containing object.
        document_ids: List of document IDs.

    Returns:
        List aligned with document_ids, each element the matching
        ndi_document or None if not found.
    """
    from .query import ndi_query

    if not document_ids:
        return []

    # Build OR query for all IDs
    q = ndi_query("base.id") == document_ids[0]
    for did in document_ids[1:]:
        q = q | (ndi_query("base.id") == did)

    try:
        found = session_or_dataset.database_search(q)
    except Exception:  # noqa: BLE001 - logged; callers expect a list
        logger.debug("database_search failed; treating as no documents", exc_info=True)
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
        documents: List of ndi.ndi_document objects.

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
    from .query import ndi_query

    q = (
        ndi_query("").isa("daqreader_mfdaq_epochdata_ingested")
        | ndi_query("").isa("daqmetadatareader_epochdata_ingested")
        | ndi_query("").isa("epochfiles_ingested")
        # Image series ingest their epoch data under their own class
        # (NDI-matlab 831a3fbef, issue #823). Without it an ingested
        # imageseries session reports as not ingested, which is the kind of
        # wrong answer that reads as "nothing to do" rather than as an error.
        | ndi_query("").isa("daqreader_image_epochdata_ingested")
    )

    try:
        return session_or_dataset.database_search(q)
    except Exception:  # noqa: BLE001 - logged; callers expect a list
        logger.debug("database_search failed; treating as no documents", exc_info=True)
        return []


def finddocs_elementEpochType(
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
        session_or_dataset: ndi_database-containing object.
        element_id: The element document ID.
        epoch_id: The epoch ID string.
        document_type: The document type name (e.g. ``'spectrogram'``).

    Returns:
        List of matching Documents.
    """
    from .query import ndi_query

    q1 = ndi_query("").isa(document_type)
    q2 = ndi_query("").depends_on("element_id", element_id)
    q3 = ndi_query("epochid.epochid") == epoch_id
    q = q1 & q2 & q3

    try:
        return session_or_dataset.database_search(q)
    except Exception:  # noqa: BLE001 - logged; callers expect a list
        logger.debug("database_search failed; treating as no documents", exc_info=True)
        return []


def ndi_document2ndi_object(
    ndi_document_obj: Any,
    ndi_session_obj: Any,
) -> Any:
    """Convert an NDI document into its corresponding Python object.

    MATLAB equivalent: ndi.database.fun.ndi_document2ndi_object

    Inspects the document's class hierarchy and instantiates the
    appropriate Python object (e.g. ndi_element, ndi_probe, ndi_subject).

    Args:
        ndi_document_obj: An ndi.ndi_document or a document ID string.
        ndi_session_obj: The session object for database lookups.

    Returns:
        The reconstructed NDI object, or None if reconstruction fails.
    """
    from .query import ndi_query

    # If given an ID string, look up the document
    if isinstance(ndi_document_obj, str):
        results = ndi_session_obj.database_search(ndi_query("base.id") == ndi_document_obj)
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
        from .element import ndi_element

        p = doc.document_properties
        el = p.get("element", {})
        return ndi_element(
            session=session,
            name=el.get("name", ""),
            reference=el.get("reference", 0),
            type=el.get("type", ""),
        )

    def _make_subject(doc: Any, session: Any) -> Any:
        from .subject import ndi_subject

        p = doc.document_properties
        subj = p.get("subject", {})
        return ndi_subject(
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
    from .query import ndi_query

    # Check for already-copied sessions
    try:
        refs, session_ids, *_ = ndi_dataset_obj.session_list()
        session_id = ndi_session_obj.id()
        if session_id in session_ids:
            return (
                False,
                f"ndi_session with ID {session_id} is already part of " f"the dataset.",
            )
    except Exception:
        pass

    # Get all documents from source session
    try:
        all_docs = ndi_session_obj.database_search(ndi_query("").isa("base"))
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
    from .query import ndi_query

    # Find all docs with depends_on
    try:
        all_docs = session_or_dataset.database_search(ndi_query("").isa("base"))
    except Exception:  # noqa: BLE001 - logged; callers expect a list
        logger.debug("database_search failed; treating as no documents", exc_info=True)
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
    N0: int | None = None,
    N1: int | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Read presentation time structure from a binary file.

    MATLAB equivalent: ndi.database.fun.read_presentation_time_structure

    Args:
        filename: Binary file path.
        N0: Start index (1-based, inclusive). Default: 1.
        N1: End index (1-based, inclusive). Default: num_entries.

    Returns:
        Tuple ``(header, entries)`` where header is the description
        string and entries is a list of dicts.

    Python-specific Notes:
        N0 and N1 use 1-based indexing to match MATLAB Semantic Parity.
        N0=1 means the first entry.
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

        # 1-based indexing to match MATLAB
        if N0 is None:
            N0 = 1
        if N1 is None:
            N1 = num_entries
        N1 = min(N1, num_entries)

        entries: list[dict[str, Any]] = []

        # Read all entries up to N1 (1-based)
        for _i in range(N1):
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

        # Slice to [N0, N1] (convert 1-based to 0-based for internal list access)
        entries = entries[N0 - 1 :]

    return header_str, entries


# =========================================================================
# ndi_database export / extraction
# =========================================================================


def database2json(
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

    from .query import ndi_query

    out = Path(output_path)
    out.mkdir(parents=True, exist_ok=True)

    docs = session.database_search(ndi_query("").isa("base"))

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


def copydocfile2temp(
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


def extract_doc_files(
    session: Any,
    target_path: str | None = None,
    *,
    reference_in_place: bool | None = None,
) -> tuple[list[Any], str]:
    """Extract every document, with its files, so it can be stored elsewhere.

    MATLAB equivalent: ndi.database.fun.extract_docs_files

    Returns the documents with each file location rewritten so that a
    subsequent ``database_add`` lands the bytes in the destination store --
    ``ndi.dataset.copySessionToDataset`` is the caller this exists for.

    FILE HANDLING. There are two ways the returned documents point at their
    bytes, selected by *reference_in_place*:

    * REFERENCE IN PLACE (the default when *target_path* is not given). Each
      file location is pointed AT THE SOURCE SESSION'S EXISTING file on disk,
      with ``delete_original=False``. A later ``database_add`` then copies
      each file exactly once, directly from the source into the destination,
      leaving the source untouched. This is what a dataset ingest wants: it
      avoids staging a second full copy of every file in a temp directory
      first, so the operation no longer transiently needs 2x the session's
      disk space.
    * COPY (the default when a *target_path* is given, and the behavior for
      any file whose bytes are NOT on the local filesystem). Files are copied
      to ``target_path/<uid>`` under the uid the source database knows them
      by. With no *target_path*, a temp directory is used.

    Reference in place applies ONLY to files whose bytes are on the LOCAL
    filesystem, which ``database_existbinarydoc`` reports without going to the
    network. A file that is not local -- a member of a cloud-backed session
    not fetched to this machine -- has nothing local to reference, so it falls
    back to the copy path (a temp directory is created on demand). A
    cloud-backed session therefore behaves as it did before this option.

    FILE SERIES. A series' manifest is an ordinary document file and is
    handled like one. The MEMBERS are handled too, which ``current_file_list``
    does not cover: it returns the manifest name only, deliberately, so that
    a 28,000-member series does not materialise 28,000 names. The members are
    enumerated from the series record instead and fetched by their
    ``NAME_<i>`` names, which resolve through the manifest
    (DID-matlab#173, #183). An absent slot is normal -- a sparse series is
    the case the mechanism exists for.

    Each member is recorded in the extracted document's ``ingest_locations``
    UNDER ITS ORIGINAL UID. That is what lets the copy be stored elsewhere:
    DID refuses a document declaring present members while recording no
    location for any of them (DID-matlab#185), and ingestion writes each
    member to ``FileDir/<uid>`` from this record -- so reusing the uid keeps
    the copied manifest, which names its members by uid, correct in the new
    store.

    Args:
        session: An NDI session or dataset.
        target_path: Directory to write copies to. If None, a temp dir is
            used on demand.
        reference_in_place: If True, reference local source files in place
            rather than copying them; if False, copy. The default is True
            when *target_path* is not supplied and False when it is (naming a
            *target_path* means "put copies there").

    Returns:
        Tuple of ``(documents, target_path)``. The documents are the ones the
        search returned, with their file_info rebuilt to point at either the
        referenced source files or the copies. ``target_path`` is the
        directory copies were written to, or ``""`` if nothing was copied
        (pure reference-in-place).

    Raises:
        OSError: If a file cannot be copied. Every copy made so far is
            removed first, as MATLAB does: a half-written extract is worse
            than none, and the usual cause is a full disk.
    """
    import shutil
    import tempfile
    from pathlib import Path

    from .query import ndi_query

    # Default: reference in place when no target_path was asked for; copy when
    # one was. MATLAB's extract_docs_files resolves the default the same way.
    if reference_in_place is None:
        reference_in_place = not target_path

    # In copy mode with no target_path, stage into a temp dir up front. In
    # reference-in-place mode the temp dir is created lazily -- only if a
    # non-local file forces a fall-back copy (see _ensure_copy_target).
    if not reference_in_place and not target_path:
        target_path = tempfile.mkdtemp(prefix="ndi_extract_")

    # A one-element holder so the nested copy helper can create the directory
    # lazily and hand the resolved path back to the caller.
    made_target = {"path": target_path or ""}
    files_i_made: list[Path] = []

    # An explicitly given (or eagerly staged) target is created up front, so a
    # caller that named one finds it even when nothing needed copying. A
    # reference-in-place run with no target leaves this empty and creates a
    # directory only if a non-local file forces a fall-back copy.
    if made_target["path"]:
        Path(made_target["path"]).mkdir(parents=True, exist_ok=True)

    def _ensure_copy_target() -> Path:
        if not made_target["path"]:
            made_target["path"] = tempfile.mkdtemp(prefix="ndi_extract_")
        out = Path(made_target["path"])
        out.mkdir(parents=True, exist_ok=True)
        return out

    def copy_in(source: str | Path, uid: str) -> Path:
        """Copy one file to <target>/<uid>, unwinding the extract on failure."""
        destination = _ensure_copy_target() / uid
        try:
            shutil.copyfile(source, destination)
        except OSError:
            for made in files_i_made:
                try:
                    made.unlink()
                except OSError:
                    pass
            raise
        files_i_made.append(destination)
        return destination

    docs = session.database_search(ndi_query("").isa("base"))

    for doc in docs:
        # has_files() rather than "does it declare a files section": the
        # latter is true for a document that declares files and has added
        # none, and there is nothing to do for one.
        if not (hasattr(doc, "has_files") and doc.has_files()):
            continue

        props = doc.document_properties
        doc_id = props.get("base", {}).get("id", "")
        if not doc_id:
            continue

        series_info = _extract_series_record(props)

        # Read the file list BEFORE clearing file_info, which is where it
        # comes from. MATLAB captures it before its reset for the same
        # reason; clearing first leaves nothing to copy and produces an
        # extract of no files at all, silently.
        #
        # current_file_list already names a series' MANIFEST -- it is an
        # ordinary file_info entry -- and deliberately does not name its
        # members, which are handled below.
        file_names = list(doc.current_file_list())

        # Rebuild file_info rather than appending to it: add_file adds a
        # SECOND location to a name that already has one, so without this
        # every extracted document would name both its copy and the source
        # database's path.
        #
        # Only file_info is cleared. MATLAB calls reset_file_info, which
        # clears files.series_info with it, and carries the series record
        # across by hand (NDI-matlab#946). Nothing to carry here: the record
        # is left where it stands and survives on its own.
        props["files"]["file_info"] = []

        for filename in file_names:
            # Is the file's bytes on the local filesystem? database_existbinarydoc
            # answers from local state only -- it never goes to the network --
            # so a true answer means we can reference the source file directly.
            local_path = ""
            if reference_in_place:
                exists, candidate = session.database_existbinarydoc(doc_id, filename)
                if exists and candidate and Path(candidate).is_file():
                    local_path = str(candidate)

            if local_path:
                # Reference the source file in place. delete_original=False:
                # this is the source session's own file, not a copy we made,
                # so a later database_add must copy it into the destination
                # WITHOUT removing it here. Deliberately not tracked in
                # files_i_made -- the error cleanup deletes what it made,
                # never the source.
                doc.add_file(filename, local_path, delete_original=False)
            else:
                handle = session.database_openbinarydoc(doc, filename)
                try:
                    source = getattr(handle, "fullpathfilename", None)
                finally:
                    session.database_closebinarydoc(handle)
                if not source:
                    continue
                # fileparts, as MATLAB does: an ingested file is named by its
                # uid with no extension, and stripping one guards against a
                # retrieval that handed back a suffixed scratch copy.
                uid = Path(source).stem
                doc.add_file(filename, str(copy_in(source, uid)))

        if series_info:
            _copy_series_members(
                session,
                doc,
                doc_id,
                series_info,
                copy_in,
                reference_in_place=reference_in_place,
            )
            doc.setproperties(**{"files.series_info": series_info})

    return docs, made_target["path"]


def _extract_series_record(props: dict) -> list[dict]:
    """This document's files.series_info, with no path into the source.

    ``ingest_locations`` names where the members sit in the SOURCE session
    and means nothing in the target path, so it is emptied with the same
    call the database makes on the way into storage. That makes this a no-op
    for every document a search returns today; it is here because an
    extract's output gets stored somewhere else, and a copy destined for
    another store should carry no path into the one it came from.

    Everything else travels: name, count, n_present and source_root describe
    the SERIES rather than where its bytes are, and the manifest listing the
    members is copied verbatim beside them.
    """
    files = props.get("files")
    if not isinstance(files, dict) or not files.get("series_info"):
        return []
    try:
        from did.document import Document
    except ImportError:  # pragma: no cover - did is a hard dependency
        return []

    stripped = Document.strip_series_ingest_locations(props)
    series_info = stripped.get("files", {}).get("series_info") or []
    if isinstance(series_info, dict):
        series_info = [series_info]
    return [entry for entry in series_info if isinstance(entry, dict)]


def _copy_series_members(
    session: Any,
    doc: Any,
    doc_id: str,
    series_info: list[dict],
    copy_in: Any,
    *,
    reference_in_place: bool = False,
) -> None:
    """Record every present member of every series, one ingest entry per uid.

    Walks the slots the series record declares and asks for each by its
    ``NAME_<i>`` name, which resolves through the manifest. Uses
    ``database_existbinarydoc`` rather than opening: an absent slot is
    normal, and a sparse series is the case the mechanism exists for.

    With *reference_in_place* the member entry points at the source file and
    nothing is copied; otherwise the member is copied via *copy_in*. Either
    way ``delete_original`` is 0 -- whether it is our copy or a reference to
    the source, the caller was promised the files would still be there.
    """
    from pathlib import Path

    for entry in series_info:
        name = str(entry.get("name", "") or "")
        if not name:
            continue
        try:
            slot_count = int(entry.get("count", 0) or 0)
        except (TypeError, ValueError):
            continue

        members: list[dict] = []
        for index in range(1, slot_count + 1):
            exists, member_path = session.database_existbinarydoc(doc_id, f"{name}_{index}")
            if not exists or not member_path:
                continue
            # Keep the ORIGINAL uid: ingestion writes the member to
            # FileDir/<uid> from this record, and the manifest just carried
            # over names its members by uid, so a fresh uid would leave the
            # copy's manifest pointing at nothing.
            member_uid = Path(member_path).stem
            if reference_in_place:
                # Reference the source file: do not copy, do not delete.
                location = str(member_path)
            else:
                location = str(copy_in(member_path, member_uid))
            members.append(
                {
                    "index": index,
                    "uid": member_uid,
                    "location": location,
                    "location_type": "file",
                    "ingest": 1,
                    "delete_original": 0,
                    "parameters": "",
                }
            )

        entry["ingest_locations"] = members


# =========================================================================
# Tables stored inside documents, as character arrays
# =========================================================================
#
# NDI keeps small tables -- a drug mixture, an odor list -- INSIDE a document
# rather than beside it as a file: the schema field is a string, and the
# string is the delimited text a table would have been written to. These two
# functions are the door in and out of that representation.
#
# The bridge contract used to record both as not_applicable, "Python
# equivalent is pandas.read_csv()". That is what a file reader would be;
# these read and write a CHARACTER ARRAY, which is the whole point -- there
# is no file. Documents written by MATLAB carry mixture tables that nothing
# in Python could read until now, which is issue #138.


def _readtable_options(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """MATLAB name-value pairs and Python keywords, as one option dict.

    MATLAB passes ``..., 'Delimiter', ','`` positionally; a Python caller
    would rather write ``Delimiter=","``. Both are accepted so a ported call
    site can read like its MATLAB twin without forcing that style on new code.
    """
    opts: dict[str, Any] = {}
    if len(args) % 2 != 0:
        raise ValueError(
            "name-value options must come in pairs; got an odd number of "
            f"positional arguments ({len(args)})"
        )
    for name, value in zip(args[::2], args[1::2], strict=True):
        opts[str(name)] = value
    opts.update(kwargs)
    return opts


def readtablechar(c: str, ext: str = ".txt", *args: Any, **kwargs: Any) -> pd.DataFrame:
    """Read a table from a character array.

    MATLAB equivalent: ``ndi.database.fun.readtablechar``, which writes *c* to
    a temporary file with extension *ext* and calls ``readtable`` on it. Here
    the text is parsed in memory instead -- the temporary file is an artifact
    of MATLAB needing a filename, not part of the meaning -- so *ext* only
    selects the parser and a caller may pass it with or without the leading
    dot, as MATLAB allows.

    The ``readtable`` options NDI actually uses are mapped onto
    :func:`pandas.read_csv`: ``Delimiter`` -> ``sep`` and
    ``ReadVariableNames`` -> ``header``. An option with no counterpart is
    refused rather than ignored, because silently dropping ``Delimiter``
    would return one column of joined text that still looks like a table.

    Args:
        c: The table as delimited text.
        ext: The extension the text would have as a file. ``.txt`` and
            ``.csv`` are equivalent here; both are delimited text.
        *args: MATLAB-style name-value pairs, e.g. ``"Delimiter", ","``.
        **kwargs: The same options as keywords, e.g. ``Delimiter=","``.

    Returns:
        The table as a :class:`pandas.DataFrame`.

    Raises:
        ValueError: If an option has no pandas counterpart, or the pairs are
            malformed.

    Example:
        >>> c = "name,value\\nsaline,2\\n"
        >>> readtablechar(c, ".txt", "Delimiter", ",")["name"].tolist()
        ['saline']
    """
    _require_pandas()

    opts = _readtable_options(args, kwargs)
    read_kwargs: dict[str, Any] = {}

    for name, value in opts.items():
        key = name.lower()
        if key == "delimiter":
            read_kwargs["sep"] = value
        elif key == "readvariablenames":
            read_kwargs["header"] = 0 if value else None
        else:
            raise ValueError(
                f"readtablechar: no pandas counterpart for readtable option {name!r}. "
                "Supported: Delimiter, ReadVariableNames."
            )

    read_kwargs.setdefault("sep", ",")

    ext = ext if ext.startswith(".") else "." + ext
    if ext.lower() not in (".txt", ".csv", ".dat", ".tsv"):
        raise ValueError(
            f"readtablechar: unsupported extension {ext!r}; "
            "the content must be delimited text (.txt, .csv, .tsv, .dat)."
        )

    import io

    return pd.read_csv(io.StringIO(c), **read_kwargs)


def writetablechar(t: pd.DataFrame, *args: Any, **kwargs: Any) -> str:
    """Write a table to a character array.

    MATLAB equivalent: ``ndi.database.fun.writetablechar`` -- the inverse of
    :func:`readtablechar`, and what put the mixture tables into the documents
    Python is now reading. MATLAB writes to a temporary file and reads the
    bytes back; here the text is produced in memory.

    Defaults match MATLAB's ``writetable``: comma-delimited, with the variable
    names as the first line. ``marderbath.m`` calls this with no options at
    all, so those defaults are the shape of the stored mixture tables.

    Args:
        t: The table to write.
        *args: MATLAB-style name-value pairs, e.g. ``"Delimiter", "\\t"``.
        **kwargs: The same options as keywords.

    Returns:
        The table as delimited text, newline-terminated as MATLAB writes it.

    Raises:
        ValueError: If an option has no pandas counterpart.
    """
    _require_pandas()

    opts = _readtable_options(args, kwargs)
    sep = ","
    header = True

    for name, value in opts.items():
        key = name.lower()
        if key == "delimiter":
            sep = value
        elif key == "writevariablenames":
            header = bool(value)
        else:
            raise ValueError(
                f"writetablechar: no pandas counterpart for writetable option {name!r}. "
                "Supported: Delimiter, WriteVariableNames."
            )

    return t.to_csv(index=False, sep=sep, header=header, lineterminator="\n")
