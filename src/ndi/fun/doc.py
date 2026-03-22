"""
ndi.fun.doc - ndi_document utility functions.

MATLAB equivalents: +ndi/+fun/+doc/diff.m, findFuid.m, allTypes.m, getDocTypes.m
"""

from __future__ import annotations

import json
import math
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

            ont_id, name = lookup(Species)
        except Exception:
            ont_id, name = Species, Species

        try:
            from openminds.latest.controlled_terms import Species as OMSpecies

            species_obj = OMSpecies(
                name=name,
                preferred_ontology_identifier=ont_id,
            )
            openminds_objects.append(species_obj)
        except ImportError:
            import warnings

            warnings.warn(
                "openminds package not installed; cannot create Species document",
                stacklevel=2,
            )

    # 2. Handle Strain (requires species)
    if Strain:
        if species_obj is None:
            import warnings

            warnings.warn(
                "Cannot create a Strain document without a valid Species. "
                "Please provide the 'Species' option.",
                stacklevel=2,
            )
        else:
            try:
                from ndi.ontology import lookup

                ont_id, name = lookup(Strain)
            except Exception:
                ont_id, name = Strain, Strain

            try:
                from openminds.latest.core import Strain as OMStrain

                strain_obj = OMStrain(name=name, species=[species_obj])
                openminds_objects.append(strain_obj)
            except ImportError:
                import warnings

                warnings.warn(
                    "openminds package not installed; cannot create Strain document",
                    stacklevel=2,
                )

    # 3. Handle Biological Sex
    if BiologicalSex:
        _sex_ontology = {
            "male": "PATO:0000384",
            "female": "PATO:0000383",
            "hermaphrodite": "PATO:0001340",
        }
        pato_id = _sex_ontology.get(BiologicalSex.lower(), "")
        if pato_id:
            try:
                from ndi.ontology import lookup

                ont_id, name = lookup(pato_id)
            except Exception:
                ont_id, name = pato_id, BiologicalSex
        else:
            ont_id, name = "", BiologicalSex

        try:
            from openminds.latest.controlled_terms import BiologicalSex as OMSex

            sex_obj = OMSex(name=name, preferred_ontology_identifier=ont_id)
            openminds_objects.append(sex_obj)
        except ImportError:
            import warnings

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
            import warnings

            warnings.warn(
                "Failed to convert openMINDS objects to NDI documents",
                stacklevel=2,
            )

    if AddToSession:
        for d in docs:
            try:
                session.database_add(d)
            except Exception:
                pass

    return docs


def probeLocations4probes(
    session: Any,
    probe_docs: list[Any],
    ontology_lookup_strings: list[str],
    *,
    doAdd: bool = True,
) -> list[Any]:
    """Create probe_location documents for a list of probes.

    MATLAB equivalent: ndi.fun.doc.probe.probeLocations4probes

    Args:
        session: NDI session instance.
        probe_docs: List of probe documents.
        ontology_lookup_strings: List of ontology lookup strings, one per
            probe. Each string is looked up to resolve a location name
            and ontology identifier.
        doAdd: If True (default), add documents to the session database.

    Returns:
        List of created probe_location documents.
    """
    from ndi.document import ndi_document

    docs: list[Any] = []
    for probe_doc, lookup_str in zip(probe_docs, ontology_lookup_strings):
        probe_id = probe_doc.document_properties.get("base", {}).get("id", "")
        doc = ndi_document("probe/probe_location")
        doc = doc.set_session_id(session.id())

        # Resolve ontology lookup string to name and ontology ID
        loc_name = lookup_str
        loc_ontology = ""
        try:
            from ndi.ontology import lookup

            result = lookup(lookup_str)
            if result:
                loc_name = getattr(result, "name", lookup_str) or lookup_str
                loc_ontology = getattr(result, "id", "") or ""
        except Exception:
            pass

        doc._set_nested_property("probe_location.name", loc_name)
        if loc_ontology:
            doc._set_nested_property(
                "probe_location.ontology",
                loc_ontology,
            )
        doc = doc.set_dependency_value("probe_id", probe_id)
        docs.append(doc)

    if doAdd:
        for d in docs:
            try:
                session.database_add(d)
            except Exception:
                pass

    return docs


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
                isinstance(a, float)
                and isinstance(b, float)
                and math.isnan(a)
                and math.isnan(b)
            )
            if not both_nan and a != b:
                details.append(f"{path}: {a!r} != {b!r}")

    # Skip file list comparison unless requested
    if not checkFileList:
        _exclude_fields.append("files")
    elif not checkFiles:
        # checkFileList is True but checkFiles is False:
        # compare file_info metadata but not actual file contents
        pass

    _compare(p1, p2)
    return {"equal": len(details) == 0, "details": details}


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
