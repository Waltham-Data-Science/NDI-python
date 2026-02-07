"""
ndi.validate - Document schema validation for NDI.

MATLAB equivalent: +ndi/validate.m

Validates ndi.document objects against their schema definitions.
Three-tier validation:
  1. This-class properties: Check property types match schema
  2. Superclass properties: Walk superclass hierarchy
  3. Dependency references: Check depends_on targets exist in database
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from .common import PathConstants

if TYPE_CHECKING:
    from .document import Document
    from .session.session_base import Session


# ---------------------------------------------------------------------------
# NDI type validators
# ---------------------------------------------------------------------------

_TYPE_VALIDATORS = {
    'did_uid': lambda v, p: isinstance(v, str),
    'char': lambda v, p: isinstance(v, str),
    'string': lambda v, p: isinstance(v, str),
    'integer': lambda v, p: isinstance(v, (int, float)) and (isinstance(v, int) or v == int(v)),
    'double': lambda v, p: isinstance(v, (int, float)),
    'timestamp': lambda v, p: isinstance(v, str) and _is_timestamp(v),
    'matrix': lambda v, p: isinstance(v, (list, tuple)),
    'structure': lambda v, p: isinstance(v, dict),
}

_ISO_TIMESTAMP_RE = re.compile(
    r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'
)


def _is_timestamp(value: str) -> bool:
    """Check if value looks like an ISO 8601 timestamp."""
    if not value:
        return True  # empty string is allowed as default
    return bool(_ISO_TIMESTAMP_RE.match(value))


def _check_integer_params(value: Any, params: Any) -> Optional[str]:
    """Check integer value against parameter constraints [min, max, increment]."""
    if not isinstance(params, list) or len(params) < 2:
        return None
    min_val, max_val = params[0], params[1]
    num_val = int(value) if isinstance(value, float) else value
    if num_val < min_val or num_val > max_val:
        return f'value {num_val} outside range [{min_val}, {max_val}]'
    return None


def _check_did_uid_params(value: str, params: Any) -> Optional[str]:
    """Check did_uid string length against parameter."""
    if isinstance(params, (int, float)) and params > 0:
        expected_len = int(params)
        if len(value) != expected_len:
            return f'expected length {expected_len}, got {len(value)}'
    return None


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------

_schema_cache: Dict[str, dict] = {}


def _load_schema(schema_name: str) -> Optional[dict]:
    """Load a schema JSON file by name.

    Searches in PathConstants.SCHEMA_PATH for ``{name}_schema.json``.
    Handles subdirectory paths (e.g. 'apps/calculations/simple_calc').

    Args:
        schema_name: Schema name, possibly with subdirectory prefix.

    Returns:
        Parsed JSON dict, or None if not found.
    """
    if schema_name in _schema_cache:
        return _schema_cache[schema_name]

    try:
        schema_path = PathConstants.SCHEMA_PATH
    except (ValueError, AttributeError):
        return None

    # Try direct path first
    filename = f'{schema_name}_schema.json'
    full_path = schema_path / filename

    if not full_path.exists():
        # Try searching subdirectories
        for candidate in schema_path.rglob(f'{schema_name.split("/")[-1]}_schema.json'):
            full_path = candidate
            break
        else:
            return None

    try:
        with open(full_path) as f:
            data = json.load(f)
        _schema_cache[schema_name] = data
        return data
    except (json.JSONDecodeError, OSError):
        return None


def _get_schema_for_document(doc: 'Document') -> Optional[dict]:
    """Get the schema for a document based on its document_class.

    Reads the document's ``document_class.definition`` path to find
    the corresponding schema file.

    Args:
        doc: NDI Document object.

    Returns:
        Schema dict or None.
    """
    props = doc.document_properties
    doc_class = props.get('document_class', {})

    # Try the definition path to derive schema name
    definition = doc_class.get('definition', '')
    if definition:
        # definition is like '$NDIDOCUMENTPATH/element.json'
        # Extract name: element
        basename = Path(definition).stem  # 'element'
        schema = _load_schema(basename)
        if schema:
            return schema

    # Fallback: use class_name to derive schema
    class_name = doc_class.get('class_name', '')
    if class_name:
        # class_name like 'ndi_document_element' -> 'element'
        name = class_name.replace('ndi_document_', '').replace('ndi_document', 'base')
        schema = _load_schema(name)
        if schema:
            return schema

    return None


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------


class ValidationResult:
    """Result of document validation.

    Attributes:
        is_valid: True if document passed all validation checks.
        errors_this: Errors from this-class property validation.
        errors_super: Dict mapping superclass names to their errors.
        errors_depends_on: Dict mapping dependency names to their status.
    """

    __slots__ = ('is_valid', 'errors_this', 'errors_super', 'errors_depends_on')

    def __init__(self) -> None:
        self.is_valid: bool = True
        self.errors_this: List[str] = []
        self.errors_super: Dict[str, List[str]] = {}
        self.errors_depends_on: Dict[str, str] = {}

    @property
    def error_message(self) -> str:
        """Format all errors into a human-readable string."""
        parts: List[str] = []
        if self.errors_this:
            parts.append('This-class errors:')
            for e in self.errors_this:
                parts.append(f'  - {e}')
        for sc_name, sc_errors in self.errors_super.items():
            if sc_errors:
                parts.append(f'Superclass "{sc_name}" errors:')
                for e in sc_errors:
                    parts.append(f'  - {e}')
        if self.errors_depends_on:
            parts.append('Dependency errors:')
            for name, status in self.errors_depends_on.items():
                if status != 'ok':
                    parts.append(f'  - {name}: {status}')
        return '\n'.join(parts)

    def __bool__(self) -> bool:
        return self.is_valid


def _validate_properties(
    doc_props: dict,
    class_name: str,
    schema: dict,
) -> List[str]:
    """Validate properties of a specific class section against its schema.

    Args:
        doc_props: The full document_properties dict.
        class_name: The class key to validate (e.g. 'base', 'element').
        schema: The schema dict containing property definitions.

    Returns:
        List of error messages (empty if valid).
    """
    errors: List[str] = []

    # Get the schema property definitions for this class
    prop_defs = schema.get(class_name, [])
    if not isinstance(prop_defs, list):
        return errors

    # Get the document's properties for this class
    doc_section = doc_props.get(class_name, {})
    if not isinstance(doc_section, dict):
        if prop_defs:
            errors.append(f'Missing "{class_name}" section in document')
        return errors

    for prop_def in prop_defs:
        prop_name = prop_def.get('name', '')
        prop_type = prop_def.get('type', '')
        params = prop_def.get('parameters', '')

        if not prop_name:
            continue

        if prop_name not in doc_section:
            # Property missing — check if it has a default or is required
            errors.append(f'{class_name}.{prop_name}: missing property')
            continue

        value = doc_section[prop_name]

        # Allow None/empty for optional fields
        if value is None or value == '':
            continue

        # Type check
        validator = _TYPE_VALIDATORS.get(prop_type)
        if validator and not validator(value, params):
            errors.append(
                f'{class_name}.{prop_name}: expected type "{prop_type}", '
                f'got {type(value).__name__} ({value!r})'
            )
            continue

        # Parameter constraints
        if prop_type == 'integer' and isinstance(params, list):
            param_err = _check_integer_params(value, params)
            if param_err:
                errors.append(f'{class_name}.{prop_name}: {param_err}')

        if prop_type == 'did_uid' and isinstance(params, (int, float)):
            param_err = _check_did_uid_params(str(value), params)
            if param_err:
                errors.append(f'{class_name}.{prop_name}: {param_err}')

    return errors


def _validate_depends_on(
    doc_props: dict,
    schema: dict,
    session: Optional['Session'] = None,
) -> Dict[str, str]:
    """Validate dependency references.

    Args:
        doc_props: Document properties dict.
        schema: Schema dict with depends_on definitions.
        session: Optional session for database lookups.

    Returns:
        Dict mapping dependency name to status ('ok', 'missing', 'empty', 'skipped').
    """
    results: Dict[str, str] = {}
    schema_deps = schema.get('depends_on', [])
    doc_deps = doc_props.get('depends_on', [])

    if not isinstance(doc_deps, list):
        return results

    for schema_dep in schema_deps:
        dep_name = schema_dep.get('name', '')
        must_not_be_empty = schema_dep.get('mustbenotempty', 0)

        # Find matching doc dependency
        matching = [d for d in doc_deps if d.get('name') == dep_name]

        if not matching:
            if must_not_be_empty:
                results[dep_name] = 'missing dependency declaration'
            else:
                results[dep_name] = 'ok'
            continue

        dep_value = matching[0].get('value', '')

        if not dep_value:
            if must_not_be_empty:
                results[dep_name] = 'empty (required to be non-empty)'
            else:
                results[dep_name] = 'ok'
            continue

        # If session available, verify the referenced document exists
        if session is not None:
            try:
                from .query import Query
                found = session.database_search(
                    Query('base.id') == dep_value
                )
                if found:
                    results[dep_name] = 'ok'
                else:
                    results[dep_name] = f'document {dep_value!r} not found in database'
            except Exception as exc:
                results[dep_name] = f'lookup error: {exc}'
        else:
            results[dep_name] = 'ok'  # Can't verify without session

    return results


def validate(
    doc: 'Document',
    session: Optional['Session'] = None,
) -> ValidationResult:
    """Validate an NDI document against its schema.

    Three-tier validation:
      1. This-class properties: type checking against schema
      2. Superclass properties: walk hierarchy
      3. Dependency references: check depends_on targets exist

    Args:
        doc: NDI Document to validate.
        session: Optional session for dependency checking.

    Returns:
        ValidationResult with is_valid flag and error details.
    """
    result = ValidationResult()
    props = doc.document_properties

    # Load schema for this document
    schema = _get_schema_for_document(doc)
    if schema is None:
        # No schema found — can't validate
        return result

    class_name = schema.get('classname', '')

    # 1. This-class validation
    this_errors = _validate_properties(props, class_name, schema)
    if this_errors:
        result.is_valid = False
        result.errors_this = this_errors

    # 2. Superclass validation
    superclasses = schema.get('superclasses', [])
    for sc_name in superclasses:
        sc_schema = _load_schema(sc_name)
        if sc_schema is None:
            result.errors_super[sc_name] = [f'Schema for superclass "{sc_name}" not found']
            result.is_valid = False
            continue

        sc_errors = _validate_properties(props, sc_name, sc_schema)
        if sc_errors:
            result.errors_super[sc_name] = sc_errors
            result.is_valid = False

    # 3. Dependency validation
    dep_results = _validate_depends_on(props, schema, session)
    for dep_name, status in dep_results.items():
        if status != 'ok':
            result.is_valid = False
    result.errors_depends_on = dep_results

    return result
