"""
ndi.ontology - Ontology lookup system with 15 providers.

MATLAB equivalent: +ndi/ontology.m, +ndi/+ontology/*.m

Unified interface for looking up terms across multiple biomedical ontologies.

Usage::

    from ndi.ontology import lookup
    result = lookup('CL:0000540')  # Cell Ontology: neuron
    result = lookup('NDIC:1')      # NDI Controlled Vocabulary
"""

from __future__ import annotations

import json
from typing import Any

import pydantic

from .providers import PROVIDER_REGISTRY

# ---------------------------------------------------------------------------
# Lookup result type
# ---------------------------------------------------------------------------


class OntologyResult:
    """Result from an ontology lookup."""

    __slots__ = ("id", "name", "prefix", "definition", "synonyms", "short_name")

    def __init__(
        self,
        id: str = "",
        name: str = "",
        prefix: str = "",
        definition: str = "",
        synonyms: list[str] | None = None,
        short_name: str = "",
    ):
        self.id = id
        self.name = name
        self.prefix = prefix
        self.definition = definition
        self.synonyms = synonyms or []
        self.short_name = short_name

    def __repr__(self) -> str:
        return f"OntologyResult(id={self.id!r}, name={self.name!r})"

    def __bool__(self) -> bool:
        return bool(self.id or self.name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "prefix": self.prefix,
            "definition": self.definition,
            "synonyms": self.synonyms,
            "short_name": self.short_name,
        }


# ---------------------------------------------------------------------------
# Prefix registry
# ---------------------------------------------------------------------------


# Prefix -> ontology-name map (case-insensitive at lookup time). This is the
# in-memory cache; it is the SINGLE SOURCE'd entirely from
# ndi_common/ontology/ontology_list.json, which is itself vendored verbatim from
# the canonical ndi-ontology-matlab package (Waltham-Data-Science/ndi-ontology-matlab)
# and is the single source of truth shared by both the MATLAB and Python
# consumers. There is intentionally no hardcoded prefix table here: a hardcoded
# copy previously duplicated (and drifted from) the JSON. To add or change a
# prefix mapping, edit it in ndi-ontology-matlab and re-vendor ontology_list.json.
_PREFIX_MAP: dict[str, str] = {}


def _load_prefix_map() -> dict[str, str]:
    """Return the prefix -> ontology-name map, loading it once from the JSON.

    The mappings come solely from ``ndi_common/ontology/ontology_list.json`` (the
    single source vendored from ndi-ontology-matlab); the in-memory ``_PREFIX_MAP``
    is populated on first use and reused thereafter.
    """
    if _PREFIX_MAP:
        return _PREFIX_MAP
    try:
        from ndi.common import ndi_common_PathConstants

        json_path = ndi_common_PathConstants.COMMON_FOLDER / "ontology" / "ontology_list.json"
        with open(json_path) as f:
            data = json.load(f)
        for mapping in data.get("prefix_ontology_mappings", []):
            prefix = mapping.get("prefix", "")
            name = mapping.get("ontology_name", "")
            if prefix and name:
                _PREFIX_MAP[prefix] = name
    except Exception as exc:  # pragma: no cover - packaged resource should exist
        import logging

        logging.getLogger(__name__).warning(
            "Could not load ontology prefix mappings from ontology_list.json: %s", exc
        )
    return _PREFIX_MAP


# ---------------------------------------------------------------------------
# Main lookup (with LRU cache)
# ---------------------------------------------------------------------------

_lookup_cache: dict[str, OntologyResult] = {}
_CACHE_MAX = 100


@pydantic.validate_call
def lookup(lookup_string: str) -> OntologyResult:
    """Look up a term in the appropriate ontology.

    MATLAB equivalent: ndi.ontology.lookup

    Args:
        lookup_string: Prefixed string like ``'CL:0000540'`` or ``'NDIC:1'``.
            Use ``'clear'`` to flush the cache.

    Returns:
        OntologyResult with id, name, prefix, definition, synonyms.
    """
    if lookup_string == "clear":
        _lookup_cache.clear()
        return OntologyResult()

    # Check cache
    if lookup_string in _lookup_cache:
        return _lookup_cache[lookup_string]

    # Parse prefix
    if ":" not in lookup_string:
        return OntologyResult()

    prefix, remainder = lookup_string.split(":", 1)

    # Load prefix map
    prefix_map = _load_prefix_map()

    # Case-insensitive prefix match
    provider_name = None
    for k, v in prefix_map.items():
        if k.lower() == prefix.lower():
            provider_name = v
            break

    if provider_name is None:
        return OntologyResult()

    # Get provider
    provider_cls = PROVIDER_REGISTRY.get(provider_name)
    if provider_cls is None:
        return OntologyResult()

    provider = provider_cls()
    try:
        result = provider.lookup_term(remainder, prefix)
    except Exception:
        result = OntologyResult()

    # Cache (with eviction)
    if len(_lookup_cache) >= _CACHE_MAX:
        # Remove oldest entry
        oldest = next(iter(_lookup_cache))
        del _lookup_cache[oldest]
    _lookup_cache[lookup_string] = result

    return result


def clearCache() -> None:
    """Clear all ontology caches.

    MATLAB equivalent: ndi.ontology.clearCache
    """
    _lookup_cache.clear()


__all__ = ["OntologyResult", "lookup", "clearCache"]
