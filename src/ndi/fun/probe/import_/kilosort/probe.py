"""ndi.fun.probe.import.kilosort.probe - import curated Kilosort output into NDI.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kilosort/probe.m``

THIS IS THE FUNCTION THAT MAKES NEURONS. For each curated cluster that passes
the quality filter it creates:

1. an element of type ``'spikes'`` named ``<probe>_<reference>_<cluster>``,
   with the cluster's spike times added as epochs -- mapped back out of
   Kilosort's concatenated sample stream into each NDI epoch's own clock; and
2. a ``neuron_extracellular`` document holding the mean waveform, its sample
   times, the cluster index and the curated quality.

Those ``'spikes'`` elements are exactly what ``ndi.fun.ensemble.load`` looks
for, so a probe imported here is a probe ``ndi.gui.app.ensembleMaker`` can
build an ensemble from.

THE SAMPLE STREAM IS THE CONTRACT
``spike_times.npy`` holds positions in the CONCATENATED stream of the probe's
epochs, in ``epochtable()`` order -- the same concatenation
``ndi.fun.probe.export.binary`` wrote. The probe is therefore the
authoritative reference for where each epoch begins and ends, and a spike
index past the end of the last epoch means the sort does not belong to this
probe. That is raised, not silently dropped, because dropping it would import
a plausible-looking subset of somebody else's recording.

THAT ORDER IS NOW DEFINED, which it was not when this importer landed.
``epochtable()`` used to return registered epochs in whatever order
``database_search`` yielded their documents -- stable for a given database,
but neither insertion order nor anything a caller could predict, so a sort
exported by one language and imported by the other could land spikes in the
wrong epochs without erroring. Registered epochs are now alphabetised by
``epoch_id`` (NDI-python#162), which is what MATLAB's ``intersect`` produces,
so both languages agree on the concatenation this file's arithmetic assumes.

IDEMPOTENCY
A ``kilosort_clusters`` document records the MD5 of ``spike_clusters.npy``.
An unchanged checksum means the curation has not moved since the last import
and there is nothing to do; a changed one removes the previous import and
repeats it. ``force`` overrides the check.
"""

from __future__ import annotations

import platform
import warnings
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .. import epoch_map as epoch_map_module
from .binary_info import binaryinfo
from .get_info import DEFAULT_QUALITY_LABELS, _session_path, kilosort_directory
from .labels import labels as read_labels
from .mean_waveform import meanwaveform
from .prompt_raw_binary import promptrawbinary
from .recalculate_mean_waveforms import recalculatemeanwaveforms
from .remove_old import removeold
from .waveform_data import waveformdata

__all__ = ["probe", "DEFAULT_QUALITY_VALUES", "app_provenance"]

#: The quality_number given to each default label: single/good = 1, multi/mua = 4.
DEFAULT_QUALITY_VALUES = (1, 4)

#: The clock spike times are stored against. Chosen because it is the clock
#: readtimeseries resolves epochs through, so a stored spike train reads back.
# The epoch bookkeeping is shared with the KIASORT importer: both map sample
# offsets into the same concatenated stream ndi.fun.probe.export.binary wrote,
# so the arithmetic has one correct answer and lives in one place.
_epochtable = epoch_map_module.epochtable
_clocks = epoch_map_module.clocks
_ranges = epoch_map_module.ranges
_first_range = epoch_map_module.first_range
_clock_index = epoch_map_module.clock_index
SPIKE_CLOCK = epoch_map_module.SPIKE_CLOCK


def app_provenance(kilosort_version: str) -> dict[str, Any]:
    """The ``app`` sub-document recorded on everything this importer writes.

    These neurons come from a multi-stage pipeline -- a sorter, then manual
    curation in Phy, then this importer -- rather than one program, and the
    ``app`` sub-document describes a single app. MATLAB records the whole
    pipeline in ``app.name`` and the Kilosort version in ``app.version`` as an
    interim measure; the same string is written here so a document written by
    either language reports its provenance identically.
    """
    return {
        "name": f"Kilosort{kilosort_version} to phy to ndi.fun.probe.import.kilosort",
        "version": kilosort_version,
        "url": "https://github.com/VH-Lab/NDI-matlab",
        "os": platform.system(),
        "os_version": platform.release(),
        "interpreter": "Python",
        "interpreter_version": platform.python_version(),
    }


def probe(  # noqa: PLR0912, PLR0915 - one function in MATLAB, kept as one here
    session: Any,
    probe_obj: Any,
    *,
    kilosort_dir: str = "kilosort",
    subdir: str = "kilosort_output",
    noSubFolder: bool = False,  # noqa: N803 - MATLAB's parameter name
    quality_labels: Sequence[str] = DEFAULT_QUALITY_LABELS,
    quality_values: Sequence[float] = DEFAULT_QUALITY_VALUES,
    kilosort_version: str = "2.5",
    waveform_source: str = "templates",
    RecalculateMeanWaveforms: bool = True,  # noqa: N803 - MATLAB's parameter name
    RecalculateMeanWaveformT0: float = -0.005,  # noqa: N803
    RecalculateMeanWaveformT1: float = 0.005,  # noqa: N803
    RecalculateMeanWaveformMaxSpikes: float = 1000,  # noqa: N803
    RecalculateChunkMemoryBytes: float = 2e9,  # noqa: N803
    binary_file: str = "",
    HighPassFilter: bool = True,  # noqa: N803
    HighPassCutoff: float = 300.0,  # noqa: N803
    HighPassOrder: int = 4,  # noqa: N803
    HighPassRipple: float = 0.8,  # noqa: N803
    PromptForRawFile: bool = True,  # noqa: N803
    RawFile: str = "",  # noqa: N803
    ProbeType: str = "",  # noqa: N803
    RawNumChannels: float = float("nan"),  # noqa: N803
    ask: Any = None,
    force: bool = False,
    dryRun: bool = False,  # noqa: N803 - MATLAB's parameter name
    progressbar: bool = False,
    verbose: bool = True,
) -> int:
    """Import PROBE_OBJ's curated Kilosort output into SESSION.

    Returns the number of neurons imported (or, under ``dryRun``, that would
    be). ``waveform_source`` is ``'templates'`` or ``'none'``.
    """
    if len(quality_labels) != len(quality_values):
        raise ValueError("quality_labels and quality_values must have the same length.")
    if waveform_source not in ("templates", "none"):
        raise ValueError(f"waveform_source must be 'templates' or 'none'; got {waveform_source!r}.")

    report = bool(verbose) or dryRun
    prefix = "[dry run] " if dryRun else ""

    # --- 1. locate the curated output -------------------------------------
    # MATLAB (post-1b99d29) resolves the probe's folder through
    # ndi.fun.file.elementDirectory, so ``elestr`` is the platform-safe
    # folder name -- and stores THAT in kilosort_clusters.kilosort_directory,
    # so a document written on one platform names the same folder on another.
    # ``elementstring()`` alone would put ``ctx | 1`` in the doc field while
    # the folder on disk is ``ctx_-_1``.
    from ....file import elementDirectory

    _, probe_dir_name, _ = elementDirectory(Path(_session_path(session)) / kilosort_dir, probe_obj)
    kdir = Path(
        kilosort_directory(
            session,
            probe_obj,
            kilosort_dir=kilosort_dir,
            subdir=subdir,
            noSubFolder=noSubFolder,
        )
    )
    if not kdir.is_dir():
        raise FileNotFoundError(
            f"Kilosort directory not found: {kdir}. Was the data exported with "
            "ndi.fun.probe.export.all_binary?"
        )
    spike_times_file = kdir / "spike_times.npy"
    spike_clusters_file = kdir / "spike_clusters.npy"
    if not spike_times_file.is_file() or not spike_clusters_file.is_file():
        raise FileNotFoundError(
            f"Expected curated files spike_times.npy and spike_clusters.npy in {kdir}."
        )
    if report:
        print(f"{prefix}Importing kilosort results for probe {probe_dir_name} from {kdir}.")

    # --- 2. idempotency ----------------------------------------------------
    from .....query import ndi_query
    from ....file import MD5

    md5_value = MD5(str(spike_clusters_file))
    existing = session.database_search(
        ndi_query("").isa("kilosort_clusters")
        & ndi_query("").depends_on("element_id", probe_obj.id)
    )
    if existing:
        if len(existing) == 1 and not force:
            stored = existing[0].document_properties["kilosort_clusters"][
                "curated_output_MD5_checksum"
            ]
            if stored == md5_value:
                if report:
                    print(
                        f"{prefix}Curation is unchanged since the last import; nothing to "
                        "do (use force=True to re-import)."
                    )
                return 0
        if report:
            print(
                f"{prefix}Would remove {len(existing)} previously imported kilosort "
                "cluster document(s) and their dependent neurons."
            )
        if not dryRun:
            for doc in existing:
                removeold(session, doc)

    # --- 3. read the curated output ---------------------------------------
    spike_samples_global = np.load(spike_times_file).astype(float).ravel()
    spike_clusters = np.load(spike_clusters_file).astype(float).ravel()
    cluster_ids, cluster_labels = read_labels(kdir)

    # --- 4. the sample <-> epoch map, straight from the probe -------------
    epoch_table, _ = _epochtable(probe_obj)
    epoch_ids: list[str] = []
    epoch_counts: list[int] = []
    epoch_clocks: list[Any] = []
    epoch_t0_t1: list[Any] = []
    sample_rate = float("nan")

    for entry in epoch_table:
        epoch_id = entry["epoch_id"]
        epoch_ids.append(epoch_id)
        first, last = probe_obj.times2samples(epoch_id, _first_range(entry))
        epoch_counts.append(int(last) - int(first) + 1)
        clock_index = _clock_index(entry, SPIKE_CLOCK)
        if clock_index is None:
            raise ValueError(f"Epoch {epoch_id} has no '{SPIKE_CLOCK}' clock.")
        epoch_clocks.append(_clocks(entry)[clock_index])
        epoch_t0_t1.append(_ranges(entry)[clock_index])
        if sample_rate != sample_rate:  # still NaN
            sample_rate = float(probe_obj.samplerate(epoch_id))

    bounds = np.concatenate([[0], np.cumsum(epoch_counts)]).astype(float)
    total_samples = float(bounds[-1])

    # --- 4b. do the spikes belong to this probe at all? -------------------
    if spike_samples_global.size:
        overrun = int(np.sum((spike_samples_global >= total_samples) | (spike_samples_global < 0)))
        if overrun > 0:
            raise ValueError(
                f"{overrun} of {spike_samples_global.size} spike sample indices fall "
                f"outside the probe's epochs [0, {total_samples:g}). The largest spike "
                f"sample index is {spike_samples_global.max():g}. This usually means the "
                "kilosort output was sorted on a recording whose concatenation does not "
                "match this probe's epochs (epochtable order or sample rate)."
            )

    # --- 5. where the waveforms come from ---------------------------------
    use_recalc = False
    bininfo: dict[str, Any] = {}
    templates = spike_templates = amplitudes = winv = None

    if waveform_source == "templates":
        if RecalculateMeanWaveforms:
            bininfo = binaryinfo(kdir, binary_file=binary_file)
            if not bininfo["found"]:
                try:
                    bininfo = promptrawbinary(
                        bininfo,
                        RawFile=RawFile,
                        ProbeType=ProbeType,
                        PromptForRawFile=PromptForRawFile,
                        num_channels=RawNumChannels,
                        expectedSamples=total_samples,
                        ask=ask,
                    )
                except Exception as exc:  # noqa: BLE001 - reported, then fall back
                    warnings.warn(
                        "Could not obtain a raw recording for waveform recalculation: "
                        f"{exc} Falling back to the (narrow) template-based mean "
                        "waveforms.",
                        stacklevel=2,
                    )
                    bininfo["found"] = False
            if bininfo["found"]:
                use_recalc = True
                if report:
                    filtering = (
                        f", high-pass {HighPassCutoff} Hz (Chebyshev-I order " f"{HighPassOrder})"
                        if HighPassFilter
                        else ""
                    )
                    print(
                        f"{prefix}Recalculating mean waveforms from binary "
                        f"{bininfo['file']} over [{RecalculateMeanWaveformT0}, "
                        f"{RecalculateMeanWaveformT1}] s{filtering}."
                    )
            else:
                warnings.warn(
                    "RecalculateMeanWaveforms is true but no raw binary could be located "
                    f"near {kdir} and none was selected. Falling back to the (narrow) "
                    "template-based mean waveforms. Pass binary_file or RawFile to "
                    "specify the recording, or set RecalculateMeanWaveforms=False to "
                    "silence this warning.",
                    stacklevel=2,
                )
        if not use_recalc:
            templates, spike_templates, amplitudes, winv = waveformdata(kdir)

    # --- 5b. one pass over the binary for every cluster being imported ----
    wanted = {str(label).lower() for label in quality_labels}
    recalc_ids = np.asarray(
        [cid for cid, label in zip(cluster_ids, cluster_labels) if str(label).lower() in wanted],
        dtype=float,
    )
    recalc_waveforms: list[np.ndarray] = []
    recalc_wst = np.zeros((0, 1))
    if use_recalc and not dryRun and recalc_ids.size:
        if report:
            print(
                f"{prefix}Recalculating mean waveforms for {recalc_ids.size} cluster(s) "
                f"in a single pass over {bininfo['file']}."
            )
        recalc_waveforms, recalc_wst, _ = recalculatemeanwaveforms(
            bininfo["file"],
            int(bininfo["num_channels"]),
            spike_samples_global,
            spike_clusters,
            recalc_ids,
            sample_rate,
            RecalculateMeanWaveformT0,
            RecalculateMeanWaveformT1,
            dtype=bininfo["dtype"],
            byteOrder=bininfo["byteOrder"],
            headerOffsetBytes=int(bininfo["headerOffsetBytes"]),
            multiplier=bininfo["multiplier"],
            maxSpikes=RecalculateMeanWaveformMaxSpikes,
            epochBounds=bounds,
            maxChunkBytes=RecalculateChunkMemoryBytes,
            highpass=HighPassFilter,
            hp_cutoff=HighPassCutoff,
            hp_order=HighPassOrder,
            hp_ripple=HighPassRipple,
            verbose=bool(verbose),
        )

    # --- 6. the provenance document ---------------------------------------
    from .....document import ndi_document

    app_struct = app_provenance(kilosort_version)
    cluster_doc = None
    if not dryRun:
        cluster_doc = ndi_document(
            "kilosort_clusters",
            app=app_struct,
            **{
                "base.session_id": session.id(),
                "kilosort_clusters.kilosort_directory": f"{kilosort_dir}/{probe_dir_name}",
                "kilosort_clusters.curated_output_MD5_checksum": md5_value,
            },
        )
        cluster_doc.set_dependency_value("element_id", probe_obj.id)
        session.database_add(cluster_doc)

    # --- 7. assemble each kept cluster, then commit in batches ------------
    label_values = {
        str(label).lower(): value for label, value in zip(quality_labels, quality_values)
    }
    specs: list[dict[str, Any]] = []
    n_imported = 0

    for index, cid in enumerate(cluster_ids):
        label = str(cluster_labels[index])
        if label.lower() not in label_values:
            if report:
                print(f"{prefix}  Cluster {int(cid)} (label '{label}') skipped.")
            continue
        quality_number = label_values[label.lower()]

        in_cluster = spike_clusters == cid
        cluster_samples = spike_samples_global[in_cluster]
        n_imported += 1

        # the reference is in the name so neurons from probes sharing a name
        # (gust_ctx ref 1..6) stay distinguishable
        neuron_name = f"{probe_obj.name}_{int(probe_obj.reference)}_{int(cid)}"

        if dryRun:
            print(
                f"{prefix}  Would import cluster {int(cid)} as neuron {neuron_name} "
                f"({label}, quality {quality_number}, {int(in_cluster.sum())} spikes), "
                f"with a neuron_extracellular document and spike trains across "
                f"{len(epoch_ids)} epoch(s)."
            )
            continue

        mean_wf, wst = _waveform_for(
            cid,
            use_recalc=use_recalc,
            waveform_source=waveform_source,
            recalc_ids=recalc_ids,
            recalc_waveforms=recalc_waveforms,
            recalc_wst=recalc_wst,
            bininfo=bininfo,
            spike_clusters=spike_clusters,
            spike_templates=spike_templates,
            amplitudes=amplitudes,
            templates=templates,
            winv=winv,
            sample_rate=sample_rate,
        )

        waveform, sample_times, n_samples, n_channels = _storable_waveform(mean_wf, wst)
        neuron_doc = ndi_document(
            "neuron_extracellular",
            app=app_struct,
            **{
                "base.session_id": session.id(),
                "neuron_extracellular.number_of_samples_per_channel": n_samples,
                "neuron_extracellular.number_of_channels": n_channels,
                "neuron_extracellular.mean_waveform": waveform,
                "neuron_extracellular.waveform_sample_times": sample_times,
                "neuron_extracellular.cluster_index": int(cid),
                "neuron_extracellular.quality_number": quality_number,
                "neuron_extracellular.quality_label": label,
            },
        )
        if cluster_doc is not None:
            neuron_doc.set_dependency_value("spike_clusters_id", cluster_doc.id)

        epochs = []
        for position, epoch_id in enumerate(epoch_ids):
            in_epoch = (cluster_samples >= bounds[position]) & (
                cluster_samples < bounds[position + 1]
            )
            # NO +1 HERE, where MATLAB has one. MATLAB's probe.times2samples /
            # samples2times are 1-BASED (sample 1 is the epoch's first), so it
            # converts a 0-based global offset with (offset + 1). Python's are
            # documented as 0-BASED (ndi.probe.timeseries.samples2times returns
            # samples / rate), so the offset IS the sample index and adding one
            # would shift every spike a sample late. Semantic parity, per
            # docs/developer_notes/ndi_xlang_principles.md: the user-facing
            # count is the same instant in both languages, spelled in each
            # language's own indexing.
            local_samples = cluster_samples[in_epoch] - bounds[position]
            if local_samples.size:
                spike_times = np.asarray(
                    probe_obj.samples2times(epoch_id, local_samples), dtype=float
                ).ravel()
            else:
                spike_times = np.zeros(0)
            epochs.append(
                {
                    "epoch_id": epoch_id,
                    "epoch_clock": epoch_clocks[position],
                    "t0_t1": epoch_t0_t1[position],
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
                f"  Prepared cluster {int(cid)} as neuron {neuron_name} "
                f"({label}, {int(in_cluster.sum())} spikes)."
            )

    if not dryRun and specs:
        from .....element_timeseries import ndi_element_timeseries

        ndi_element_timeseries.add_multiple(
            session,
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
                f"{probe_dir_name}. No changes were made to the database."
            )
        else:
            print(f"Done. Imported {n_imported} neuron(s) for probe {probe_dir_name}.")
    return n_imported


def _storable_waveform(mean_wf: np.ndarray, wst: Any) -> tuple[list[Any], list[float], int, int]:
    """A waveform and its times in the shapes ``neuron_extracellular`` accepts.

    DIVERGENCE, forced and documented: with ``waveform_source='none'`` MATLAB
    stores an EMPTY mean_waveform while still writing counts of 1 (its
    ``max(size(meanWf,1),1)``). The schema declares mean_waveform a matrix and
    waveform_sample_times an N-by-1 matrix, and this port's DID validator
    rejects a 0x0 for either -- so an empty waveform cannot be stored on this
    side at all. Rather than make ``waveform_source='none'`` unusable, the
    empty case is stored as the single zero sample the counts MATLAB writes
    already describe: a reader sees 1 sample x 1 channel of zero, which is
    what "no waveform was computed" looks like in a field that cannot be
    empty.
    """
    waveform = np.asarray(mean_wf, dtype=float)
    times = np.asarray(wst, dtype=float).ravel()
    if waveform.size == 0 or waveform.ndim < 2:
        return [[0.0]], [0.0], 1, 1
    if times.size != waveform.shape[0]:
        # a waveform whose times were never computed: keep the two consistent
        times = np.zeros(waveform.shape[0])
    return waveform.tolist(), times.tolist(), int(waveform.shape[0]), int(waveform.shape[1])


def _waveform_for(
    cid: float,
    *,
    use_recalc: bool,
    waveform_source: str,
    recalc_ids: np.ndarray,
    recalc_waveforms: list[np.ndarray],
    recalc_wst: np.ndarray,
    bininfo: dict[str, Any],
    spike_clusters: Any,
    spike_templates: Any,
    amplitudes: Any,
    templates: Any,
    winv: Any,
    sample_rate: float,
) -> tuple[np.ndarray, np.ndarray]:
    """This cluster's mean waveform and its sample times.

    From the single-pass recalculation when one ran, else from the Kilosort
    templates. The two differ in where time zero is: a recalculated waveform
    is cut around the spike sample, so its times run from T0 to T1 with 0 at
    the spike; a template's are placed relative to its own trough, which is
    the only landmark a template carries.
    """
    if waveform_source != "templates":
        return np.zeros((0, 0)), np.zeros(0)

    if use_recalc:
        matches = np.flatnonzero(recalc_ids == cid)
        if matches.size and recalc_waveforms:
            return recalc_waveforms[int(matches[0])], recalc_wst
        channels = int(bininfo.get("num_channels", 1) or 1)
        return np.zeros((max(np.asarray(recalc_wst).size, 1), channels)), recalc_wst

    mean_wf = meanwaveform(cid, spike_clusters, spike_templates, amplitudes, templates, winv)
    if mean_wf.size == 0:
        return mean_wf, np.zeros(0)
    trough_channel = int(np.argmin(np.min(mean_wf, axis=0)))
    trough_sample = int(np.argmin(mean_wf[:, trough_channel]))
    wst = (np.arange(mean_wf.shape[0], dtype=float) - trough_sample) / sample_rate
    return mean_wf, wst
