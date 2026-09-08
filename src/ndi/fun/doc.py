"""
ndi.fun.doc - ndi_document utility functions.

MATLAB equivalents: +ndi/+fun/+doc/diff.m, findFuid.m, allTypes.m, getDocTypes.m
"""

from __future__ import annotations

import json
import math
import warnings
from typing import Any


def allTypes() -> list[str]:
    """Return all known NDI document types by scanning schema JSON files.

    MATLAB equivalent: ndi.fun.doc.allTypes

    Returns:
        Sorted list of document type names.
    """
    from ndi.common import ndi_common_PathConstants

    types: set[str] = set()
    doc_folder = ndi_common_PathConstants.COMMON_FOLDER / "database_documents"
    search_paths = [doc_folder]

    # Also check calculator doc paths
    calc_path = doc_folder / "apps" / "calculators"
    if calc_path.exists():
        search_paths.append(calc_path)

    for base in search_paths:
        if not base.exists():
            continue
        for f in base.rglob("*.json"):
            if f.name.startswith("."):
                continue
            name = f.stem
            # Strip _schema suffix if present
            if name.endswith("_schema"):
                name = name[:-7]
            types.add(name)

    return sorted(types)


def findFuid(session: Any, fuid: str) -> tuple[Any | None, str]:
    """Search session for a document containing a file with the given UID.

    MATLAB equivalent: ndi.fun.doc.findFuid

    Args:
        session: An NDI session instance.
        fuid: File UID to search for.

    Returns:
        Tuple of ``(document, filename)`` or ``(None, '')`` if not found.
    """
    from ndi.query import ndi_query

    docs = session.database_search(ndi_query("").isa("base"))
    for doc in docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue
        files = props.get("files", {})
        if not isinstance(files, dict):
            continue
        for fi in files.get("file_info", []):
            if not isinstance(fi, dict):
                continue
            for loc in fi.get("locations", []):
                if isinstance(loc, dict) and loc.get("uid", "") == fuid:
                    return doc, fi.get("name", "")
    return None, ""


#: MATLAB's mustBeMember list, with the PATO term for each.
#: 'notDetectable' has no PATO id, so its document carries only a name.
BIOLOGICAL_SEX_TERMS = {
    "male": "PATO:0000384",
    "female": "PATO:0000383",
    "hermaphrodite": "PATO:0001340",
    "notDetectable": "",
}


def makeSpeciesStrainSex(
    session: Any,
    subjectID: str,
    *,
    Species: str = "",
    Strain: str = "",
    BiologicalSex: str = "",
    AddToSession: bool = False,
    species: str | None = None,
    strain: str | None = None,
    sex: str | None = None,
) -> list[Any]:
    """Create OpenMINDS-standard documents for species, strain, and sex.

    MATLAB equivalent: ndi.fun.doc.subject.makeSpeciesStrainSex

    Uses the ``openminds`` Python library to create controlled-term objects
    (Species, Strain, BiologicalSex), then converts them to NDI documents
    via :func:`ndi.openminds_convert.openminds_obj_to_ndi_document`.

    Args:
        session: NDI session instance.
        subjectID: ndi_subject document identifier string.
        Species: Species ontology identifier (e.g. ``'NCBITaxon:10116'``).
        Strain: Strain ontology identifier (e.g. ``'RRID:RGD_70508'``).
            Requires ``Species`` to also be provided.
        BiologicalSex: Biological sex (``'male'``, ``'female'``,
            ``'hermaphrodite'``, or ``'notDetectable'``).
        AddToSession: If True, add documents to the session database.

    Returns:
        List of created NDI ndi_document objects.
    """
    from ndi.openminds_convert import openminds_obj_to_ndi_document

    # Support lowercase aliases
    if species is not None and not Species:
        Species = species
    if strain is not None and not Strain:
        Strain = strain
    if sex is not None and not BiologicalSex:
        BiologicalSex = sex

    # Accept document objects or string IDs
    if hasattr(subjectID, "document_properties"):
        subject_id = subjectID.document_properties.get("base", {}).get("id", str(subjectID))
    else:
        subject_id = subjectID
    openminds_objects: list[Any] = []
    species_obj = None

    # 1. Handle Species
    if Species:
        try:
            from ndi.ontology import lookup

            # `*_` is how a caller asks for MATLAB's first two of six
            # outputs: MATLAB permits requesting fewer outputs than are
            # declared, Python unpacking demands an exact count.
            ont_id, name, *_ = lookup(Species)
        except Exception as exc:
            # MATLAB warns and creates nothing at all. This keeps the object
            # with the caller's text as its NAME but WITHOUT an ontology
            # identifier, which is the part that matters: the old fallback
            # was (Species, Species), so the preferredOntologyIdentifier
            # became the name -- a species asserted to be identified by
            # 'Mus musculus' in whatever ontology. Deliberately more
            # permissive than MATLAB, so that a caller who has a plain
            # species name still gets a document, and warned about either
            # way.
            warnings.warn(
                f"Could not look up ontology term for species {Species!r}: {exc}",
                stacklevel=2,
            )
            ont_id, name = None, Species

        try:
            from openminds.latest.controlled_terms import Species as OMSpecies

            species_kwargs: dict[str, Any] = {"name": name}
            if ont_id:
                species_kwargs["preferred_ontology_identifier"] = ont_id
            species_obj = OMSpecies(**species_kwargs)
            openminds_objects.append(species_obj)
        except ImportError:
            warnings.warn(
                "openminds package not installed; cannot create Species document",
                stacklevel=2,
            )

    # 2. Handle Strain (requires species)
    if Strain:
        if species_obj is None:
            warnings.warn(
                "Cannot create a Strain document without a valid Species. "
                "Please provide the 'Species' option.",
                stacklevel=2,
            )
        else:
            try:
                from ndi.ontology import lookup

                ont_id, name, *_ = lookup(Strain)
            except Exception as exc:
                warnings.warn(
                    f"Could not look up ontology term for strain {Strain!r}: {exc}",
                    stacklevel=2,
                )
                ont_id, name = None, Strain

            try:
                from openminds.latest.core import Strain as OMStrain

                # MATLAB passes 'ontologyIdentifier', ID. Leaving it off
                # dropped the strain's identifier entirely, so a strain came
                # back as a bare name with nothing to resolve it.
                strain_obj = OMStrain(
                    name=name,
                    species=[species_obj],
                    ontology_identifiers=[ont_id] if ont_id else None,
                )
                openminds_objects.append(strain_obj)
            except ImportError:
                warnings.warn(
                    "openminds package not installed; cannot create Strain document",
                    stacklevel=2,
                )

    # 3. Handle Biological Sex
    if BiologicalSex:
        # MATLAB's mustBeMember rejects anything outside these four; this
        # accepted any string and quietly made a BiologicalSex document out
        # of it.
        if BiologicalSex not in BIOLOGICAL_SEX_TERMS:
            raise ValueError(
                f"BiologicalSex must be one of {sorted(BIOLOGICAL_SEX_TERMS)}; "
                f"got {BiologicalSex!r}."
            )

        pato_id = BIOLOGICAL_SEX_TERMS[BiologicalSex]
        ont_id, name = None, BiologicalSex
        if pato_id:
            try:
                from ndi.ontology import lookup

                ont_id, name, *_ = lookup(pato_id)
            except Exception as exc:
                warnings.warn(
                    f"Could not look up ontology term {pato_id!r} for "
                    f"biological sex {BiologicalSex!r}: {exc}",
                    stacklevel=2,
                )
                ont_id, name = None, BiologicalSex

        try:
            from openminds.latest.controlled_terms import BiologicalSex as OMSex

            # MATLAB builds notDetectable with a name and NO
            # preferredOntologyIdentifier, rather than an empty one.
            sex_kwargs: dict[str, Any] = {"name": name}
            if ont_id:
                sex_kwargs["preferred_ontology_identifier"] = ont_id
            openminds_objects.append(OMSex(**sex_kwargs))
        except ImportError:
            warnings.warn(
                "openminds package not installed; cannot create BiologicalSex document",
                stacklevel=2,
            )

    # 4. Convert openMINDS objects to NDI documents
    docs: list[Any] = []
    if openminds_objects:
        try:
            docs = openminds_obj_to_ndi_document(
                openminds_objects,
                session.id(),
                "subject",
                subject_id,
            )
        except Exception:
            warnings.warn(
                "Failed to convert openMINDS objects to NDI documents",
                stacklevel=2,
            )

    if AddToSession and docs:
        # One call, as MATLAB makes, and errors reach the caller: adding
        # under `except Exception: pass` reported success for documents that
        # never entered the database.
        session.database_add(docs)

    return docs


def probeLocations4probes(
    session: Any,
    probes: list[Any],
    ontology_lookup_strings: list[str],
    *,
    doAdd: bool = True,
) -> list[Any]:
    """Create probe_location documents for a list of probes.

    MATLAB equivalent: ndi.fun.doc.probe.probeLocations4probes

    Args:
        session: NDI session instance.
        probes: List of probe objects or probe documents.
        ontology_lookup_strings: List of ontology lookup strings, one per
            probe, e.g. ``'UBERON:0000411'``. Must be the same length as
            *probes*.
        doAdd: If True (default), add the documents to the session database.

    Returns:
        List of created probe_location documents. A probe whose lookup
        string does not resolve is warned about and skipped, as MATLAB
        does, so the list can be shorter than *probes*.

    Raises:
        ValueError: If the two lists are different lengths.
    """
    from ndi.document import ndi_document

    if len(probes) != len(ontology_lookup_strings):
        # zip() silently truncated to the shorter list, so a caller who
        # miscounted got location documents for some of their probes and no
        # word about the rest.
        raise ValueError(
            f"The number of probes ({len(probes)}) must match the number of "
            f"ontology_lookup_strings ({len(ontology_lookup_strings)})."
        )

    docs: list[Any] = []
    for probe, lookup_str in zip(probes, ontology_lookup_strings):
        try:
            from ndi.ontology import lookup

            result = lookup(lookup_str)
            ontology_name = _prefixed_ontology_id(result)
            location_name = result.name
        except Exception as exc:
            # MATLAB warns and SKIPS. Falling back to the lookup string as
            # the name, as this did, wrote a document asserting a location
            # that was never resolved.
            warnings.warn(
                f"Could not look up ontology term {lookup_str!r}. "
                f"Skipping probe {_probe_string(probe)}. Error: {exc}",
                stacklevel=2,
            )
            continue

        doc = ndi_document("probe/probe_location")
        doc = doc.set_session_id(session.id())
        doc = doc.setproperties(
            **{
                # The schema declares probe_location.ontology_name; writing
                # 'ontology' put the term in a field nothing reads and left
                # the declared one empty.
                "probe_location.ontology_name": ontology_name,
                "probe_location.name": location_name,
            }
        )
        doc = doc.set_dependency_value("probe_id", _probe_id(probe))
        docs.append(doc)

    if doAdd and docs:
        # One call, as MATLAB makes; and errors are not swallowed -- adding
        # under an `except Exception: pass` reported success for documents
        # that never reached the database.
        session.database_add(docs)

    return docs


def _prefixed_ontology_id(result: Any) -> str:
    """MATLAB: prefix:id, unless the id already carries the prefix."""
    identifier = str(getattr(result, "id", "") or "")
    prefix = str(getattr(result, "prefix", "") or "")
    if prefix and not identifier.startswith(f"{prefix}:"):
        return f"{prefix}:{identifier}"
    return identifier


def _probe_id(probe: Any) -> str:
    """The probe's id, whether it is a probe object or a probe document."""
    identifier = getattr(probe, "id", None)
    if callable(identifier):
        identifier = identifier()
    if identifier:
        return str(identifier)
    properties = getattr(probe, "document_properties", None)
    if isinstance(properties, dict):
        return str(properties.get("base", {}).get("id", ""))
    return ""


def _probe_string(probe: Any) -> str:
    """MATLAB names the skipped probe with probestring(); fall back to id."""
    probestring = getattr(probe, "probestring", None)
    if callable(probestring):
        try:
            return str(probestring())
        except Exception:
            pass
    return _probe_id(probe)


def diff(
    doc1: Any,
    doc2: Any,
    *,
    ignoreFields: list[str] | None = None,
    exclude_fields: list[str] | None = None,
    checkFiles: bool = False,
    checkFileList: bool = True,
    compare_files: bool | None = None,
    session1: Any = None,
    session2: Any = None,
) -> dict[str, Any]:
    """Compare two NDI documents for equality.

    MATLAB equivalent: ndi.fun.doc.diff

    Order-independent comparison for depends_on and file lists.

    Args:
        doc1: First document.
        doc2: Second document.
        ignoreFields: Dot-separated field paths to skip
            (e.g. ``['base.session_id']``). Defaults to
            ``['base.session_id']``.
        checkFiles: Whether to compare file contents.
        checkFileList: Whether to compare the file_info lists
            (default True).
        session1: ndi_session for doc1 (used for cross-session file
            comparison when *checkFiles* is True).
        session2: ndi_session for doc2 (used for cross-session file
            comparison when *checkFiles* is True).

    Returns:
        Dict with ``'equal'`` (bool) and ``'details'`` (list of strings).
    """
    # Support both MATLAB-style and Pythonic parameter names
    if exclude_fields is not None and ignoreFields is None:
        ignoreFields = exclude_fields
    if ignoreFields is None:
        ignoreFields = ["base.session_id"]
    if compare_files is not None:
        checkFileList = compare_files
    _exclude_fields = list(ignoreFields)
    details: list[str] = []

    p1 = doc1.document_properties if hasattr(doc1, "document_properties") else doc1
    p2 = doc2.document_properties if hasattr(doc2, "document_properties") else doc2

    if not isinstance(p1, dict) or not isinstance(p2, dict):
        if p1 != p2:
            details.append("Documents have different types")
        return {"equal": len(details) == 0, "details": details}

    def _exclude(path: str) -> bool:
        return any(path == e or path.startswith(e + ".") for e in _exclude_fields)

    def _compare(a: Any, b: Any, path: str = "") -> None:
        if _exclude(path):
            return
        if isinstance(a, dict) and isinstance(b, dict):
            all_keys = set(a.keys()) | set(b.keys())
            for k in sorted(all_keys):
                sub = f"{path}.{k}" if path else k
                if k not in a:
                    details.append(f"{sub}: missing in doc1")
                elif k not in b:
                    details.append(f"{sub}: missing in doc2")
                else:
                    _compare(a[k], b[k], sub)
        elif isinstance(a, list) and isinstance(b, list):
            if path.endswith("depends_on") or path.endswith("file_info"):
                # Order-independent
                sa = sorted(json.dumps(x, sort_keys=True) for x in a)
                sb = sorted(json.dumps(x, sort_keys=True) for x in b)
                if sa != sb:
                    details.append(f"{path}: lists differ (order-independent)")
            elif len(a) != len(b):
                details.append(f"{path}: list lengths differ ({len(a)} vs {len(b)})")
            else:
                for i, (va, vb) in enumerate(zip(a, b)):
                    _compare(va, vb, f"{path}[{i}]")
        else:
            # Treat NaN == NaN (matches MATLAB behaviour)
            both_nan = (
                isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b)
            )
            if not both_nan and a != b:
                details.append(f"{path}: {a!r} != {b!r}")

    # Skip file list comparison unless requested
    if not checkFileList:
        _exclude_fields.append("files")

    _compare(p1, p2)

    if checkFiles:
        _compare_file_contents(doc1, doc2, session1, session2, details)

    return {"equal": len(details) == 0, "details": details}


def _compare_file_contents(
    doc1: Any,
    doc2: Any,
    session1: Any,
    session2: Any,
    details: list[str],
) -> None:
    """Step 5 of MATLAB's ``ndi.fun.doc.diff``: compare the binary files.

    THIS WAS NOT PORTED, AND ITS ABSENCE WAS SILENT. ``checkFiles`` was
    accepted, ``session1`` and ``session2`` were accepted, and none of the
    three was ever read -- so ``diff(a, b, checkFiles=True)`` reported the
    documents equal without comparing a single byte, and MATLAB's guard
    ("If checkFiles is true, session1 and session2 must be provided") never
    fired either. A difference-finder that answers "equal" for a comparison
    it did not run is the exact failure the bridge exists to catch.

    Mirrors MATLAB: union of both file lists, presence checked first, then
    size, then content through :func:`ndi.util.getHexDiffFromFileObj` -- the
    same helper MATLAB uses here, and this is its only caller on either side.
    Each file is compared inside a try/except that records the error as a
    detail rather than raising, as MATLAB's own try/catch does.
    """
    from ndi.util import getHexDiffFromFileObj

    if session1 is None or session2 is None:
        raise ValueError("If checkFiles is true, session1 and session2 must be provided.")

    list1 = list(doc1.current_file_list()) if hasattr(doc1, "current_file_list") else []
    list2 = list(doc2.current_file_list()) if hasattr(doc2, "current_file_list") else []
    set1, set2 = set(list1), set(list2)

    for fname in sorted(set1 | set2):
        in1, in2 = fname in set1, fname in set2
        if in1 != in2:
            present, absent = ("doc1", "doc2") if in1 else ("doc2", "doc1")
            details.append(f"File {fname} present in {present} but not {absent}.")
            continue  # cannot compare content if not in both

        handle1 = handle2 = None
        try:
            handle1 = session1.database_openbinarydoc(doc1, fname)
            handle2 = session2.database_openbinarydoc(doc2, fname)

            handle1.seek(0, 2)
            size1 = handle1.tell()
            handle1.seek(0)
            handle2.seek(0, 2)
            size2 = handle2.tell()
            handle2.seek(0)

            if size1 != size2:
                details.append(f"File {fname} size mismatch: {size1} vs {size2}.")
            else:
                identical, _ = getHexDiffFromFileObj(handle1, handle2)
                if not identical:
                    details.append(f"File {fname} content mismatch.")
        except Exception as exc:  # noqa: BLE001 -- MATLAB catches and reports too
            details.append(f"Error comparing file {fname}: {exc}")
        finally:
            for session, handle in ((session1, handle1), (session2, handle2)):
                if handle is not None and hasattr(session, "database_closebinarydoc"):
                    try:
                        session.database_closebinarydoc(handle)
                    except Exception:  # noqa: BLE001
                        pass


def ontologyTableRowVars(
    session: Any,
) -> tuple[list[str], list[str], list[str]]:
    """Return all unique ontologyTableRow variable names in a session.

    MATLAB equivalent: ndi.fun.doc.ontologyTableRowVars

    Searches for all ``ontologyTableRow`` documents and extracts the
    unique variable names, short names, and ontology node names from
    their comma-separated fields.

    Args:
        session: An NDI session or dataset instance.

    Returns:
        Tuple of ``(names, variable_names, ontology_nodes)`` where each
        is a sorted list of unique strings.
    """
    from ndi.query import ndi_query

    docs = session.database_search(ndi_query("").isa("ontologyTableRow"))

    names_set: dict[str, tuple[str, str]] = {}

    for doc in docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if not isinstance(props, dict):
            continue

        otr = props.get("ontologyTableRow", {})
        if not isinstance(otr, dict):
            continue

        raw_names = otr.get("names", "")
        raw_var_names = otr.get("variableNames", "")
        raw_ont_nodes = otr.get("ontologyNodes", "")

        if not raw_names:
            continue

        name_list = [s.strip() for s in raw_names.split(",")]
        var_list = (
            [s.strip() for s in raw_var_names.split(",")]
            if raw_var_names
            else [""] * len(name_list)
        )
        ont_list = (
            [s.strip() for s in raw_ont_nodes.split(",")]
            if raw_ont_nodes
            else [""] * len(name_list)
        )

        for n, v, o in zip(name_list, var_list, ont_list):
            if n and n not in names_set:
                names_set[n] = (v, o)

    sorted_names = sorted(names_set.keys())
    variable_names = [names_set[n][0] for n in sorted_names]
    ontology_nodes = [names_set[n][1] for n in sorted_names]

    return sorted_names, variable_names, ontology_nodes


def getDocTypes(
    session: Any,
) -> tuple[list[str], list[int]]:
    """Find all unique document types and their counts in a session.

    MATLAB equivalent: ndi.fun.doc.getDocTypes

    Args:
        session: An NDI session or dataset instance.

    Returns:
        Tuple of ``(doc_types, doc_counts)`` where *doc_types* is a sorted
        list of unique class names and *doc_counts* contains the count for
        each type.
    """
    from collections import Counter

    from ndi.query import ndi_query

    docs = session.database_search(ndi_query("").isa("base"))

    type_counter: Counter[str] = Counter()
    for doc in docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if isinstance(props, dict):
            class_name = props.get("document_class", {}).get("class_name", "unknown")
            type_counter[class_name] += 1

    sorted_types = sorted(type_counter.keys())
    counts = [type_counter[t] for t in sorted_types]

    return sorted_types, counts


# Backward-compatible aliases
all_types = allTypes
find_fuid = findFuid
make_species_strain_sex = makeSpeciesStrainSex
probe_locations_for_probes = probeLocations4probes
probe_locations4probes_legacy = probeLocations4probes
ontology_table_row_vars = ontologyTableRowVars
get_doc_types = getDocTypes
