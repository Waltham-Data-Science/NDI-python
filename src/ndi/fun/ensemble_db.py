"""Database-backed helpers for ndi.element.ensemble.

MATLAB counterpart: ``src/ndi/+ndi/+fun/+ensemble/`` -- ``allElement``,
``allNTrodes``, ``create``, ``findExisting``, ``load``, ``neuronQuality``,
``plot``, and ``read``.

These live beside the pure ``ndi.fun.ensemble.filter`` (in ``ensemble.py``)
rather than inside it: everything here needs a session, so keeping the pure
selection logic importable without one is worth the split. Every name here is
re-exported from ``ndi.fun.ensemble``, so callers see the single flat
namespace MATLAB's ``+ensemble`` package presents.

Naming follows the parity convention used throughout this port: MATLAB's
camelCase names are preserved (``allElement``, ``findExisting``,
``neuronQuality``) with snake_case aliases beside them, so code written
against either convention reads naturally.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from .ensemble import filter as ensemble_filter

__all__ = [
    "all_element",
    "allElement",
    "all_ntrodes",
    "allNTrodes",
    "create",
    "find_existing",
    "findExisting",
    "load",
    "neuron_quality",
    "neuronQuality",
    "plot",
    "read",
]

#: MATLAB's default for an ensemble's ``value_type``.
DEFAULT_VALUE_TYPE = "spiketimes"

#: The element type that marks a spiking-neuron element.
SPIKES_TYPE = "spikes"

#: The probe type ``allNTrodes`` sweeps.
NTRODE_TYPE = "n-trode"


# ----------------------------------------------------------------------
# small shared helpers
# ----------------------------------------------------------------------
def _element_from_document(doc: Any, session: Any) -> Any:
    """Load an element object FROM its document, preserving its identity.

    Not ``ndi_document2ndi_object``: that maps class name "element" to a
    constructor which builds a BRAND NEW ndi_element from the name, reference
    and type alone. The result gets a fresh id and no underlying element, so
    it reads no data and matches no dependency -- every neuron loaded that way
    silently contributed nothing. ``_load_from_document`` (reached via the
    ``document=`` constructor) restores the stored id, the underlying element
    and the direct flag, which is what makes the epoch resolvable.

    The class comes from the registry when the document names a registered
    one; otherwise ndi_element_timeseries, since every element read here is
    read as a timeseries. (Elements written as plain timeseries record
    ndi_element_class "ndi.element" because ndi_element_timeseries does not
    override it, so the registry alone would strand them without
    readtimeseries.)
    """
    from ..class_registry import get_class
    from ..element_timeseries import ndi_element_timeseries

    props = getattr(doc, "document_properties", {}) or {}
    class_name = (props.get("element", {}) or {}).get("ndi_element_class", "")
    cls = get_class(class_name) if class_name else None
    if cls is None or not hasattr(cls, "readtimeseries"):
        cls = ndi_element_timeseries
    return cls(session=session, document=doc)


def _document_by_id(doc_id: str, session: Any) -> Any:
    from ..query import ndi_query

    docs = session.database_search(ndi_query("base.id") == doc_id)
    if not docs:
        raise ValueError(f"Could not load an element for document id '{doc_id}'.")
    return docs[0]


def _element_object(x: Any, session: Any) -> Any:
    """An element object from an object, a document, or a document id."""
    if hasattr(x, "id") and hasattr(x, "epochtable"):
        return x
    if isinstance(x, str):
        return _element_from_document(_document_by_id(x, session), session)
    if hasattr(x, "document_properties"):
        return _element_from_document(x, session)
    raise TypeError(
        "Elements must be element objects, documents, or document id strings; "
        f"got {type(x).__name__}."
    )


def _element_id(x: Any) -> str:
    """The element document id of an element object or an id string."""
    if isinstance(x, str):
        return x
    ident = getattr(x, "id", None)
    if ident is None:
        raise TypeError(
            "Expected an element object or a document id string; " f"got {type(x).__name__}."
        )
    return ident


def _ensemble_object(x: Any, session: Any) -> Any:
    """An ndi_element_ensemble from an object, a document, or an id."""
    from ..element.ensemble import ndi_element_ensemble

    if isinstance(x, ndi_element_ensemble):
        return x
    obj = _element_object(x, session)
    if not isinstance(obj, ndi_element_ensemble):
        raise TypeError("The provided element is not an ndi_element_ensemble.")
    return obj


def _clock_name(clock: Any) -> str:
    return getattr(clock, "type", None) or str(clock)


# ----------------------------------------------------------------------
# findExisting
# ----------------------------------------------------------------------
def find_existing(session: Any, ensemble_element: Any, *, epochid: str = "") -> list[Any]:
    """The ``ensemble`` map documents belonging to an ensemble element.

    Optionally restricted to one epoch. Returns a list, empty if none. Used by
    :func:`create` and :func:`all_element` to detect whether an ensemble
    already exists for an element and epoch.
    """
    from ..query import ndi_query

    element_id = _element_id(ensemble_element)
    q = ndi_query("").isa("ensemble") & ndi_query("").depends_on("element_id", element_id)
    if epochid:
        q = q & ndi_query("epochid.epochid", "exact_string", epochid, "")
    return session.database_search(q)


findExisting = find_existing


# ----------------------------------------------------------------------
# neuronQuality
# ----------------------------------------------------------------------
def neuron_quality(session: Any, neuron_ids: Sequence[str]) -> tuple[np.ndarray, list[str]]:
    """Spike-sorting quality for each neuron id.

    Returns ``(quality_number, quality_label)``. ``quality_number[i]`` is the
    ``neuron_extracellular`` quality of ``neuron_ids[i]``, or NaN when that
    neuron has no such document; ``quality_label[i]`` is the matching string,
    ``''`` where there is none.

    One search retrieves every ``neuron_extracellular`` document and matches
    by ``element_id``, rather than one query per neuron. A neuron with more
    than one such document raises: that is a real inconsistency, and silently
    taking the first would pick an arbitrary quality.
    """
    from ..query import ndi_query

    ids = list(neuron_ids)
    n = len(ids)
    quality_number = np.full(n, np.nan, dtype=float)
    quality_label = [""] * n

    docs = session.database_search(ndi_query("").isa("neuron_extracellular"))
    if not docs:
        return quality_number, quality_label

    doc_element_ids = [d.dependency_value("element_id", False) for d in docs]

    for i, nid in enumerate(ids):
        matches = [k for k, eid in enumerate(doc_element_ids) if eid == nid]
        if not matches:
            continue
        if len(matches) > 1:
            raise ValueError(
                f"Neuron {nid} has {len(matches)} neuron_extracellular documents; "
                "expected at most one."
            )
        ne = docs[matches[0]].document_properties["neuron_extracellular"]
        quality_number[i] = ne["quality_number"]
        quality_label[i] = ne["quality_label"]

    return quality_number, quality_label


neuronQuality = neuron_quality


# ----------------------------------------------------------------------
# load
# ----------------------------------------------------------------------
def _clock_index(entry: Mapping[str, Any], clockname: str) -> int | None:
    """Index of CLOCKNAME within an epochtable entry's clock list."""
    clocks = entry.get("epoch_clock") or []
    for i, c in enumerate(clocks):
        if _clock_name(c) == clockname:
            return i
    return None


def load(
    session: Any,
    element: Any,
    epochid: str,
    *,
    neurons: Sequence[Any] | None = None,
    clocktype: str = "",
    value_type: str = DEFAULT_VALUE_TYPE,
    value_description: str = "",
    verbose: bool = False,
) -> tuple[Any, list[str], list[str], dict[str, Any], list[np.ndarray]]:
    """Build the spiking ensemble of every neuron recorded in an epoch.

    Finds the spiking-neuron elements built on ELEMENT (type ``'spikes'`` with
    ELEMENT as their underlying element), reads each one's spike times against
    a time reference on ELEMENT's epoch -- so every neuron's spikes come back
    in the SAME clock and are directly comparable -- and packs them.

    Returns ``(activity, neuron_ids, neuron_names, info, spike_rows)`` where
    ``activity`` is an N-by-Smax sparse matrix of spike times, zero-padded on
    the right, and ``spike_rows[i]`` is neuron i's times without the padding.

    A neuron that was not recorded during EPOCHID is skipped rather than
    raising: an ensemble is the neurons that were actually there.
    """
    from scipy.sparse import lil_matrix

    from ..query import ndi_query
    from ..time.clocktype import ndi_time_clocktype
    from ..time.timereference import ndi_time_timereference

    element_obj = _element_object(element, session)

    et, _ = element_obj.epochtable()
    entry = next((e for e in et if e.get("epoch_id") == epochid), None)
    if entry is None:
        raise ValueError(f"Element '{element_obj.elementstring()}' has no epoch '{epochid}'.")

    if not clocktype:
        # Prefer dev_local_time -- the clock readtimeseries resolves epochs
        # through -- when the epoch has it, so the stored ensemble epoch can be
        # read back. Fall back to the epoch's first clock otherwise.
        ci = _clock_index(entry, "dev_local_time")
        if ci is None:
            ci = 0
    else:
        ci = _clock_index(entry, clocktype)
        if ci is None:
            raise ValueError(f"The epoch does not have a clock of type '{clocktype}'.")

    clocks = entry.get("epoch_clock") or []
    ref_clock = clocks[ci]
    if not isinstance(ref_clock, ndi_time_clocktype):
        ref_clock = ndi_time_clocktype(_clock_name(ref_clock))
    clockname = _clock_name(ref_clock)

    ranges = entry.get("t0_t1") or []
    ref_t0_t1 = list(ranges[ci]) if ci < len(ranges) else [0.0, 0.0]

    timeref = ndi_time_timereference(element_obj, ref_clock, epochid, 0)

    # By default the ensemble is the spiking elements built ON this element,
    # not every 'spikes' element in the session.
    if neurons is None or len(neurons) == 0:
        q = (
            ndi_query("").isa("element")
            & ndi_query("element.type", "exact_string", SPIKES_TYPE, "")
            & ndi_query("").depends_on("underlying_element_id", element_obj.id)
        )
        neuron_docs = session.database_search(q)
        candidates = [_element_from_document(d, session) for d in neuron_docs]
    else:
        candidates = list(neurons)

    if verbose:
        print(
            f"ndi.fun.ensemble.load: considering {len(candidates)} candidate "
            f"cell(s) for epoch {epochid}."
        )

    spike_rows: list[np.ndarray] = []
    neuron_ids: list[str] = []
    neuron_names: list[str] = []
    for j, cand in enumerate(candidates):
        e = _element_object(cand, session)
        if verbose:
            print(
                f"ndi.fun.ensemble.load: reading cell {j + 1} of "
                f"{len(candidates)} ({e.elementstring()})..."
            )
        try:
            # readtimeseries against a timereference returns the spike times in
            # the reference clock, and fails if this neuron was not recorded in
            # the reference epoch.
            _, st, _ = e.readtimeseries(timeref, -np.inf, np.inf)
        except Exception as exc:  # noqa: BLE001 - a skip, not a swallow
            if verbose:
                print(
                    f"ndi.fun.ensemble.load:   skipping {e.elementstring()} "
                    f"(not recorded in epoch {epochid}): {exc}"
                )
            continue
        st = np.asarray(st, dtype=float).ravel()
        if verbose:
            print(f"ndi.fun.ensemble.load:   {st.size} spike(s).")
        spike_rows.append(st)
        neuron_ids.append(e.id)
        neuron_names.append(e.elementstring())

    n = len(spike_rows)
    smax = max((r.size for r in spike_rows), default=0)
    activity = lil_matrix((n, max(smax, 1)), dtype=float)
    for k, row in enumerate(spike_rows):
        if row.size:
            activity[k, : row.size] = row
    activity = activity.tocsr()

    if verbose:
        print(f"ndi.fun.ensemble.load: built an ensemble of {n} neuron(s) " f"for epoch {epochid}.")

    vdesc = value_description or (f"time of the n-th spike of neuron i, in the {clockname} clock")
    info = {
        "num_neurons": n,
        "num_dimensions": 2,
        "value_type": value_type,
        "value_description": vdesc,
        "clocktype": clockname,
        "clock": ref_clock,
        "t0_t1": ref_t0_t1,
    }
    return activity, neuron_ids, neuron_names, info, spike_rows


# ----------------------------------------------------------------------
# create
# ----------------------------------------------------------------------
def create(
    session: Any,
    element: Any,
    epochid: str,
    *,
    check_existing: bool = True,
    verbose: bool = False,
    **load_options: Any,
) -> tuple[Any, list[Any]]:
    """Build an ensemble element's epoch and store it.

    Finds or creates the ensemble element for ELEMENT (one per element, named
    ``<element.name>_ensemble``), reads the epoch's spiking activity with
    :func:`load`, and stores it as a marked point process plus a per-epoch map
    document.

    Returns ``(ensemble_element, existing)``. ``existing`` is the map
    documents already present for this epoch; when ``check_existing`` is True
    and it is non-empty, this raises rather than writing a second ensemble for
    the same epoch.
    """
    from ..element.ensemble import ndi_element_ensemble

    element_obj = _element_object(element, session)
    ens = _find_or_create_ensemble_element(session, element_obj)

    existing = find_existing(session, ens, epochid=epochid)
    if existing and check_existing:
        raise ValueError(
            f"An ensemble already exists for epoch '{epochid}' of "
            f"{element_obj.elementstring()}. Pass check_existing=False to add "
            "another, or remove the existing one first."
        )

    _, neuron_ids, neuron_names, info, spike_rows = load(
        session, element_obj, epochid, verbose=verbose, **load_options
    )

    if verbose:
        print(
            f"ndi.fun.ensemble.create: storing {len(neuron_ids)} neuron(s) " f"for epoch {epochid}."
        )

    ens.add_ensemble_epoch(
        epochid,
        [info["clock"]],
        [tuple(info["t0_t1"])],
        neuron_ids,
        neuron_names,
        spike_rows,
        value_type=info["value_type"],
        value_description=info["value_description"],
        ensemble_name=f"{element_obj.name}_ensemble",
    )
    assert isinstance(ens, ndi_element_ensemble)
    return ens, existing


def _find_or_create_ensemble_element(session: Any, element_obj: Any) -> Any:
    """The ensemble element for ELEMENT, creating and registering it if new.

    One ensemble element per element, named ``<name>_ensemble``. An existing
    one is loaded rather than duplicated -- MATLAB's constructor does the same
    lookup, so calling create twice does not produce two ensemble elements.
    """
    from ..element.ensemble import ndi_element_ensemble
    from ..query import ndi_query

    name = f"{element_obj.name}_ensemble"
    q = (
        ndi_query("").isa("element")
        & ndi_query("element.name", "exact_string", name, "")
        & ndi_query("element.reference", "exact_number", element_obj.reference, "")
        & ndi_query("").depends_on("underlying_element_id", element_obj.id)
    )
    docs = session.database_search(q)
    if docs:
        return ndi_element_ensemble(session, docs[0])

    ens = ndi_element_ensemble(
        session,
        name,
        element_obj.reference,
        element_obj,
    )
    session.database_add(ens.newdocument())
    return ens


# ----------------------------------------------------------------------
# read
# ----------------------------------------------------------------------
def read(
    session: Any,
    ensemble_element: Any,
    epoch: Any,
    *,
    include_names: Sequence[str] | None = None,
    exclude_names: Sequence[str] | None = None,
    include_index: Any = None,
    exclude_index: Any = None,
    include_ids: Sequence[str] | None = None,
    exclude_ids: Sequence[str] | None = None,
    min_quality: float | None = None,
    quality_label: Any = "",
    keep_unrated: bool = False,
) -> dict[str, Any]:
    """Read one epoch of an ensemble, optionally selecting neurons.

    Returns a dict with ``activity``, ``neuron_ids``, ``neuron_names``,
    ``epoch``, and ``info``.

    Quality acts as a hard constraint: a neuron failing ``min_quality`` or
    ``quality_label`` is dropped regardless of the include options, by being
    folded into the exclusions. Unrated neurons (no ``neuron_extracellular``
    document) are dropped by an active quality filter unless ``keep_unrated``.
    """
    ens = _ensemble_object(ensemble_element, session)

    activity, neuron_ids = ens.spike_matrix(epoch)
    mapdoc = ens.epoch_ensemble_doc(epoch)

    E: dict[str, Any] = {
        "activity": activity,
        "neuron_ids": neuron_ids,
        "neuron_names": ens.neuron_names(epoch),
        "epoch": ens._resolve_epoch_id(epoch),
        "info": mapdoc.document_properties["ensemble"],
    }

    use_quality = min_quality is not None or bool(quality_label)
    any_filter = use_quality or any(
        x is not None and len(np.atleast_1d(x)) > 0
        for x in (
            include_names,
            exclude_names,
            include_index,
            exclude_index,
            include_ids,
            exclude_ids,
        )
    )
    if not any_filter:
        return E

    excl_ids = list(exclude_ids) if exclude_ids else []
    if use_quality:
        qnum, qlabel = neuron_quality(session, E["neuron_ids"])
        qmask = np.ones(len(E["neuron_ids"]), dtype=bool)
        if min_quality is not None:
            # NaN >= x is False, so unrated neurons fail here by construction;
            # keep_unrated below is what puts them back.
            qmask &= qnum >= min_quality
        if quality_label:
            wanted = [quality_label] if isinstance(quality_label, str) else list(quality_label)
            qmask &= np.array([lab in wanted for lab in qlabel], dtype=bool)
        if keep_unrated:
            qmask |= np.isnan(qnum)
        excl_ids += [nid for nid, ok in zip(E["neuron_ids"], qmask) if not ok]

    return ensemble_filter(
        E,
        include_names=include_names,
        exclude_names=exclude_names,
        include_index=include_index,
        exclude_index=exclude_index,
        include_ids=include_ids,
        exclude_ids=excl_ids,
    )


# ----------------------------------------------------------------------
# allElement / allNTrodes
# ----------------------------------------------------------------------
def all_element(
    session: Any,
    element: Any,
    *,
    if_exists: str = "skip",
    verbose: bool = False,
    **create_options: Any,
) -> Any:
    """Build an ensemble epoch for every epoch of ELEMENT.

    ``if_exists`` says what to do for an epoch that already has an ensemble:
    ``'skip'`` (default), ``'error'``, or ``'replace'`` (remove the existing
    map and epoch documents, then rebuild).
    """
    if if_exists not in ("skip", "error", "replace"):
        raise ValueError(f"if_exists must be 'skip', 'error', or 'replace'; got {if_exists!r}.")

    element_obj = _element_object(element, session)
    ens = _find_or_create_ensemble_element(session, element_obj)

    et, _ = element_obj.epochtable()
    for entry in et:
        epochid = entry.get("epoch_id")
        existing = find_existing(session, ens, epochid=epochid)
        if existing:
            if if_exists == "error":
                raise ValueError(
                    f"An ensemble already exists for epoch '{epochid}' of "
                    f"{element_obj.elementstring()}."
                )
            if if_exists == "skip":
                if verbose:
                    print(
                        f"ndi.fun.ensemble.allElement: epoch {epochid} already "
                        "has an ensemble; skipping."
                    )
                continue
            _remove_ensemble_epoch(session, ens, epochid, existing)

        create(
            session,
            element_obj,
            epochid,
            check_existing=False,
            verbose=verbose,
            **create_options,
        )

    return ens


allElement = all_element


def _remove_ensemble_epoch(session: Any, ens: Any, epochid: str, map_docs: Sequence[Any]) -> None:
    """Delete an epoch's map documents and its element_epoch document.

    Both go, and the map goes first: it depends on the element_epoch document,
    so removing the epoch first would leave the map dangling for as long as
    the two removals take.
    """
    for d in map_docs:
        session.database_rm(d)
    epoch_doc = ens._epoch_document(epochid)
    if epoch_doc is not None:
        session.database_rm(epoch_doc)
    ens.resetepochtable()


def all_ntrodes(
    session: Any, *, if_exists: str = "skip", verbose: bool = False, **create_options: Any
) -> list[Any]:
    """Build ensemble elements for every n-trode probe in a session."""
    from ..query import ndi_query

    q = ndi_query("").isa("element") & ndi_query("element.type", "exact_string", NTRODE_TYPE, "")
    docs = session.database_search(q)
    if verbose:
        print(f"ndi.fun.ensemble.allNTrodes: found {len(docs)} n-trode(s).")

    out = []
    for d in docs:
        probe = _element_from_document(d, session)
        out.append(
            all_element(session, probe, if_exists=if_exists, verbose=verbose, **create_options)
        )
    return out


allNTrodes = all_ntrodes


# ----------------------------------------------------------------------
# plot
# ----------------------------------------------------------------------
def plot(
    E: Mapping[str, Any],
    *,
    ax: Any = None,
    color: Any = "k",
    marker_size: float = 2.0,
    show_names: bool = True,
) -> Any:
    """Raster-plot an ensemble structure as returned by :func:`read`.

    One row per neuron, one tick per spike. Returns the axes.

    matplotlib is imported here rather than at module scope so that importing
    ``ndi.fun.ensemble`` on a headless machine, or one without matplotlib,
    does not fail for the sake of a function the caller may never use.
    """
    import matplotlib.pyplot as plt

    if ax is None:
        _, ax = plt.subplots()

    activity = E["activity"]
    names = list(E.get("neuron_names") or [])
    dense = activity.toarray() if hasattr(activity, "toarray") else np.asarray(activity)

    for i in range(dense.shape[0]):
        row = dense[i]
        # A zero is padding, not a spike at time zero -- the sparse export
        # cannot tell the two apart. Same limitation as MATLAB's.
        spikes = row[row != 0]
        if spikes.size:
            ax.plot(
                spikes,
                np.full(spikes.size, i + 1),
                linestyle="none",
                marker="|",
                markersize=marker_size * 4,
                color=color,
            )

    ax.set_xlabel("time (s)")
    ax.set_ylabel("neuron")
    ax.set_ylim(0.5, max(dense.shape[0], 1) + 0.5)
    if show_names and names:
        ax.set_yticks(range(1, len(names) + 1))
        ax.set_yticklabels(names)
    return ax
