"""
ndi.openminds_convert - OpenMINDS object conversion utilities.

MATLAB equivalents:
- +ndi/+database/+fun/openMINDSobj2struct.m
- +ndi/+database/+fun/openMINDSobj2ndi_document.m
- +ndi/+util/+openminds/find_instance_name.m
- +ndi/+util/+openminds/find_techniques_names.m

Converts openMINDS Python objects (from the ``openMINDS`` PyPI package)
into NDI document structures with cross-reference handling via ``ndi://`` URIs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def openminds_obj_to_dict(
    obj: Any,
    visited: Optional[Dict[int, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Recursively serialize an openMINDS object graph to flat dicts.

    MATLAB equivalent: ndi.database.fun.openMINDSobj2struct

    Performs depth-first traversal with cycle detection. Each openMINDS
    object becomes a dict with:
    - ``openminds_type``: The ``@type`` URI (e.g. ``https://openminds.om-i.org/types/Species``)
    - ``python_type``: The Python class name
    - ``openminds_id``: The ``@id`` from the openMINDS object
    - ``ndi_id``: A new unique NDI identifier
    - ``fields``: Dict of property values (nested objects replaced by ``ndi://{ndi_id}`` references)

    Args:
        obj: An openMINDS object (or list of objects).
        visited: Internal cache for cycle detection (keyed by ``id(obj)``).

    Returns:
        List of flat dicts, one per object in the graph.
    """
    from .ido import Ido

    if visited is None:
        visited = {}

    objects = obj if isinstance(obj, list) else [obj]
    result: List[Dict[str, Any]] = []

    for item in objects:
        obj_id = id(item)

        # Skip if already visited
        if obj_id in visited:
            continue

        # Extract openMINDS metadata
        openminds_type = _get_openminds_type(item)
        python_type = type(item).__module__ + '.' + type(item).__qualname__
        openminds_id = _get_openminds_id(item)
        ndi_id = Ido().id

        entry = {
            'openminds_type': openminds_type,
            'python_type': python_type,
            'openminds_id': openminds_id,
            'ndi_id': ndi_id,
            'fields': {},
        }

        # Mark as visited before recursing (cycle prevention)
        visited[obj_id] = entry
        result.append(entry)

        # Iterate properties
        fields = _get_object_fields(item)
        for field_name, field_value in fields.items():
            if field_name.startswith('_'):
                continue

            if _is_openminds_object(field_value):
                # Single nested object
                child_results = openminds_obj_to_dict(field_value, visited)
                result.extend(child_results)
                child_id = id(field_value)
                if child_id in visited:
                    entry['fields'][field_name] = f"ndi://{visited[child_id]['ndi_id']}"
                else:
                    entry['fields'][field_name] = field_value

            elif isinstance(field_value, list):
                # List that may contain openMINDS objects
                refs = []
                for v in field_value:
                    if _is_openminds_object(v):
                        child_results = openminds_obj_to_dict(v, visited)
                        result.extend(child_results)
                        child_id = id(v)
                        if child_id in visited:
                            refs.append(f"ndi://{visited[child_id]['ndi_id']}")
                        else:
                            refs.append(v)
                    else:
                        refs.append(_convert_value(v))
                entry['fields'][field_name] = refs

            else:
                entry['fields'][field_name] = _convert_value(field_value)

    # Deduplicate (visited cache may cause duplicates in result)
    seen_ndi_ids = set()
    deduped = []
    for item in result:
        nid = item['ndi_id']
        if nid not in seen_ndi_ids:
            seen_ndi_ids.add(nid)
            deduped.append(item)

    return deduped


def openminds_obj_to_ndi_document(
    obj: Any,
    session_id: str,
    dependency_type: str = '',
    dependency_value: str = '',
) -> List[Any]:
    """Convert openMINDS objects to NDI documents with dependencies.

    MATLAB equivalent: ndi.database.fun.openMINDSobj2ndi_document

    Args:
        obj: An openMINDS object (or list of objects).
        session_id: The NDI session ID.
        dependency_type: Optional dependency type: ``'subject'``,
            ``'element'``, or ``'stimulus'``.
        dependency_value: The dependency ID value (required if
            dependency_type is set).

    Returns:
        List of NDI Document objects.

    Raises:
        ValueError: If dependency_type is set but dependency_value is empty.
    """
    from .document import Document

    if dependency_type and not dependency_value:
        raise ValueError(
            'dependency_value must not be empty if dependency_type is given.'
        )

    # Determine document schema and dependency name
    doc_schema = 'metadata/openminds'
    dependency_name = ''

    dtype = dependency_type.lower() if dependency_type else ''
    if dtype == 'subject':
        doc_schema = 'metadata/openminds_subject'
        dependency_name = 'subject_id'
    elif dtype == 'element':
        doc_schema = 'metadata/openminds_element'
        dependency_name = 'element_id'
    elif dtype == 'stimulus':
        doc_schema = 'metadata/openminds_stimulus'
        dependency_name = 'stimulus_element_id'
    elif dtype:
        raise ValueError(f"Unknown dependency_type: '{dependency_type}'")

    # Serialize the openMINDS object graph
    struct_list = openminds_obj_to_dict(obj)

    documents = []
    for s in struct_list:
        doc = Document(doc_schema)
        doc = doc.set_session_id(session_id)

        # Store the openMINDS data
        doc._set_nested_property('openminds.openminds_type', s['openminds_type'])
        doc._set_nested_property('openminds.python_type', s['python_type'])
        doc._set_nested_property('openminds.openminds_id', s['openminds_id'])
        doc._set_nested_property('openminds.fields', s['fields'])

        # Override the base.id with the NDI ID from serialization
        doc._set_nested_property('base.id', s['ndi_id'])

        # Scan fields for ndi:// references and add dependencies
        has_openminds_dep = False
        for _fname, fval in s['fields'].items():
            refs = []
            if isinstance(fval, str) and fval.startswith('ndi://'):
                refs.append(fval[6:])
            elif isinstance(fval, list):
                for v in fval:
                    if isinstance(v, str) and v.startswith('ndi://'):
                        refs.append(v[6:])
            for ref_id in refs:
                try:
                    doc = doc.add_dependency_value_n('openminds', ref_id)
                    has_openminds_dep = True
                except Exception:
                    pass

        if not has_openminds_dep:
            try:
                doc = doc.set_dependency_value('openminds', '')
            except Exception:
                pass

        # Set primary dependency if specified
        if dependency_name:
            doc = doc.set_dependency_value(dependency_name, dependency_value)

        documents.append(doc)

    return documents


def find_controlled_instance(
    names: List[str],
    controlled_type: str,
) -> List[str]:
    """Map user-friendly names to openMINDS controlled term instance names.

    MATLAB equivalent: ndi.util.openminds.find_instance_name

    Args:
        names: List of user-friendly names to look up.
        controlled_type: The controlled term type (e.g. ``'BiologicalSex'``,
            ``'Species'``). Use ``'TechniquesEmployed'`` for technique lookup.

    Returns:
        List of matching instance names from the controlled terms.
    """
    if controlled_type == 'TechniquesEmployed':
        return find_technique_names(names)

    try:
        import openminds.controlled_terms as ct
    except ImportError:
        return []

    cls = getattr(ct, controlled_type, None)
    if cls is None:
        return []

    # Get all instances
    all_instances = _get_controlled_instances(cls)

    # Match names
    matched = []
    for inst_name, inst_display in all_instances.items():
        if inst_display in names or inst_name in names:
            matched.append(inst_name)

    return matched


def find_technique_names(
    names: List[str],
) -> List[str]:
    """Map user-friendly names to openMINDS technique instance names.

    MATLAB equivalent: ndi.util.openminds.find_techniques_names

    Queries allowed technique types from ``DatasetVersion.technique``,
    enumerates all instances, and matches by name.

    Args:
        names: List of unformatted technique names.

    Returns:
        List of formatted technique strings (``"name (type)"``) or
        ``'InvalidFormat'`` for unmatched names.
    """
    try:
        import openminds.controlled_terms as ct
        from openminds.latest.core import DatasetVersion  # noqa: F401
    except ImportError:
        return ['InvalidFormat'] * len(names)

    # Build name → "name (type)" map from all technique types
    name_to_technique: Dict[str, str] = {}

    # Common technique types in openMINDS
    technique_types = ['Technique', 'AnalysisTechnique', 'StimulationApproach']

    for type_name in technique_types:
        cls = getattr(ct, type_name, None)
        if cls is None:
            continue
        instances = _get_controlled_instances(cls)
        for inst_name, display_name in instances.items():
            formatted = f'{display_name} ({type_name})'
            name_to_technique[display_name] = formatted
            name_to_technique[inst_name] = formatted

    # Match input names
    result = []
    for name in names:
        if name in name_to_technique:
            result.append(name_to_technique[name])
        else:
            result.append('InvalidFormat')

    return result


# =========================================================================
# Internal helpers
# =========================================================================

def _is_openminds_object(obj: Any) -> bool:
    """Check if an object is an openMINDS schema instance."""
    try:
        from openminds.abstract import Schema
        return isinstance(obj, Schema)
    except ImportError:
        # Fallback: check for openMINDS-like attributes
        return (
            hasattr(obj, 'type_') or
            hasattr(obj, 'X_TYPE') or
            (hasattr(obj, '__module__') and 'openminds' in getattr(obj, '__module__', ''))
        )


def _get_openminds_type(obj: Any) -> str:
    """Extract the @type URI from an openMINDS object."""
    # Try common attribute names
    for attr in ('type_', 'X_TYPE', '_type'):
        val = getattr(obj, attr, None)
        if val and isinstance(val, str):
            return val
    # Try JSON-LD style
    if hasattr(obj, 'to_jsonld'):
        try:
            jld = obj.to_jsonld()
            if isinstance(jld, dict):
                return jld.get('@type', '')
        except Exception:
            pass
    return type(obj).__name__


def _get_openminds_id(obj: Any) -> str:
    """Extract the @id from an openMINDS object."""
    for attr in ('id', '_id', 'at_id'):
        val = getattr(obj, attr, None)
        if val and isinstance(val, str):
            return val
    return ''


def _get_object_fields(obj: Any) -> Dict[str, Any]:
    """Extract fields from an openMINDS object."""
    # Try model_dump (Pydantic)
    if hasattr(obj, 'model_dump'):
        try:
            return obj.model_dump()
        except Exception:
            pass
    # Try __dict__
    if hasattr(obj, '__dict__'):
        return {
            k: v for k, v in obj.__dict__.items()
            if not k.startswith('_')
        }
    return {}


def _convert_value(val: Any) -> Any:
    """Convert MATLAB-incompatible types to JSON-safe values."""
    import datetime
    if isinstance(val, datetime.datetime):
        return val.isoformat()
    if isinstance(val, datetime.date):
        return val.isoformat()
    return val


def _get_controlled_instances(cls: Any) -> Dict[str, str]:
    """Get all instances of a controlled term class.

    Returns dict mapping instance name → display name.
    """
    instances: Dict[str, str] = {}

    # Try to get instances from class methods
    if hasattr(cls, 'get_instances'):
        try:
            for inst in cls.get_instances():
                name = getattr(inst, 'name', str(inst))
                instances[str(inst)] = name
            return instances
        except Exception:
            pass

    # Try to enumerate from class attributes
    for attr_name in dir(cls):
        if attr_name.startswith('_'):
            continue
        attr = getattr(cls, attr_name, None)
        if attr is not None and isinstance(attr, cls):
            display = getattr(attr, 'name', attr_name)
            instances[attr_name] = display

    return instances
