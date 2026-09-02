"""ndi.fun.probe.export - write probe data in the flat int16 format spike sorters read.

MATLAB counterpart: ``+ndi/+fun/+probe/+export/`` (``binary.m``,
``all_binary.m``, ``autoMultiplier.m``, ``oneProbe.m``). MATLAB's package
becomes one module here, as ``+ndi/+fun/+export/`` did in
:mod:`ndi.fun.export`.

WHAT THE MULTIPLIER MEANS, AND WHICH WAY IT POINTS
The multiplier is applied in the ENCODE direction::

    int16_written = multiplier * physical_data

so it is the RECIPROCAL of the factor that decodes stored int16 back to
physical units. Intan int16 decode to microvolts via ``uV = int16 * 0.195``,
so the encode multiplier is ``1/0.195`` -- the default of :func:`all_binary`
and of :func:`autoMultiplier` for floating-point data. For SpikeGLX volts it
is ``(512*500)/0.6``, which has to be passed explicitly. Getting this
backwards does not raise: it writes a file whose spikes are 26x too small.

THE METADATA SIDECAR IS THE MATLAB ONE
``binary`` writes ``<outputfile>.metadata`` through
``vlt.file.saveStructArray``, the tab-delimited form MATLAB writes, rather
than a bespoke text layout. That is what lets
:func:`ndi.fun.probe.geometry.writeKilosortMap` recover ``num_channels``
from a sidecar written by either language, and what lets a sidecar written
here be read by MATLAB's ``vlt.file.loadStructArray``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

__all__ = [
    "binary",
    "all_binary",
    "autoMultiplier",
    "auto_multiplier",
    "oneProbe",
    "one_probe",
    "INTAN_MULTIPLIER",
    "CHUNK_DURATION",
]

#: The Intan microvolt encode default: uV decode by ``int16 * 0.195``.
INTAN_MULTIPLIER = 1 / 0.195

#: Seconds of data read and written at a time, as MATLAB reads them.
CHUNK_DURATION = 100


def binary(
    probe: Any,
    outputfile: str | Path,
    *,
    multiplier: float = 1.0,
    verbose: int | bool = 1,
    precision: str = "int16",
    noBinary: bool = False,  # noqa: N803 (MATLAB mirror)
    progressfcn: Any = None,
) -> None:
    """Export *probe*'s data to an int16 binary file, plus a metadata sidecar.

    Channels are interleaved sample by sample, which is the layout Kilosort
    and KIASORT read, and epochs are written end to end in epoch-table order
    -- the sidecar's ``epoch_sample_counts`` is how a reader cuts them apart
    again.

    Args:
        probe: an ``ndi.element`` or ``ndi.probe`` of type ``n-trode``.
        outputfile: path of the binary to write.
        multiplier: encode multiplier, ``int16 = multiplier * physical``.
        verbose: 0/1, whether to report each epoch and chunk.
        precision: NumPy dtype string for the samples written.
        noBinary: write only the ``.metadata`` sidecar. Useful when the
            sorted data already exist (from SpikeGLX, say) and only the
            epoch and sample bookkeeping is needed to set up an import.
        progressfcn: optional ``f(fraction, message)`` called after each
            chunk, ``fraction`` running 0..1 across all epochs.

    MATLAB equivalent: ``ndi.fun.probe.export.binary``.
    """
    outputfile = Path(outputfile)
    metafile = outputfile.with_name(outputfile.name + ".metadata")

    et, _ = probe.epochtable()

    dtype = np.dtype(precision)
    epoch_sample_counts: list[int] = []
    epoch_sample_rates: list[float] = []
    num_channels: int | None = None

    # Total chunk count across all epochs, so the progress fraction is over
    # the whole export rather than restarting at each epoch.
    total_chunks = 0
    if not noBinary and progressfcn is not None:
        for entry in et:
            t0, t1 = _epoch_t0_t1(entry)
            total_chunks += len(_colon(t0, CHUNK_DURATION, t1))
        total_chunks = max(total_chunks, 1)
    done_chunks = 0

    fid = None if noBinary else open(outputfile, "wb")
    try:
        for e_index, entry in enumerate(et):
            if verbose:
                print(f"Processing epoch {e_index + 1} of {len(et)}.")

            epoch_id = entry.get("epoch_id", e_index + 1)
            t0, t1 = _epoch_t0_t1(entry)

            samples_here = probe.times2samples(epoch_id, np.array([t0, t1]))
            epoch_sample_counts.append(int(samples_here[1] - samples_here[0] + 1))
            sample_rate = float(probe.samplerate(epoch_id))
            epoch_sample_rates.append(sample_rate)
            single_sample_time = 1.0 / sample_rate if sample_rate > 0 else 0.0

            if noBinary:
                # The channel count is still wanted for the sidecar. One
                # sample is cheap; a whole epoch is not.
                if num_channels is None:
                    data, _t, _ref = probe.readtimeseries(epoch=epoch_id, t0=t0, t1=t0)
                    num_channels = _channel_count(data)
                continue

            chunk_times = _colon(t0, CHUNK_DURATION, t1)
            for c_index, chunk_start in enumerate(chunk_times):
                if verbose:
                    print(
                        f"  Processing epoch {e_index + 1}, "
                        f"chunk {c_index + 1} of {len(chunk_times)}."
                    )
                start_time = float(chunk_start)
                end_time = min(chunk_start + CHUNK_DURATION - single_sample_time, t1)
                data, _t, _ref = probe.readtimeseries(epoch=epoch_id, t0=start_time, t1=end_time)
                if data is not None and len(data) > 0:
                    num_channels = _channel_count(data)
                    fid.write(_interleaved_bytes(multiplier * data, dtype))
                done_chunks += 1
                if progressfcn is not None:
                    progressfcn(
                        done_chunks / total_chunks,
                        f"epoch {e_index + 1}/{len(et)}, "
                        f"chunk {c_index + 1}/{len(chunk_times)}",
                    )
    finally:
        if fid is not None:
            fid.close()

    write_metadata(
        metafile,
        epoch_sample_counts=epoch_sample_counts,
        epoch_sample_rates=epoch_sample_rates,
        multiplier=multiplier,
        num_channels=num_channels,
        probe_name=str(probe.elementstring()),
    )


def all_binary(
    S: Any,  # noqa: N803 (MATLAB mirror)
    *,
    binary_dir: str = "kilosort",
    binaryFileName: str = "kilosort.bin",  # noqa: N803 (MATLAB mirror)
    verbose: int | bool = 1,
    multiplier: float = INTAN_MULTIPLIER,
    noBinary: bool = False,  # noqa: N803 (MATLAB mirror)
) -> None:
    """Export every n-trode probe of session *S* with one fixed multiplier.

    Creates ``<S.path>/<binary_dir>``, and inside it one folder per probe
    (named by :func:`ndi.fun.file.elementDirectory`, so a folder written by
    an older NDI is reused rather than duplicated) holding
    *binaryFileName*.

    MATLAB equivalent: ``ndi.fun.probe.export.all_binary``.
    """
    from ..file import elementDirectory

    if verbose:
        print(f"About to look for probes in {S.reference}")

    probe_list = S.getprobes(type="n-trode")

    if verbose:
        print(f"Found {len(probe_list)} probe(s) of type 'n-trode'.")

    binary_path = Path(S.path) / binary_dir
    binary_path.mkdir(parents=True, exist_ok=True)

    for probe in probe_list:
        if verbose:
            print(f"Now working on probe {probe.elementstring()}.")
        this_path = Path(elementDirectory(binary_path, probe)[0])
        this_path.mkdir(parents=True, exist_ok=True)
        binary(
            probe,
            this_path / binaryFileName,
            verbose=verbose,
            multiplier=multiplier,
            noBinary=noBinary,
        )

    if verbose:
        print(f"Done processing {S.reference}")


def autoMultiplier(probe: Any) -> float:  # noqa: N802 (MATLAB mirror)
    """Pick an int16 encode multiplier from what *probe* actually returns.

    Integer-class samples are already int16-style counts, so 1 passes them
    through losslessly. Anything else is floating-point physical units, and
    gets the Intan microvolt default ``1/0.195``.

    That default ASSUMES INTAN. SpikeGLX/Neuropixels data arrive in volts
    and need ``multiplier=(512*500)/0.6`` passed explicitly; when in doubt,
    read a sample and look at its class and magnitude.

    MATLAB equivalent: ``ndi.fun.probe.export.autoMultiplier``.
    """
    try:
        et, _ = probe.epochtable()
        if not et:
            return INTAN_MULTIPLIER
        t0, _t1 = _epoch_t0_t1(et[0])
        data, _t, _ref = probe.readtimeseries(epoch=et[0].get("epoch_id", 1), t0=t0, t1=t0)
        if data is not None and np.issubdtype(np.asarray(data).dtype, np.integer):
            return 1.0
    except Exception:  # noqa: BLE001 - an unsamplable probe keeps the default
        return INTAN_MULTIPLIER
    return INTAN_MULTIPLIER


def oneProbe(  # noqa: N802 (MATLAB mirror)
    S: Any,  # noqa: N803 (MATLAB mirror)
    probe: Any,
    *,
    binary_dir: str = "kiasort",
    binaryFileName: str = "kiasort.bin",  # noqa: N803 (MATLAB mirror)
    multiplier: float | None = None,
    channelMap: bool = True,  # noqa: N803 (MATLAB mirror)
    progressfcn: Any = None,
    verbose: int | bool = 1,
) -> dict[str, Any]:
    """Export one probe's binary and its channel map, into the sorter's folder.

    Writes ``<S.path>/<binary_dir>/<probe folder>/<binaryFileName>`` and,
    unless *channelMap* is False, a Kilosort-style ``channel_map.mat``
    beside it, built from the probe's assigned electrode geometry. A probe
    with no geometry gets a DEFAULT SINGLE-COLUMN LINEAR map instead --
    enough to let a sorter run, and usually wrong for a real array, which is
    why the returned ``hadGeometry`` says which of the two happened.

    Returns a dict with ``binaryFile``, ``multiplier``, ``channelMapFile``
    (``""`` when none was written) and ``hadGeometry`` -- MATLAB's STATUS
    struct, as a dict for the same reason ``SessionApp.list`` returns dicts.

    MATLAB equivalent: ``ndi.fun.probe.export.oneProbe``.
    """
    from ..file import elementDirectory
    from .channel_count import channelCount
    from .geometry import toKilosortMap, writeKilosortMap

    probedir = Path(elementDirectory(Path(S.path) / binary_dir, probe)[0])
    probedir.mkdir(parents=True, exist_ok=True)
    binaryfile = probedir / binaryFileName

    mult = autoMultiplier(probe) if multiplier is None else float(multiplier)

    binary(probe, binaryfile, multiplier=mult, verbose=verbose, progressfcn=progressfcn)

    status: dict[str, Any] = {
        "binaryFile": str(binaryfile),
        "multiplier": mult,
        "channelMapFile": "",
        "hadGeometry": False,
    }

    if channelMap:
        cmf = probedir / "channel_map.mat"
        had_geometry, _ = toKilosortMap(S, probe, cmf, verbose=verbose)
        status["hadGeometry"] = had_geometry
        if not had_geometry:
            # No geometry on file: a linear placeholder, if we know how many
            # channels to lay out. If we do not, no map is better than a map
            # of the wrong width.
            nch = channelCount(probe)
            if nch:
                writeKilosortMap(cmf, num_channels=nch, verbose=verbose)
        if cmf.is_file():
            status["channelMapFile"] = str(cmf)

    return status


def write_metadata(
    metafile: str | Path,
    *,
    epoch_sample_counts: list[int],
    epoch_sample_rates: list[float],
    multiplier: float,
    num_channels: int | None,
    probe_name: str,
) -> None:
    """Write the ``.metadata`` sidecar beside an exported binary.

    The field order is MATLAB's ``var2struct`` order, and the writer is
    ``vlt.file.saveStructArray``, so the file is the one MATLAB writes and
    ``vlt.file.loadStructArray`` reads on either side.
    """
    from vlt.file import saveStructArray

    saveStructArray(
        str(metafile),
        [
            {
                "epoch_sample_counts": list(epoch_sample_counts),
                "epoch_sample_rates": list(epoch_sample_rates),
                "multiplier": multiplier,
                "num_channels": 0 if num_channels is None else int(num_channels),
                "probe_name": probe_name,
            }
        ],
    )


# ----------------------------------------------------------------------
# module helpers
# ----------------------------------------------------------------------
def _colon(start: float, step: float, stop: float) -> list[float]:
    """MATLAB's ``start:step:stop``.

    Not ``numpy.arange``: for a single-sample epoch (``start == stop``)
    MATLAB yields one chunk and arange yields none, which would write
    nothing and report success.
    """
    if step <= 0 or stop < start:
        return []
    count = int(np.floor((stop - start) / step)) + 1
    return [start + i * step for i in range(count)]


def _epoch_t0_t1(entry: dict[str, Any]) -> tuple[float, float]:
    """The ``[t0 t1]`` of an epoch-table entry, as MATLAB's ``t0_t1{1}``.

    The entry holds either the pair itself or a list of pairs, one per time
    reference, of which MATLAB takes the first.
    """
    t0_t1 = entry.get("t0_t1", [])
    if isinstance(t0_t1, (list, tuple)) and len(t0_t1) > 0:
        first = t0_t1[0]
        if isinstance(first, (list, tuple, np.ndarray)):
            t0_t1 = first
    if isinstance(t0_t1, (list, tuple, np.ndarray)) and len(t0_t1) >= 2:
        return float(t0_t1[0]), float(t0_t1[1])
    raise ValueError(f"Epoch table entry has no usable t0_t1: {entry.get('epoch_id')!r}")


def _interleaved_bytes(data: Any, dtype: np.dtype) -> bytes:
    """A block of samples in the order a sorter reads it.

    Kilosort and KIASORT read channel-interleaved: every channel's sample 1,
    then every channel's sample 2. MATLAB gets there by transposing and
    letting ``fwrite`` write column-major; the same bytes are the
    (samples x channels) block written in C order, which is what this does.

    The previous port here transposed AND wrote in C order, which is one
    transpose too many: it wrote each channel end to end. Nothing downstream
    rejects that file -- a sorter reads it as a recording with the sample
    count and channel count swapped -- so it is pinned by a test rather than
    left to be noticed.
    """
    return np.ascontiguousarray(np.asarray(data).astype(dtype)).tobytes(order="C")


def _channel_count(data: Any) -> int:
    """Channels in a ``readtimeseries`` block: its second dimension."""
    array = np.asarray(data)
    return int(array.shape[1]) if array.ndim == 2 else 1


#: snake_case spellings, the house style for new code.
auto_multiplier = autoMultiplier
one_probe = oneProbe
