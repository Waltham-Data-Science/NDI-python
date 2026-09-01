"""ndi.fun.cache - clearing NDI's in-memory caches.

MATLAB counterpart: ``src/ndi/+ndi/+fun/clearAllCaches.m``

NDI builds up in-memory caches over a long-lived session: a shared cache
singleton, several lazily-built lookup tables held in module globals, and
memoized lookups. This clears them, which is what you want when definitions,
schemas or path contents have changed on disk but a running process is still
serving stale copies.

WHAT IS AND IS NOT MIRRORED
MATLAB clears five things. Four have direct counterparts here:

  1. the global cache singleton (``ndi.common.getCache``)          -> cleared
  2. the probe-type map (``ndi.probe.getProbeTypeMap``)            -> cleared
  3. the calculator subclass list                                  -> N/A
  4. the document-definition memo / DID file cache                 -> partial
  5. the database hierarchy                                        -> N/A

Items 3 and 5 have no Python counterpart to clear: neither
``find_calculator_subclasses`` nor ``getDatabaseHierarchy`` has been ported,
so there is no cache for them to hold. Item 4 clears this side's schema
memo; DID's own file cache is not reachable from here and is left alone.
Two caches exist here that MATLAB does not have in this function -- the
class registry and the ontology lookup memo -- and both are cleared, since
the point of the function is that nothing stale survives it.

That inventory is stated rather than glossed because the function's value is
entirely in what it covers: a "clear all" that quietly misses a cache is
worse than one that says which caches it means.
"""

from __future__ import annotations

from typing import Any

__all__ = ["clear_all_caches", "clearAllCaches"]


def clear_all_caches(*objects: Any, verbose: bool = False) -> list[str]:
    """Clear NDI's in-memory caches.

    Args:
        *objects: Optional sessions or caches whose own cache should also be
            cleared, mirroring MATLAB's ``clearAllCaches(OBJ1, OBJ2, ...)``.
            An object with a ``cache`` attribute has that cleared; an object
            with its own ``clear`` method is cleared directly.
        verbose: Print each cache as it is cleared.

    Returns:
        The names of the caches actually cleared, in order. Returned rather
        than discarded so a caller (or a test) can tell what happened, and so
        a cache that silently stops being cleared is visible.
    """
    cleared: list[str] = []

    def note(name: str) -> None:
        cleared.append(name)
        if verbose:
            print(f"ndi.fun.clear_all_caches: cleared {name}")

    # 1. The global cache singleton. Dropped rather than emptied, so the next
    #    getCache() builds a fresh one -- MATLAB's clear does the same.
    try:
        from .. import common

        if getattr(common, "_cache_singleton", None) is not None:
            common._cache_singleton = None
            note("ndi.common.getCache singleton")
    except Exception:  # noqa: BLE001 - a missing cache is not a failure
        pass

    # 2. The probe-type map.
    try:
        from .. import probe

        if getattr(probe, "_PROBE_TYPE_MAP", None) is not None:
            probe._PROBE_TYPE_MAP = None
            note("ndi.probe.getProbeTypeMap map")
    except Exception:  # noqa: BLE001
        pass

    # 4. The schema memo (this side's half of MATLAB's definition memo).
    try:
        from .. import validate

        if getattr(validate, "_schema_cache", None):
            validate._schema_cache.clear()
            note("ndi.validate schema cache")
    except Exception:  # noqa: BLE001
        pass

    # Python-only: the class registry.
    try:
        from .. import class_registry

        if getattr(class_registry, "_REGISTRY", None) is not None:
            class_registry._REGISTRY = None
            note("ndi.class_registry registry")
    except Exception:  # noqa: BLE001
        pass

    # Python-only: the ontology lookup memo.
    try:
        from .. import ontology

        if getattr(ontology, "_lookup_cache", None):
            ontology._lookup_cache.clear()
            note("ndi.ontology lookup cache")
    except Exception:  # noqa: BLE001
        pass

    for obj in objects:
        cache = getattr(obj, "cache", None)
        target = cache if cache is not None else obj
        clear = getattr(target, "clear", None)
        if callable(clear):
            clear()
            note(f"{type(obj).__name__} cache")

    return cleared


#: MATLAB-cased alias, as elsewhere in this port.
clearAllCaches = clear_all_caches
