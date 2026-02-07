"""
ndi.fun.doc - Document utility functions.

MATLAB equivalents: +ndi/+fun/+doc/diff.m, findFuid.m, allTypes.m, getDocTypes.m
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


def all_types() -> List[str]:
    """Return all known NDI document types by scanning schema JSON files.

    MATLAB equivalent: ndi.fun.doc.allTypes

    Returns:
        Sorted list of document type names.
    """
    from ndi.common import PathConstants

    types: Set[str] = set()
    doc_folder = PathConstants.COMMON_FOLDER / 'database_documents'
    search_paths = [doc_folder]

    # Also check calculator doc paths
    calc_path = doc_folder / 'apps' / 'calculators'
    if calc_path.exists():
        search_paths.append(calc_path)

    for base in search_paths:
        if not base.exists():
            continue
        for f in base.rglob('*.json'):
            if f.name.startswith('.'):
                continue
            name = f.stem
            # Strip _schema suffix if present
            if name.endswith('_schema'):
                name = name[:-7]
            types.add(name)

    return sorted(types)


def get_doc_types(session: Any) -> Tuple[List[str], Dict[str, int]]:
    """Find all unique document types and counts in a session.

    MATLAB equivalent: ndi.fun.doc.getDocTypes

    Args:
        session: An NDI session instance.

    Returns:
        Tuple of ``(sorted_types, counts_dict)``.
    """
    from ndi.query import Query

    docs = session.database_search(Query('').isa('base'))
    counts: Dict[str, int] = {}
    for doc in docs:
        props = doc.document_properties if hasattr(doc, 'document_properties') else doc
        if isinstance(props, dict):
            classes = props.get('document_class', {}).get('class_list', [])
            if classes:
                doc_type = classes[-1].get('class_name', 'unknown')
            else:
                doc_type = 'unknown'
        else:
            doc_type = 'unknown'
        counts[doc_type] = counts.get(doc_type, 0) + 1

    sorted_types = sorted(counts.keys())
    return sorted_types, counts


def find_fuid(session: Any, fuid: str) -> Tuple[Optional[Any], str]:
    """Search session for a document containing a file with the given UID.

    MATLAB equivalent: ndi.fun.doc.findFuid

    Args:
        session: An NDI session instance.
        fuid: File UID to search for.

    Returns:
        Tuple of ``(document, filename)`` or ``(None, '')`` if not found.
    """
    from ndi.query import Query

    docs = session.database_search(Query('').isa('base'))
    for doc in docs:
        props = doc.document_properties if hasattr(doc, 'document_properties') else doc
        if not isinstance(props, dict):
            continue
        files = props.get('files', {})
        if not isinstance(files, dict):
            continue
        for fi in files.get('file_info', []):
            if not isinstance(fi, dict):
                continue
            for loc in fi.get('locations', []):
                if isinstance(loc, dict) and loc.get('uid', '') == fuid:
                    return doc, fi.get('name', '')
    return None, ''


def make_species_strain_sex(
    session: Any,
    subject_doc: Any,
    *,
    species: str = '',
    strain: str = '',
    sex: str = '',
    add_to_database: bool = False,
) -> List[Any]:
    """Create OpenMINDS-standard documents for species, strain, and sex.

    MATLAB equivalent: ndi.fun.doc.subject.makeSpeciesStrainSex

    Args:
        session: NDI session instance.
        subject_doc: Subject document to link via dependency.
        species: Species name or ontology term.
        strain: Strain name or ontology term.
        sex: Biological sex string.
        add_to_database: If True, add documents to the session database.

    Returns:
        List of created documents.
    """
    from ndi.document import Document

    docs: List[Any] = []
    subject_id = subject_doc.document_properties.get('base', {}).get('id', '')

    if species:
        doc = Document('openminds_species')
        doc = doc.set_session_id(session.id())
        doc._set_nested_property('openminds_species.species', species)
        doc = doc.set_dependency_value('subject_id', subject_id)
        docs.append(doc)

    if strain:
        doc = Document('openminds_strain')
        doc = doc.set_session_id(session.id())
        doc._set_nested_property('openminds_strain.strain', strain)
        doc = doc.set_dependency_value('subject_id', subject_id)
        docs.append(doc)

    if sex:
        doc = Document('openminds_biologicalsex')
        doc = doc.set_session_id(session.id())
        doc._set_nested_property('openminds_biologicalsex.biological_sex', sex)
        doc = doc.set_dependency_value('subject_id', subject_id)
        docs.append(doc)

    if add_to_database:
        for d in docs:
            try:
                session.database_add(d)
            except Exception:
                pass

    return docs


def probe_locations_for_probes(
    session: Any,
    probe_docs: List[Any],
    locations: List[Dict[str, str]],
    *,
    add_to_database: bool = False,
) -> List[Any]:
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

    docs: List[Any] = []
    for probe_doc, loc in zip(probe_docs, locations):
        probe_id = probe_doc.document_properties.get('base', {}).get('id', '')
        doc = Document('probe_location')
        doc = doc.set_session_id(session.id())
        doc._set_nested_property('probe_location.name', loc.get('name', ''))
        if 'ontology' in loc:
            doc._set_nested_property(
                'probe_location.ontology', loc['ontology'],
            )
        doc = doc.set_dependency_value('probe_id', probe_id)
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
    exclude_fields: Optional[List[str]] = None,
    compare_files: bool = False,
) -> Dict[str, Any]:
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
    details: List[str] = []

    p1 = doc1.document_properties if hasattr(doc1, 'document_properties') else doc1
    p2 = doc2.document_properties if hasattr(doc2, 'document_properties') else doc2

    if not isinstance(p1, dict) or not isinstance(p2, dict):
        if p1 != p2:
            details.append('Documents have different types')
        return {'equal': len(details) == 0, 'details': details}

    def _exclude(path: str) -> bool:
        return any(path == e or path.startswith(e + '.') for e in exclude_fields)

    def _compare(a: Any, b: Any, path: str = '') -> None:
        if _exclude(path):
            return
        if isinstance(a, dict) and isinstance(b, dict):
            all_keys = set(a.keys()) | set(b.keys())
            for k in sorted(all_keys):
                sub = f'{path}.{k}' if path else k
                if k not in a:
                    details.append(f'{sub}: missing in doc1')
                elif k not in b:
                    details.append(f'{sub}: missing in doc2')
                else:
                    _compare(a[k], b[k], sub)
        elif isinstance(a, list) and isinstance(b, list):
            if path.endswith('depends_on') or path.endswith('file_info'):
                # Order-independent
                sa = sorted(json.dumps(x, sort_keys=True) for x in a)
                sb = sorted(json.dumps(x, sort_keys=True) for x in b)
                if sa != sb:
                    details.append(f'{path}: lists differ (order-independent)')
            elif len(a) != len(b):
                details.append(f'{path}: list lengths differ ({len(a)} vs {len(b)})')
            else:
                for i, (va, vb) in enumerate(zip(a, b)):
                    _compare(va, vb, f'{path}[{i}]')
        else:
            if a != b:
                details.append(f'{path}: {a!r} != {b!r}')

    # Skip file comparison unless requested
    if not compare_files:
        exclude_fields = list(exclude_fields) + ['files']

    _compare(p1, p2)
    return {'equal': len(details) == 0, 'details': details}


def ontology_table_row_vars(
    session: Any,
) -> Tuple[List[str], List[str], List[str]]:
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

    docs = session.database_search(Query('').isa('ontologyTableRow'))

    names_set: Dict[str, Tuple[str, str]] = {}

    for doc in docs:
        props = doc.document_properties if hasattr(doc, 'document_properties') else doc
        if not isinstance(props, dict):
            continue

        otr = props.get('ontologyTableRow', {})
        if not isinstance(otr, dict):
            continue

        raw_names = otr.get('names', '')
        raw_var_names = otr.get('variableNames', '')
        raw_ont_nodes = otr.get('ontologyNodes', '')

        if not raw_names:
            continue

        name_list = [s.strip() for s in raw_names.split(',')]
        var_list = [s.strip() for s in raw_var_names.split(',')] if raw_var_names else [''] * len(name_list)
        ont_list = [s.strip() for s in raw_ont_nodes.split(',')] if raw_ont_nodes else [''] * len(name_list)

        for n, v, o in zip(name_list, var_list, ont_list):
            if n and n not in names_set:
                names_set[n] = (v, o)

    sorted_names = sorted(names_set.keys())
    variable_names = [names_set[n][0] for n in sorted_names]
    ontology_nodes = [names_set[n][1] for n in sorted_names]

    return sorted_names, variable_names, ontology_nodes
