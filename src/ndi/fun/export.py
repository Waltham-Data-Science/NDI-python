"""
ndi.fun.export - Export NDI data into other analysis packages' formats.

MATLAB equivalent: +ndi/+fun/+export/

Provides :func:`blech_clust_write`, the low-level writer for blech_clust HMM
HDF5 files, and :func:`blech_clust`, the wrapper that assembles its arrays
from an NDI stimulator and probe.

The wrapper was previously absent here, because it needs
``ndi.fun.ensemble.load`` / ``read`` / ``filter`` / ``neuron_quality``,
``ndi.element.ensemble`` and ``ndi.app.stimulus.decoder``, none of which had
been ported. They have been, so it is present now.

The split between the two is worth keeping: MATLAB factored the writer to
have no session, syncgraph or database dependencies precisely so it could be
used and tested on its own, and the tests here take the same advantage --
every binning rule is pinned against the writer directly, and the wrapper is
tested for what only it does, which is finding the right documents and
converting the stimulus times into the ensemble's clock.

``h5py`` is not declared in pyproject because ``vhlab-toolbox-python``, a core
dependency, already requires it; the import is guarded anyway so a broken
environment produces a useful message rather than a traceback from the middle
of a write.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

try:
    import h5py
except ImportError:  # pragma: no cover - exercised only without h5py
    h5py = None  # type: ignore[assignment]

__all__ = ["blech_clust", "blech_clust_write"]

# The compound type MATLAB builds by hand with H5T.create: three native ints.
_UNIT_DESCRIPTOR_DTYPE = np.dtype(
    [("single_unit", "i4"), ("regular_spiking", "i4"), ("fast_spiking", "i4")]
)


def _require_h5py() -> None:
    if h5py is None:
        raise ImportError("h5py is required for ndi.fun.export. Install it with: pip install h5py")


def _matlab_round(x: Any) -> np.ndarray:
    """Round half AWAY FROM ZERO, as MATLAB's ``round`` does.

    numpy rounds half to even, so ``np.round(0.5)`` is 0 where MATLAB's
    ``round(0.5)`` is 1. Spike times land exactly on a half-sample often
    enough that this is a real difference and not a curiosity: at 30 kHz a
    time recorded to microsecond precision hits a half sample whenever it is
    an odd multiple of 1/60000 s.
    """
    a = np.asarray(x, dtype=float)
    return np.where(a >= 0, np.floor(a + 0.5), np.ceil(a - 0.5))


def blech_clust_write(
    outputfile: str | os.PathLike,
    unit_spiketimes: Sequence[Any],
    unit_info: Sequence[Mapping[str, Any]],
    onset_times: Any,
    trial_stimid: Any,
    stimid_tastant: Mapping[Any, str],
    *,
    pre_stim: float = 2000.0,
    post_stim: float = 5000.0,
    sample_rate: float = 30000.0,
    stimulus_order: Any = None,
    include_stimids: Any = None,
    epoch_id: str = "",
    verbose: bool = True,
) -> None:
    """Write a blech_clust HMM HDF5 file from prepared arrays.

    MATLAB equivalent: ``ndi.fun.export.blech_clust_write``

    Given ensemble spike times and per-trial stimulus identities and delivery
    times already expressed in a single common clock in seconds, bins the
    activity into blech_clust's binary millisecond ``spike_array`` layout and
    writes *outputfile* (overwritten if it exists).

    Args:
        outputfile: Path of the HDF5 file to write.
        unit_spiketimes: One entry per unit; each a sequence of spike times in
            seconds, in the common clock.
        unit_info: One mapping per unit with keys ``name``, ``single_unit``,
            ``regular_spiking`` and ``fast_spiking``; the last three are
            written to ``/unit_descriptor``.
        onset_times: Stimulus delivery times, seconds, one per trial.
        trial_stimid: Integer stimulus id of each trial.
        stimid_tastant: Maps a stimid to a tastant name, for the ``dig_in``
            group's ``tastant`` attribute. MATLAB uses a ``containers.Map``.
        pre_stim: Milliseconds retained before delivery (MATLAB ``preStim``).
            Delivery is placed at column ``pre_stim`` of ``spike_array``.
        post_stim: Milliseconds retained after delivery (MATLAB ``postStim``).
        sample_rate: Acquisition sample rate in Hz, for ``/sorted_units``
            (MATLAB ``sampleRate``).
        stimulus_order: Order of stimids mapping onto ``dig_in_0``,
            ``dig_in_1``, ...; if None, the unique stimids present, ascending
            (MATLAB ``stimulusOrder``).
        include_stimids: If given, restrict exported stimids to these
            (MATLAB ``includeStimids``).
        epoch_id: Recorded as the ``/ndi_epochid`` root attribute.
        verbose: Print progress, as MATLAB's ``verbose`` option does.

    Raises:
        ImportError: If h5py is not installed.
        ValueError: If no tastant stimuli remain to export.

    **Axis order of** ``/spike_trains/dig_in_<N>/spike_array``

    blech_clust requires the raster to have numpy shape
    ``(n_trials, n_units, trial_duration_ms)``, and that is exactly the shape
    written here -- h5py is row-major, so no transpose is involved on this
    side.

    The MATLAB writer reaches the same file by the opposite route: it is
    column-major, so it permutes to ``[trial_dur_ms n_units n_trials]`` and
    HDF5 reverses that back. Reading the file with MATLAB's ``h5read``
    therefore returns ``[trial_dur_ms n_units n_trials]``, and that is
    correct. A Python consumer must **not** apply a compensating
    ``np.transpose(spike_array, (2, 1, 0))``: the file is already in blech's
    order. That transpose was the workaround for VH-Lab/NDI-matlab#855, which
    is fixed; applying it now transposes correct data back into the bug.

    A tastant with no trials is skipped with a warning, because HDF5 datasets
    cannot have a zero-length dimension. **Its ``dig_in`` index is still
    consumed**, so the numbering has a gap rather than closing up -- matching
    MATLAB, where the loop counter names the group before the skip.
    """
    _require_h5py()

    pre_stim_ms = int(_matlab_round(pre_stim))
    post_stim_ms = int(_matlab_round(post_stim))
    trial_dur_ms = pre_stim_ms + post_stim_ms
    n_units = len(unit_spiketimes)

    onset_times = np.asarray(onset_times, dtype=float).ravel()
    trial_stimid = np.asarray(trial_stimid, dtype=float).ravel()

    if stimulus_order is not None and len(np.asarray(stimulus_order).ravel()):
        dig_in_stimids = np.asarray(stimulus_order, dtype=float).ravel()
    else:
        dig_in_stimids = np.unique(trial_stimid)
    if include_stimids is not None and len(np.asarray(include_stimids).ravel()):
        wanted = np.asarray(include_stimids, dtype=float).ravel()
        dig_in_stimids = dig_in_stimids[np.isin(dig_in_stimids, wanted)]
    if dig_in_stimids.size == 0:
        raise ValueError("No tastant stimuli were found to export.")

    outputfile = os.fspath(outputfile)
    if os.path.exists(outputfile):
        os.remove(outputfile)

    with h5py.File(outputfile, "w") as handle:
        for n, this_stimid in enumerate(dig_in_stimids):
            trials = np.flatnonzero(trial_stimid == this_stimid)
            n_trials = trials.size
            group_name = f"/spike_trains/dig_in_{n}"  # blech is 0-indexed

            if n_trials == 0:
                warnings.warn(
                    f"stimid {this_stimid:g} has no trials; skipping dig_in_{n}.",
                    stacklevel=2,
                )
                continue

            spike_array = np.zeros((n_trials, n_units, trial_dur_ms), dtype=np.uint8)
            for ti, trial in enumerate(trials):
                win_start = onset_times[trial] - pre_stim_ms / 1000.0  # seconds
                for u in range(n_units):
                    st = np.asarray(unit_spiketimes[u], dtype=float).ravel()
                    if st.size == 0:
                        continue
                    # ms bin index; delivery lands in column pre_stim_ms.
                    # MATLAB adds 1 for its 1-based columns and keeps
                    # 1 <= idx <= trial_dur_ms; this is the 0-based form of
                    # the same window.
                    idx = np.floor((st - win_start) * 1000.0).astype(np.int64)
                    idx = idx[(idx >= 0) & (idx < trial_dur_ms)]
                    spike_array[ti, u, idx] = 1

            group = handle.require_group(group_name)
            group.create_dataset("spike_array", data=spike_array, dtype="uint8")

            this_tastant = "unknown"
            for key, value in stimid_tastant.items():
                if float(key) == float(this_stimid) and value:
                    this_tastant = value
                    break

            # MATLAB's h5writeatt stores a numeric scalar as a double; these
            # are written as float64 so the two files carry the same types.
            group.attrs["stimid"] = np.float64(this_stimid)
            group.attrs["tastant"] = this_tastant
            group.attrs["n_trials"] = np.float64(n_trials)
            group.attrs["pre_stim_ms"] = np.float64(pre_stim_ms)
            group.attrs["post_stim_ms"] = np.float64(post_stim_ms)

            if verbose:
                print(
                    f"  dig_in_{n}: stimid {this_stimid:g} ({this_tastant}), "
                    f"{n_trials} trials, {n_units} units, {trial_dur_ms} ms/trial."
                )

        if verbose:
            print("Writing /sorted_units and /unit_descriptor...")
        _write_units(handle, unit_spiketimes, unit_info, sample_rate)

        handle.attrs["source"] = "NDI-python ndi.fun.export.blech_clust"
        handle.attrs["ndi_epochid"] = epoch_id
        handle.attrs["sample_rate_hz"] = np.float64(sample_rate)

    if verbose:
        print(f"Wrote blech_clust HDF5 file: {outputfile}")


def _write_units(
    handle: Any,
    unit_spiketimes: Sequence[Any],
    unit_info: Sequence[Mapping[str, Any]],
    sample_rate: float,
) -> None:
    """Write /sorted_units/unitNNN/times and the /unit_descriptor table."""
    for u, times in enumerate(unit_spiketimes):
        st = np.asarray(times, dtype=float).ravel()
        samples = _matlab_round(st * sample_rate)
        samples = samples[samples >= 0].astype(np.uint64)
        group = handle.require_group(f"/sorted_units/unit{u:03d}")
        if samples.size == 0:
            # A zero-length dimension is not allowed, so MATLAB writes a
            # single 0 rather than an empty dataset.
            group.create_dataset("times", data=np.zeros(1, dtype=np.uint64))
        else:
            group.create_dataset("times", data=samples)

    n_units = len(unit_info)
    table = np.zeros(max(n_units, 1), dtype=_UNIT_DESCRIPTOR_DTYPE)
    for i, info in enumerate(unit_info):
        table[i] = (
            np.int32(info["single_unit"]),
            np.int32(info["regular_spiking"]),
            np.int32(info["fast_spiking"]),
        )
    # With no units MATLAB creates the dataset and never writes it, so HDF5
    # leaves one zero-filled row; the zeros() above matches that.
    handle.create_dataset("unit_descriptor", data=table)


# ======================================================================
# blech_clust -- the session-backed wrapper over blech_clust_write
# ======================================================================
#: Quality labels that mark a kept neuron as a single unit in
#: ``/unit_descriptor``. Matched case-insensitively, as MATLAB does.
DEFAULT_SINGLE_UNIT_LABELS = ("single", "good", "excellent")

#: blech_clust hard-codes a 30 kHz acquisition rate (30 samples/ms).
BLECH_SAMPLE_RATE = 30000.0


def blech_clust(
    stimulator: Any,
    probe: Any,
    epoch_id: str,
    outputfile: str | os.PathLike,
    *,
    sample_rate: float = BLECH_SAMPLE_RATE,
    pre_stim: float = 2000.0,
    post_stim: float = 5000.0,
    ensemble: Any = None,
    min_quality: float | None = None,
    quality_label: Any = "",
    keep_unrated: bool = False,
    include_names: Sequence[str] | None = None,
    exclude_names: Sequence[str] | None = None,
    include_ids: Sequence[str] | None = None,
    exclude_ids: Sequence[str] | None = None,
    include_index: Any = None,
    exclude_index: Any = None,
    single_unit_labels: Sequence[str] = DEFAULT_SINGLE_UNIT_LABELS,
    stimulus_order: Any = None,
    include_stimids: Any = None,
    tastant_field: str = "tastant",
    stimid_field: str = "stimid",
    verbose: bool = True,
) -> None:
    """Export an NDI ensemble + tastant stimulus epoch to a blech_clust file.

    MATLAB counterpart: ``ndi.fun.export.blech_clust``.

    Pulls the sorted-unit ensemble recorded on PROBE and the tastant stimulus
    identities and delivery times reported by STIMULATOR, for one epoch, and
    writes the HDF5 layout the blech_clust HMM code reads
    (https://github.com/vh-lab/blech_clust).

    Where the pieces come from:

    * **ensemble activity** -- ``ndi.fun.ensemble.load`` on PROBE for this
      epoch, or ``ndi.fun.ensemble.read`` when ``ensemble`` names one.
    * **stimulus identity** -- the ``stimid`` parameter of each stimulus in
      the stimulator's ``stimulus_presentation`` document.
    * **stimulus times** -- ``presentation_time.onset``, converted into the
      ensemble's clock through the session syncgraph, so delivery times and
      spike times are directly comparable.

    Neuron selection uses the same vocabulary as ``ndi.fun.ensemble.read``,
    and quality is a hard filter there too.

    The binning and file writing are ``blech_clust_write``, which is pure and
    separately tested; this function is the part that needs a session.
    """
    if sample_rate != BLECH_SAMPLE_RATE:
        raise ValueError(
            "blech_clust requires an acquisition sample rate of exactly 30000 Hz "
            f"(30 samples/ms); received {sample_rate:g} Hz. Resample the data or "
            "supply data recorded at 30 kHz."
        )
    if pre_stim < 0 or post_stim <= 0:
        raise ValueError("pre_stim must be >= 0 and post_stim must be > 0 (milliseconds).")

    session = probe.session

    if verbose:
        print("Reading ensemble spike times (ndi.fun.ensemble)...")
    unit_spiketimes, unit_info, ensemble_clocktype = _blech_get_ensemble(
        session,
        probe,
        epoch_id,
        ensemble=ensemble,
        min_quality=min_quality,
        quality_label=quality_label,
        keep_unrated=keep_unrated,
        include_names=include_names,
        exclude_names=exclude_names,
        include_ids=include_ids,
        exclude_ids=exclude_ids,
        include_index=include_index,
        exclude_index=exclude_index,
        single_unit_labels=single_unit_labels,
    )
    if not unit_spiketimes:
        raise ValueError(f"The ensemble for epoch {epoch_id} contains no neurons.")

    if verbose:
        print("Reading stimulus presentation (identities and times)...")
    onset_probe, trial_stimid, stimid_tastant = _blech_get_stimulus_presentation(
        session,
        stimulator,
        probe,
        epoch_id,
        ensemble_clocktype,
        tastant_field=tastant_field,
        stimid_field=stimid_field,
    )

    blech_clust_write(
        outputfile,
        unit_spiketimes,
        unit_info,
        onset_probe,
        trial_stimid,
        stimid_tastant,
        pre_stim=round(pre_stim),
        post_stim=round(post_stim),
        sample_rate=sample_rate,
        stimulus_order=stimulus_order,
        include_stimids=include_stimids,
        epoch_id=epoch_id,
        verbose=verbose,
    )


def _blech_get_ensemble(
    session: Any,
    probe: Any,
    epoch_id: str,
    *,
    ensemble: Any,
    single_unit_labels: Sequence[str],
    **filter_options: Any,
) -> tuple[list[np.ndarray], list[dict[str, Any]], str]:
    """The per-unit spike trains, unit descriptors, and the ensemble clock."""
    from . import ensemble as ensemble_fun

    if ensemble is not None:
        E = ensemble_fun.read(session, ensemble, epoch_id, **filter_options)
    else:
        activity, neuron_ids, neuron_names, info, _ = ensemble_fun.load(session, probe, epoch_id)
        E = {
            "activity": activity,
            "neuron_ids": neuron_ids,
            "neuron_names": neuron_names,
            "epoch": epoch_id,
            "info": info,
        }
        E = _blech_apply_filter(session, E, filter_options)

    clocktype = (E.get("info") or {}).get("clocktype", "")

    activity = E["activity"]
    dense = activity.toarray() if hasattr(activity, "toarray") else np.asarray(activity)
    # Drop the zero right-padding. A spike at exactly 0.0 is indistinguishable
    # from padding in this representation; that is inherent to the sparse
    # export, and MATLAB drops it the same way.
    unit_spiketimes = [row[row != 0] for row in np.atleast_2d(dense)]

    # blech's /unit_descriptor flags. regular_spiking and fast_spiking are NOT
    # inferred -- they only affect blech's raster colours, and guessing them
    # would put a claim about cell type into the file that NDI never made.
    _, qlabel = ensemble_fun.neuron_quality(session, E["neuron_ids"])
    su_labels = {s.lower() for s in single_unit_labels}
    names = list(E.get("neuron_names") or [])
    unit_info: list[dict[str, Any]] = []
    for i in range(len(unit_spiketimes)):
        lab = qlabel[i] if i < len(qlabel) else ""
        unit_info.append(
            {
                "name": names[i] if i < len(names) else "",
                "single_unit": int(bool(lab) and lab.lower() in su_labels),
                "regular_spiking": 0,
                "fast_spiking": 0,
            }
        )
    return unit_spiketimes, unit_info, clocktype


def _blech_apply_filter(
    session: Any, E: Mapping[str, Any], options: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply read()'s selection vocabulary to an already-loaded ensemble."""
    from . import ensemble as ensemble_fun

    min_quality = options.get("min_quality")
    quality_label = options.get("quality_label") or ""
    use_quality = min_quality is not None or bool(quality_label)
    any_filter = use_quality or any(
        options.get(k) is not None and len(np.atleast_1d(options.get(k))) > 0
        for k in (
            "include_names",
            "exclude_names",
            "include_ids",
            "exclude_ids",
            "include_index",
            "exclude_index",
        )
    )
    if not any_filter:
        return dict(E)

    excl_ids = list(options.get("exclude_ids") or [])
    if use_quality:
        qnum, qlabel = ensemble_fun.neuron_quality(session, E["neuron_ids"])
        qmask = np.ones(len(E["neuron_ids"]), dtype=bool)
        if min_quality is not None:
            qmask &= qnum >= min_quality
        if quality_label:
            wanted = [quality_label] if isinstance(quality_label, str) else list(quality_label)
            qmask &= np.array([lab in wanted for lab in qlabel], dtype=bool)
        if options.get("keep_unrated"):
            qmask |= np.isnan(qnum)
        excl_ids += [nid for nid, ok in zip(E["neuron_ids"], qmask) if not ok]

    return ensemble_fun.filter(
        E,
        include_names=options.get("include_names"),
        exclude_names=options.get("exclude_names"),
        include_index=options.get("include_index"),
        exclude_index=options.get("exclude_index"),
        include_ids=options.get("include_ids"),
        exclude_ids=excl_ids,
    )


def _blech_get_stimulus_presentation(
    session: Any,
    stimulator: Any,
    probe: Any,
    epoch_id: str,
    target_clocktype: str,
    *,
    tastant_field: str,
    stimid_field: str,
) -> tuple[np.ndarray, np.ndarray, dict[float, str]]:
    """Stimulus identities and delivery times, in the ensemble's clock."""
    from ..app.stimulus.decoder import ndi_app_stimulus_decoder
    from ..query import ndi_query
    from ..time.clocktype import ndi_time_clocktype
    from ..time.timereference import ndi_time_timereference

    q = (
        ndi_query("").isa("stimulus_presentation")
        & ndi_query("").depends_on("stimulus_element_id", stimulator.id)
        & ndi_query("epochid.epochid", "exact_string", epoch_id, "")
    )
    stim_docs = session.database_search(q)
    if not stim_docs:
        raise ValueError(
            f"No stimulus_presentation document was found for stimulator "
            f"{stimulator.elementstring()}, epoch {epoch_id}. Run the stimulus "
            "decoder on this session first."
        )
    stim_doc = stim_docs[0]

    sp = stim_doc.document_properties["stimulus_presentation"]
    presentation_order = np.asarray(sp["presentation_order"], dtype=float).ravel()

    stimuli = sp["stimuli"]
    unique_stimid = np.full(len(stimuli), np.nan, dtype=float)
    stimid_tastant: dict[float, str] = {}
    for k, stim in enumerate(stimuli):
        params = stim.get("parameters", {}) or {}
        # Fall back to the 1-based index when there is no stimid field, as
        # MATLAB does, so an unlabelled protocol still exports.
        unique_stimid[k] = float(params.get(stimid_field, k + 1))
        stimid_tastant[unique_stimid[k]] = str(params.get(tastant_field, ""))

    # presentation_order holds 1-BASED indices into `stimuli` (it is written by
    # MATLAB), so subtract one before indexing.
    trial_stimid = np.array([unique_stimid[int(i) - 1] for i in presentation_order], dtype=float)

    decoder = ndi_app_stimulus_decoder(session)
    presentation_time = decoder.load_presentation_time(stim_doc)
    onset_stim = np.array([p["onset"] for p in presentation_time], dtype=float)
    offset_stim = np.array([p["offset"] for p in presentation_time], dtype=float)

    target = target_clocktype or "dev_local_time"
    stim_timeref = ndi_time_timereference(
        stimulator,
        ndi_time_clocktype(presentation_time[0]["clocktype"]),
        stim_doc.document_properties["epochid"]["epochid"],
        0,
    )
    t_probe, _, msg = session.syncgraph.time_convert(
        stim_timeref,
        np.column_stack([onset_stim, offset_stim]),
        probe,
        ndi_time_clocktype(target),
    )
    if t_probe is None or np.size(t_probe) == 0:
        raise ValueError(
            f"Could not convert stimulus times into the ensemble clock ({target}) "
            f"via the session syncgraph: {msg}"
        )
    t_probe = np.asarray(t_probe, dtype=float).reshape(len(onset_stim), 2)
    return t_probe[:, 0], trial_stimid, stimid_tastant
