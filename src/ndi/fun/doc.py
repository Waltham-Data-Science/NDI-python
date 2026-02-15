"""
ndi.fun.doc - Document utility functions.

MATLAB equivalents: +ndi/+fun/+doc/diff.m, findFuid.m, allTypes.m, getDocTypes.m
"""

from __future__ import annotations

import json
from typing import Any


def all_types() -> list[str]:
    """Return all known NDI document types by scanning schema JSON files.

    MATLAB equivalent: ndi.fun.doc.allTypes

    Returns:
        Sorted list of document type names.
    """
    from ndi.common import PathConstants

    types: set[str] = set()
    doc_folder = PathConstants.COMMON_FOLDER / "database_documents"
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


def find_fuid(session: Any, fuid: str) -> tuple[Any | None, str]:
    """Search session for a document containing a file with the given UID.

    MATLAB equivalent: ndi.fun.doc.findFuid

    Args:
        session: An NDI session instance.
        fuid: File UID to search for.

    Returns:
        Tuple of ``(document, filename)`` or ``(None, '')`` if not found.
    """
    from ndi.query import Query

    docs = session.database_search(Query("").isa("base"))
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


def make_species_strain_sex(
    session: Any,
    subject_doc: Any,
    *,
    species: str = "",
    strain: str = "",
    sex: str = "",
    add_to_database: bool = False,
) -> list[Any]:
    """Create OpenMINDS-standard documents for species, strain, and sex.

    MATLAB equivalent: ndi.fun.doc.subject.makeSpeciesStrainSex

    Uses the ``openminds`` Python library to create controlled-term objects
    (Species, Strain, BiologicalSex), then converts them to NDI documents
    via :func:`ndi.openminds_convert.openminds_obj_to_ndi_document`.

    Args:
        session: NDI session instance.
        subject_doc: Subject document to link via dependency.
        species: Species ontology identifier (e.g. ``'NCBITaxon:10116'``).
        strain: Strain ontology identifier (e.g. ``'RRID:RGD_70508'``).
            Requires ``species`` to also be provided.
        sex: Biological sex (``'male'``, ``'female'``, ``'hermaphrodite'``,
            or ``'notDetectable'``).
        add_to_database: If True, add documents to the session database.

    Returns:
        List of created NDI Document objects.
    """
    from ndi.openminds_convert import openminds_obj_to_ndi_document

    subject_id = subject_doc.document_properties.get("base", {}).get("id", "")
    openminds_objects: list[Any] = []
    species_obj = None

    # 1. Handle Species
    if species:
        try:
            from ndi.ontology import lookup

            ont_id, name = lookup(species)
        except Exception:
            ont_id, name = species, species

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
    if strain:
        if species_obj is None:
            import warnings

            warnings.warn(
                "Cannot create a Strain document without a valid Species. "
                "Please provide the 'species' option.",
                stacklevel=2,
            )
        else:
            try:
                from ndi.ontology import lookup

                ont_id, name = lookup(strain)
            except Exception:
                ont_id, name = strain, strain

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
    if sex:
        _sex_ontology = {
            "male": "PATO:0000384",
            "female": "PATO:0000383",
            "hermaphrodite": "PATO:0001340",
        }
        pato_id = _sex_ontology.get(sex.lower(), "")
        if pato_id:
            try:
                from ndi.ontology import lookup

                ont_id, name = lookup(pato_id)
            except Exception:
                ont_id, name = pato_id, sex
        else:
            ont_id, name = "", sex

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

    if add_to_database:
        for d in docs:
            try:
                session.database_add(d)
            except Exception:
                pass

    return docs


def probe_locations_for_probes(
    session: Any,
    probe_docs: list[Any],
    locations: list[dict[str, str]],
    *,
    add_to_database: bool = False,
) -> list[Any]:
    """Create probe_location documents for a list of probes.

    MATLAB equivalent: ndi.fun.doc.probe.probeLocations4probes

    Args:
        session: NDI session instance.
        probe_docs: List of probe documents.
        locations: List of dicts with ``'name'`` and optional ``'ontology'``
            keys, one per probe.
        add_to_database: If True, add documents to the session database.

    Returns:
        List of created probe_location documents.
    """
    from ndi.document import Document

    docs: list[Any] = []
    for probe_doc, loc in zip(probe_docs, locations):
        probe_id = probe_doc.document_properties.get("base", {}).get("id", "")
        doc = Document("probe/probe_location")
        doc = doc.set_session_id(session.id())
        doc._set_nested_property("probe_location.name", loc.get("name", ""))
        if "ontology" in loc:
            doc._set_nested_property(
                "probe_location.ontology",
                loc["ontology"],
            )
        doc = doc.set_dependency_value("probe_id", probe_id)
        docs.append(doc)

    if add_to_database:
        for d in docs:
            try:
                session.database_add(d)
            except Exception:
                pass

    return docs


def diff(
    doc1: Any,
    doc2: Any,
    exclude_fields: list[str] | None = None,
    compare_files: bool = False,
) -> dict[str, Any]:
    """Compare two NDI documents for equality.

    MATLAB equivalent: ndi.fun.doc.diff

    Order-independent comparison for depends_on and file lists.

    Args:
        doc1: First document.
        doc2: Second document.
        exclude_fields: Dot-separated field paths to skip
            (e.g. ``['base.session_id']``).
        compare_files: Whether to compare file lists.

    Returns:
        Dict with ``'equal'`` (bool) and ``'details'`` (list of strings).
    """
    exclude_fields = exclude_fields or []
    details: list[str] = []

    p1 = doc1.document_properties if hasattr(doc1, "document_properties") else doc1
    p2 = doc2.document_properties if hasattr(doc2, "document_properties") else doc2

    if not isinstance(p1, dict) or not isinstance(p2, dict):
        if p1 != p2:
            details.append("Documents have different types")
        return {"equal": len(details) == 0, "details": details}

    def _exclude(path: str) -> bool:
        return any(path == e or path.startswith(e + ".") for e in exclude_fields)

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
            if a != b:
                details.append(f"{path}: {a!r} != {b!r}")

    # Skip file comparison unless requested
    if not compare_files:
        exclude_fields = list(exclude_fields) + ["files"]

    _compare(p1, p2)
    return {"equal": len(details) == 0, "details": details}


def ontology_table_row_vars(
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
    from ndi.query import Query

    docs = session.database_search(Query("").isa("ontologyTableRow"))

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


def get_doc_types(
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

    from ndi.query import Query

    docs = session.database_search(Query("").isa("base"))

    type_counter: Counter[str] = Counter()
    for doc in docs:
        props = doc.document_properties if hasattr(doc, "document_properties") else doc
        if isinstance(props, dict):
            class_name = props.get("document_class", {}).get("class_name", "unknown")
            type_counter[class_name] += 1

    sorted_types = sorted(type_counter.keys())
    counts = [type_counter[t] for t in sorted_types]

    return sorted_types, counts
