"""ndi.fun.probe.import.kiasort.probe - import one probe's KIASORT sort into NDI.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kiasort/probe.m``

For every KIASORT unit that passes the quality filter this writes:

1. an ``ndi.neuron`` element named ``<probe name>_<reference>_<unit id>``,
   with its spike times added as epochs; and
2. a ``neuron_extracellular`` document holding the mean waveform, its sample
   times, the cluster index and the quality label.

The reference is in the neuron's name because probes routinely share one --
``gust_ctx`` references 1 through 6 -- and unit 3 of each would otherwise
collide.

WHY THE EPOCH MAP COMES FROM THE PROBE, NOT THE SORT
KIASORT reports each spike as an offset into the recording it sorted, which
was the concatenation ``ndi.fun.probe.export.binary`` wrote: the probe's
epochs, end to end, in epochtable order. So the probe itself is the
authoritative map back, via :mod:`ndi.fun.probe.import_.epoch_map` -- the
same map the Kilosort importer uses, because both are undoing the same
concatenation. If the offsets do not fit inside it the sort belongs to a
different recording, and that is an error rather than a set of dropped
spikes.

IMPORTING TWICE IS FREE, IMPORTING A CHANGED SORT IS NOT
A ``kiasort_clusters`` document records the MD5 of the unit-label file. An
unchanged checksum means the sort has not moved and the call does nothing;
a changed one means the previous neurons describe a sort that no longer
exists, so they are removed before the new ones are written. Skipping that
removal would leave two generations of neurons for one probe, indistinguishable
from each other.
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .. import epoch_map as epoch_map_module
from .get_info import DEFAULT_QUALITY_LABELS, kiasort_directory
from .labels import labels as read_labels
from .mean_waveform import meanwaveform
from .remove_old import removeold
from .results import RES_SORTED, results

__all__ = ["probe", "app_provenance", "DEFAULT_QUALITY_VALUES", "WAVEFORM_SOURCES"]

#: The quality_number given to each of :data:`.get_info.DEFAULT_QUALITY_LABELS`.
DEFAULT_QUALITY_VALUES: tuple[float, ...] = (1.0,)

#: Where a mean waveform may come from. KIASORT computes them during its
#: sample-sorting stage; there is no second source to recalculate from, as
#: the Kilosort importer has.
WAVEFORM_SOURCES = ("samples", "none")


def app_provenance(kiasort_version: str) -> dict[str, Any]:
    """The ``app`` sub-document recorded on everything this importer writes.

    These neurons come from a pipeline -- KIASORT, optionally curation, then
    this importer -- rather than one program, while the ``app`` sub-document
    describes a single app. MATLAB records the whole pipeline in ``app.name``
    and the KIASORT version in ``app.version``; the same strings are written
    here so a document written by either language reads the same.
    """
    return {
        "name": "KIASORT to ndi.fun.probe.import.kiasort",
        "version": kiasort_version,
        "url": "https://github.com/VH-Lab/KIASORT",
        "os": platform.system(),
        "os_version": platform.version(),
        "interpreter": "Python",
        "interpreter_version": sys.version.split()[0],
    }


def probe(  # noqa: PLR0912, PLR0915 - one function in MATLAB, kept as one here
    S: Any,  # noqa: N803 - MATLAB's parameter name
    probe_obj: Any,
    *,
    kiasort_dir: str = "kiasort",
    subdir: str = "kiasort_output",
    noSubFolder: bool = False,  # noqa: N803 - MATLAB's parameter name
    curated: bool = False,
    quality_labels: Sequence[str] = DEFAULT_QUALITY_LABELS,
    quality_values: Sequence[float] = DEFAULT_QUALITY_VALUES,
    kiasort_version: str = "",
    waveform_source: str = "samples",
    force: bool = False,
    dryRun: bool = False,  # noqa: N803 - MATLAB's parameter name
    progressbar: bool = False,
    verbose: bool = True,
) -> int:
    """Import PROBE_OBJ's KIASORT results into session S; returns neurons imported.

    Args:
        S: the ``ndi.session`` holding the probe.
        probe_obj: the probe or element whose sort is being imported.
        kiasort_dir: directory under the session path holding the output.
        subdir: the KIASORT output subfolder within the probe's directory.
        noSubFolder: read directly from the probe's directory instead.
        curated: prefer KIASORT's ``_curated`` files when they exist.
        quality_labels: labels to import, parallel to *quality_values*.
        quality_values: the ``quality_number`` each label stores.
        kiasort_version: recorded in the documents' ``app`` provenance.
        waveform_source: ``'samples'`` for KIASORT's per-unit mean waveforms,
            ``'none'`` to import spike trains only.
        force: re-import even when the checksum says nothing changed.
        dryRun: report what would be imported, touching nothing.
        progressbar: show a progress bar while the neurons are written.
        verbose: report progress.

    Raises:
        ValueError: on mismatched label/value lists, an unknown
            *waveform_source*, or spikes that fall outside the probe's epochs.
        FileNotFoundError: when the KIASORT output is not where it should be.

    MATLAB equivalent: ``ndi.fun.probe.import.kiasort.probe``.
    """
    quality_labels = list(quality_labels)
    quality_values = list(quality_values)
    if len(quality_labels) != len(quality_values):
        raise ValueError("quality_labels and quality_values must have the same number of elements.")
    if waveform_source not in WAVEFORM_SOURCES:
        raise ValueError(f"waveform_source must be one of {WAVEFORM_SOURCES}.")

    # A dry run always reports: it produces nothing else.
    report = bool(verbose) or dryRun
    prefix = "[dry run] " if dryRun else ""

    # --- 1. locate the output ---------------------------------------------
    kdir, element_string = kiasort_directory(
        S, probe_obj, kiasort_dir=kiasort_dir, subdir=subdir, noSubFolder=noSubFolder
    )
    if not kdir.is_dir():
        raise FileNotFoundError(
            f"KIASORT directory not found: {kdir}. Was the data exported with "
            "ndi.fun.probe.export.all_binary and sorted with KIASORT?"
        )
    res_dir = kdir / RES_SORTED
    if not res_dir.is_dir():
        raise FileNotFoundError(
            f"KIASORT {RES_SORTED} folder not found in {kdir}. Was KIASORT run with "
            "this folder as its output?"
        )

    # The checksum has to target the file the reader will actually read, so
    # resolve curated-vs-not here rather than trusting the request.
    suffix = _resolve_suffix(res_dir, curated)
    unified_file = res_dir / f"unifiedLabels{suffix}.h5"
    if not unified_file.is_file() or not (res_dir / f"spike_idx{suffix}.h5").is_file():
        raise FileNotFoundError(
            f"Expected KIASORT files spike_idx{suffix}.h5 and unifiedLabels{suffix}.h5 "
            f"in {res_dir}."
        )

    if report:
        print(f"{prefix}Importing KIASORT results for probe {element_string} from {res_dir}.")

    # --- 2. idempotency ----------------------------------------------------
    from .....fun.utils import identifier
    from .....query import ndi_query
    from ....file import MD5

    md5_value = MD5(str(unified_file))
    existing = S.database_search(
        ndi_query("").isa("kiasort_clusters")
        & ndi_query("").depends_on("element_id", identifier(probe_obj))
    )
    if existing:
        if len(existing) == 1 and not force:
            stored = existing[0].document_properties["kiasort_clusters"][
                "curated_output_MD5_checksum"
            ]
            if stored == md5_value:
                if report:
                    print(
                        f"{prefix}Sort is unchanged since the last import; nothing to do "
                        "(use force=True to re-import)."
                    )
                return 0
        if report:
            print(
                f"{prefix}Would remove {len(existing)} previously imported KIASORT "
                "cluster document(s) and their dependent neurons."
            )
        if not dryRun:
            for doc in existing:
                removeold(S, doc)

    # --- 3. read the sort (spike samples arrive 0-based) -------------------
    found = results(kdir, curated=curated, need_stats=waveform_source != "none")
    spike_samples_global = found.spike_samples_global
    spike_units = found.spike_units
    unit_ids, unit_labels = read_labels(kdir, curated=curated)

    # --- 4. the sample <-> epoch map, straight from the probe --------------
    emap = epoch_map_module.epoch_map(probe_obj)
    emap.check_in_range(spike_samples_global, "KIASORT")

    # --- 5. the provenance document ----------------------------------------
    from .....document import ndi_document

    app_struct = app_provenance(kiasort_version)
    cluster_doc = None
    if not dryRun:
        cluster_doc = ndi_document(
            "kiasort_clusters",
            **{
                "app": app_struct,
                "base.session_id": S.id(),
                "kiasort_clusters.kiasort_directory": f"{kiasort_dir}/{element_string}",
                "kiasort_clusters.curated_output_MD5_checksum": md5_value,
            },
        )
        cluster_doc = cluster_doc.set_dependency_value("element_id", identifier(probe_obj))
        S.database_add(cluster_doc)

    # --- 6. one spec per imported unit, committed together -----------------
    wanted = {str(label).lower(): index for index, label in enumerate(quality_labels)}
    specs: list[dict[str, Any]] = []
    n_imported = 0

    for cid, label in zip(unit_ids, unit_labels):
        match = wanted.get(str(label).lower())
        if match is None:
            if report:
                print(f"{prefix}  Unit {int(cid)} (label '{label}') skipped.")
            continue
        quality_number = quality_values[match]

        in_unit = spike_units == cid
        unit_samples = spike_samples_global[in_unit]
        n_imported += 1

        neuron_name = f"{probe_obj.name}_{int(probe_obj.reference)}_{int(cid)}"

        if dryRun:
            print(
                f"{prefix}  Would import unit {int(cid)} as neuron {neuron_name} "
                f"({label}, quality {int(quality_number)}, {int(in_unit.sum())} spikes), "
                f"with a neuron_extracellular document and spike trains across "
                f"{len(emap)} epoch(s)."
            )
            continue

        mean_wf = meanwaveform(cid, found.unit_stats) if waveform_source == "samples" else None
        waveform, times, n_samples, n_channels = _storable_waveform(mean_wf, emap.sample_rate)

        neuron_doc = ndi_document(
            "neuron_extracellular",
            **{
                "app": app_struct,
                "base.session_id": S.id(),
                "neuron_extracellular.number_of_samples_per_channel": n_samples,
                "neuron_extracellular.number_of_channels": n_channels,
                "neuron_extracellular.mean_waveform": waveform,
                "neuron_extracellular.waveform_sample_times": times,
                "neuron_extracellular.cluster_index": int(cid),
                "neuron_extracellular.quality_number": quality_number,
                "neuron_extracellular.quality_label": str(label),
            },
        )
        neuron_doc = neuron_doc.set_dependency_value("spike_clusters_id", identifier(cluster_doc))

        epochs = []
        for index, epoch_id in enumerate(emap.epoch_ids):
            local = emap.epoch_slice(index, unit_samples)
            spike_times = (
                np.asarray(probe_obj.samples2times(epoch_id, local), dtype=float).ravel()
                if local.size
                else np.zeros(0)
            )
            epochs.append(
                {
                    "epoch_id": epoch_id,
                    "epoch_clock": emap.clocks[index],
                    "t0_t1": emap.t0_t1[index],
                    "timepoints": spike_times,
                    "datapoints": np.ones_like(spike_times),
                }
            )

        specs.append(
            {
                "name": neuron_name,
                "reference": probe_obj.reference,
                "type": "spikes",
                "epochs": epochs,
                "extra_documents": [neuron_doc],
            }
        )
        if verbose:
            print(
                f"  Prepared unit {int(cid)} as neuron {neuron_name} "
                f"({label}, {int(in_unit.sum())} spikes)."
            )

    if not dryRun and specs:
        from .....element_timeseries import ndi_element_timeseries

        ndi_element_timeseries.add_multiple(
            S,
            probe_obj,
            specs,
            element_class="ndi.neuron",
            progressbar=progressbar,
            verbose=bool(verbose),
        )

    if report:
        if dryRun:
            print(
                f"{prefix}Done. Would import {n_imported} neuron(s) for probe "
                f"{element_string}. No changes were made to the database."
            )
        else:
            print(f"Done. Imported {n_imported} neuron(s) for probe {element_string}.")
    return n_imported


def _resolve_suffix(res_dir: Path, curated: bool) -> str:
    """Which output files will be read: ``"_curated"`` or ``""``.

    Deliberately silent where :func:`.results.results` warns -- it is called
    again there, and one fallback should not produce two warnings.
    """
    if not curated:
        return ""
    have_curated = (res_dir / "spike_idx_curated.h5").is_file() and (
        res_dir / "unifiedLabels_curated.h5"
    ).is_file()
    return "_curated" if have_curated else ""


def _storable_waveform(
    mean_wf: np.ndarray | None, sample_rate: float
) -> tuple[list[Any], list[float], int, int]:
    """A waveform and its sample times in the shapes ``neuron_extracellular`` takes.

    The times are placed RELATIVE TO THE TROUGH, the only landmark a mean
    waveform carries: time zero is the trough of the channel the unit is
    largest on, which is what makes two neurons' waveforms comparable.

    DIVERGENCE, forced and documented, matching the Kilosort importer's: with
    no waveform MATLAB stores an empty ``mean_waveform`` while still writing
    counts of 1. The schema declares it a matrix and this port's validator
    rejects a 0x0, so the empty case is stored as the single zero sample
    those counts already describe -- a reader sees 1 sample x 1 channel of
    zero, which is what "no waveform" looks like in a field that cannot be
    empty.
    """
    if mean_wf is None or np.asarray(mean_wf).size == 0:
        return [[0.0]], [0.0], 1, 1

    waveform = np.asarray(mean_wf, dtype=float)
    if waveform.ndim < 2:
        waveform = waveform.reshape(-1, 1)

    trough_channel = int(np.argmin(np.min(waveform, axis=0)))
    trough_sample = int(np.argmin(waveform[:, trough_channel]))
    rate = sample_rate if sample_rate and sample_rate == sample_rate else 1.0
    times = (np.arange(waveform.shape[0], dtype=float) - trough_sample) / rate

    return waveform.tolist(), times.tolist(), int(waveform.shape[0]), int(waveform.shape[1])
