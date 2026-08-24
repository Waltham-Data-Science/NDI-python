"""
ndi.fun.probe.import_.kilosort.probe - import curated Kilosort spike sorting results into NDI.

MATLAB equivalent: +ndi/+fun/+probe/+import/+kilosort/probe.m

NAMING DIVERGENCE: the MATLAB package is ``+ndi/+fun/+probe/+import/+kilosort``.
``import`` is a reserved word in Python, so the subpackage directory is named
``import_`` and the importable path is ``ndi.fun.probe.import_.kilosort.probe``.

INDEXING PARITY (MATLAB 1-based vs Python/numpy 0-based):

* ``spike_times.npy`` holds 0-based sample indices into the concatenated stream
  (Kilosort's on-disk convention). This is identical in both languages.
* Per-epoch sample COUNTS are offset-invariant (``ss[1] - ss[0] + 1``), so the
  cumulative half-open boundaries ``bounds0`` are the same in both languages.
* Converting a global spike sample to a per-epoch LOCAL sample: MATLAB computes
  ``local1 = (g0 - bounds0[e]) + 1`` (1-based) and calls a 1-based
  ``samples2times``. Python's ``probe.samples2times`` is 0-based
  (ndi.probe.timeseries), so we compute ``local0 = g0 - bounds0[e]`` (no +1) and
  pass that. Dropping the +1 is the only change; the resulting times match.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .labels import labels
from .meanwaveform import meanwaveform
from .removeold import removeold
from .waveformdata import waveformdata


def probe(
    session: Any,
    probe: Any,
    *,
    kilosort_dir: str = "kilosort",
    subdir: str = "kilosort_output",
    noSubFolder: bool = False,
    quality_labels: list[str] | tuple[str, ...] = ("good", "mua"),
    quality_values: list[float] | tuple[float, ...] = (1, 4),
    kilosort_version: str = "2.5",
    waveform_source: str = "templates",
    force: bool = False,
    dryRun: bool = False,
    verbose: bool = True,
) -> None:
    """Import curated Kilosort/Phy output for a probe into the NDI database.

    MATLAB equivalent: ``ndi.fun.probe.import.kilosort.probe``

    For each curated cluster that passes the quality filter, this creates:

    1. an :class:`ndi.neuron` element named ``[probe.name]_[probe.reference]_[N]``
       (``N`` = cluster id) with spike times added as epochs (mapped back from
       the concatenated Kilosort sample stream into each NDI epoch's local time),
       and
    2. a ``neuron_extracellular`` ndi.document holding the mean waveform, sample
       counts, cluster index, and quality (label/number) for that neuron.

    A ``kilosort_clusters`` ndi.document is created that depends on *probe* and
    stores the MD5 checksum of ``spike_clusters.npy``, used to detect whether the
    curation changed since a previous import (idempotency).

    The curated output is read from
    ``[session.path]/[kilosort_dir]/[probe_directory]/[subdir]/``. The
    ``[probe_directory]`` name comes from
    :func:`ndi.fun.file.elementDirectoryName`; for a probe named ``'ctx'`` with
    reference 1 it is ``'ctx_-_1'``. Folders written by older versions of NDI,
    which used a ``'|'`` separator (``'ctx_|_1'``), are still found and used if
    they are present.

    Args:
        session: The ndi.session.
        probe: The ndi.probe / ndi.element whose sort is being imported.
        kilosort_dir: Name of the directory holding the kilosort output.
        subdir: Subfolder within the probe's directory holding the curated files.
        noSubFolder: If ``True``, read directly from the probe's directory.
        quality_labels: Curation labels to import (matched case-insensitively).
        quality_values: ``quality_number`` for each label (parallel array).
        kilosort_version: Kilosort version, recorded in the documents' ``app``
            provenance.
        waveform_source: ``'templates'`` (amplitude-weighted average of
            contributing templates) or ``'none'``.
        force: Re-import even if the checksum is unchanged.
        dryRun: Report what would be imported without changing the database.
        verbose: ``True``/``False`` should we be verbose.

    Raises:
        ValueError: If ``quality_labels`` and ``quality_values`` differ in
            length, if ``waveform_source`` is invalid, or
            (``ndi:fun:probe:import:kilosort:probe:sampleOutOfRange``) if spike
            sample indices fall outside the probe's epochs.
        FileNotFoundError: If the kilosort directory or required files are
            missing.
    """
    if waveform_source not in ("templates", "none"):
        raise ValueError("waveform_source must be 'templates' or 'none'.")
    if len(quality_labels) != len(quality_values):
        raise ValueError("quality_labels and quality_values must have the same number of elements.")

    from ndi.document import ndi_document
    from ndi.element_timeseries import ndi_element_timeseries
    from ndi.fun.file import MD5, elementDirectory
    from ndi.query import ndi_query

    # In a dry run we always report the plan, regardless of the verbose setting.
    report = verbose or dryRun
    pfx = "[dry run] " if dryRun else ""

    # Step 1: locate the kilosort output directory (mirror of the export layout)
    probedir, elestr, _is_legacy = elementDirectory(Path(session.path) / kilosort_dir, probe)
    eff_subdir = "" if noSubFolder else subdir
    kdir = probedir / eff_subdir

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
        print(f"{pfx}Importing kilosort results for probe {elestr} from {kdir}.")

    # Step 2: idempotency - has this curation already been imported?
    md5_value = MD5(str(spike_clusters_file))

    q_existing = ndi_query("").isa("kilosort_clusters") & ndi_query("").depends_on(
        "element_id", probe.id
    )
    olddocs = session.database_search(q_existing)

    if olddocs:
        if len(olddocs) == 1 and not force:
            existing_md5 = olddocs[0].document_properties["kilosort_clusters"][
                "curated_output_MD5_checksum"
            ]
            if existing_md5 == md5_value:
                if report:
                    print(
                        f"{pfx}Curation is unchanged since the last import; nothing "
                        "to do (use force=True to re-import)."
                    )
                return
        if report:
            print(
                f"{pfx}Would remove {len(olddocs)} previously imported kilosort "
                "cluster document(s) and their dependent neurons."
            )
        if not dryRun:
            for od in olddocs:
                removeold(session, od)

    # Step 3: read the curated kilosort output (readNPY -> numpy.load)
    # 0-based sample index into concatenated stream
    spike_samples_global = np.load(spike_times_file).astype(np.float64).ravel()
    spike_clusters = np.load(spike_clusters_file).astype(np.float64).ravel()

    cluster_ids, cluster_labels = labels(kdir)

    # Step 4: build the sample <-> epoch map directly from the probe. This
    # matches how ndi.fun.probe.export.binary concatenated the epochs (in
    # probe.epochtable() order), so the boundaries align with the exported binary.
    et, _ = probe.epochtable()
    n_epochs = len(et)
    epoch_counts: list[int] = []
    epoch_ids: list[Any] = []
    epoch_t0t1: list[Any] = []
    epoch_clock: list[Any] = []
    sample_rate: float = float("nan")

    for entry in et:
        epoch_id = entry.get("epoch_id")
        epoch_ids.append(epoch_id)

        t0_t1 = entry.get("t0_t1")
        # t0_t1 is a list of [t0, t1] pairs (one per clock); the first is the
        # default clock, same convention as export.binary.
        first_pair = t0_t1[0] if isinstance(t0_t1, list) and t0_t1 else t0_t1
        ss = probe.times2samples(epoch_id, np.array([float(first_pair[0]), float(first_pair[1])]))
        epoch_counts.append(int(ss[1] - ss[0] + 1))

        # find the dev_local_time clock for spike-time storage
        clocks = entry.get("epoch_clock") or []
        if not isinstance(clocks, list):
            clocks = [clocks]
        found_idx = None
        for c_idx, clk in enumerate(clocks):
            ctype = getattr(clk, "type", None)
            if ctype is None and hasattr(clk, "value"):
                ctype = clk.value
            if str(ctype) == "dev_local_time":
                found_idx = c_idx
                break
        if found_idx is None:
            raise ValueError(f"Epoch {epoch_id} has no 'dev_local_time' clock.")
        epoch_clock.append(clocks[found_idx])
        # the t0_t1 pair for the chosen clock
        if isinstance(t0_t1, list) and found_idx < len(t0_t1):
            epoch_t0t1.append(t0_t1[found_idx])
        else:
            epoch_t0t1.append(first_pair)

        if np.isnan(sample_rate):
            sample_rate = float(probe.samplerate(epoch_id))

    # 0-based, half-open boundaries per epoch
    bounds0 = np.concatenate(([0], np.cumsum(epoch_counts))).astype(np.int64)
    total_samples = int(bounds0[-1])

    # Step 4b: validate that the kilosort spike indices fit within the NDI epochs.
    if spike_samples_global.size > 0:
        max_sample = int(np.max(spike_samples_global))  # 0-based
        n_overrun = int(
            np.sum((spike_samples_global >= total_samples) | (spike_samples_global < 0))
        )
        if n_overrun > 0:
            raise ValueError(
                "ndi:fun:probe:import:kilosort:probe:sampleOutOfRange: "
                f"{n_overrun} of {spike_samples_global.size} spike sample indices "
                f"fall outside the probe's epochs [0, {total_samples}). The largest "
                f"spike sample index is {max_sample}. This usually means the kilosort "
                "output was sorted on a recording whose concatenation does not match "
                "this probe's epochs (epochtable order or sample rate). Verify that "
                "the sorted data correspond to this probe and that "
                "sum(epoch_sample_counts) in the .metadata sidecar matches the length "
                "of the sorted recording."
            )

    # Step 5: precompute waveform data if requested
    templates = spike_templates = amplitudes = winv = None
    if waveform_source == "templates":
        templates, spike_templates, amplitudes, winv = waveformdata(kdir)

    # Step 6: create the provenance/cluster document (neurons will depend on it).
    # Mirrors the MATLAB 'app' provenance, but records the Python interpreter.
    app_struct = {
        "name": f"Kilosort{kilosort_version} to phy to ndi.fun.probe.import.kilosort",
        "version": kilosort_version,
        "url": "https://github.com/VH-Lab/NDI-python",
        "os": platform.system(),
        "os_version": platform.release(),
        "interpreter": "Python",
        "interpreter_version": platform.python_version()
        or ".".join(map(str, sys.version_info[:3])),
    }

    kc = None
    if not dryRun:
        kc = ndi_document(
            "apps/kilosort/kilosort_clusters",
            **{
                "app.name": app_struct["name"],
                "app.version": app_struct["version"],
                "app.url": app_struct["url"],
                "app.os": app_struct["os"],
                "app.os_version": app_struct["os_version"],
                "app.interpreter": app_struct["interpreter"],
                "app.interpreter_version": app_struct["interpreter_version"],
                "kilosort_clusters.kilosort_directory": f"{kilosort_dir}/{elestr}",
                "kilosort_clusters.curated_output_MD5_checksum": md5_value,
            },
        )
        kc.set_session_id(session.id())
        kc.set_dependency_value("element_id", probe.id)
        session.database_add(kc)

    # Step 7: assemble each cluster that passes the quality filter, then commit
    # them all in batched database writes via ndi.element.timeseries.addMultiple.
    want_labels = [str(s).lower() for s in quality_labels]

    specs: list[dict[str, Any]] = []
    n_imported = 0
    for cid, raw_label in zip(cluster_ids, cluster_labels):
        thislabel = str(raw_label).lower()
        if thislabel not in want_labels:
            if report:
                print(f"{pfx}  Cluster {cid} (label '{raw_label}') skipped.")
            continue
        qnum = quality_values[want_labels.index(thislabel)]

        # this cluster's spikes (0-based global samples)
        spike_idx = np.flatnonzero(spike_clusters == cid)
        g0 = spike_samples_global[spike_idx]
        n_imported += 1

        # neuron name includes the probe reference so neurons from probes that
        # share a name are distinguishable: <name>_<reference>_<cluster id>
        neuron_name = f"{probe.name}_{int(probe.reference)}_{int(cid)}"

        if dryRun:
            print(
                f"{pfx}  Would import cluster {cid} as neuron {neuron_name} "
                f"({raw_label}, quality {qnum}, {spike_idx.size} spikes), with a "
                "neuron_extracellular document and spike trains across "
                f"{n_epochs} epoch(s)."
            )
            continue

        # the mean waveform
        if waveform_source == "templates":
            mean_wf = meanwaveform(
                cid, spike_clusters, spike_templates, amplitudes, templates, winv
            )
            # build waveform_sample_times relative to the trough.
            # MATLAB: [~,troughchan]=min(min(meanWf,[],1)); the column whose
            # column-minimum is smallest. troughsamp is the row of that minimum.
            col_min = np.min(mean_wf, axis=0)
            trough_chan = int(np.argmin(col_min))
            trough_samp = int(np.argmin(mean_wf[:, trough_chan]))  # 0-based row
            n_wf = mean_wf.shape[0]
            # MATLAB: ((0:n-1)' - (troughsamp-1)) / sr, with 1-based troughsamp.
            # In 0-based Python troughsamp is already (matlab_troughsamp - 1).
            wst = (np.arange(n_wf, dtype=np.float64) - trough_samp) / sample_rate
        else:
            mean_wf = np.zeros((0, 0))
            wst = np.zeros((0,))

        # The document is JSON-serialized by the database, so matrix fields are
        # stored as nested Python lists (mirroring how MATLAB jsonencodes them).
        ne = {
            "number_of_samples_per_channel": int(max(mean_wf.shape[0], 1)),
            "number_of_channels": int(max(mean_wf.shape[1] if mean_wf.ndim == 2 else 1, 1)),
            "mean_waveform": mean_wf.tolist(),
            "waveform_sample_times": wst.tolist(),
            "cluster_index": int(cid),
            "quality_number": int(qnum),
            "quality_label": str(raw_label),
        }

        # the neuron_extracellular document (addMultiple sets its element_id)
        neuron_doc = ndi_document(
            "neuron/neuron_extracellular",
            **{
                "app.name": app_struct["name"],
                "app.version": app_struct["version"],
                "app.url": app_struct["url"],
                "app.os": app_struct["os"],
                "app.os_version": app_struct["os_version"],
                "app.interpreter": app_struct["interpreter"],
                "app.interpreter_version": app_struct["interpreter_version"],
                "neuron_extracellular": ne,
            },
        )
        neuron_doc.set_session_id(session.id())
        neuron_doc.set_dependency_value("spike_clusters_id", kc.id)

        # the spike trains, one epoch entry per probe epoch (empty where no spikes)
        epochs: list[dict[str, Any]] = []
        for e_idx in range(n_epochs):
            in_epoch = np.flatnonzero((g0 >= bounds0[e_idx]) & (g0 < bounds0[e_idx + 1]))
            if in_epoch.size == 0:
                spike_times_local = np.zeros((0,))
            else:
                # 0-based local NDI sample (MATLAB added +1 for its 1-based
                # samples2times; Python's samples2times is 0-based, so no +1).
                local0 = g0[in_epoch] - bounds0[e_idx]
                spike_times_local = np.asarray(
                    probe.samples2times(epoch_ids[e_idx], local0.astype(np.float64))
                ).ravel()
            epochs.append(
                {
                    "epoch_id": epoch_ids[e_idx],
                    "epoch_clock": epoch_clock[e_idx],
                    "t0_t1": list(epoch_t0t1[e_idx]),
                    "timepoints": spike_times_local,
                    "datapoints": np.ones_like(spike_times_local),
                }
            )

        specs.append(
            {
                "name": neuron_name,
                "reference": int(probe.reference),
                "type": "spikes",
                "epochs": epochs,
                "extra_documents": [neuron_doc],
            }
        )

        if verbose:
            print(
                f"  Prepared cluster {cid} as neuron {neuron_name} "
                f"({raw_label}, {spike_idx.size} spikes)."
            )

    if not dryRun and specs:
        ndi_element_timeseries.addMultiple(
            session,
            probe,
            specs,
            element_class="ndi.neuron",
            verbose=bool(verbose),
        )

    if report:
        if dryRun:
            print(
                f"{pfx}Done. Would import {n_imported} neuron(s) for probe {elestr}. "
                "No changes were made to the database."
            )
        else:
            print(f"Done. Imported {n_imported} neuron(s) for probe {elestr}.")
