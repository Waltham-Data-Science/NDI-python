"""
ndi.fun.probe.export_binary - Export probe data to binary files.

MATLAB equivalents:
  +ndi/+fun/+probe/export_binary.m
  +ndi/+fun/+probe/export_all_binary.m
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import numpy as np


def export_binary(
    probe: Any,
    outputfile: str | Path,
    *,
    multiplier: float = 1.0,
    verbose: bool = True,
    precision: str = "int16",
) -> None:
    """Export data from a probe to a binary file.

    MATLAB equivalent: ndi.fun.probe.export_binary

    Exports data from *probe* (an :class:`ndi.element.Element` or
    :class:`ndi.probe.Probe` of type ``n-trode``) to a binary file.
    Before converting to the output precision the data are scaled by
    *multiplier*.  A text metadata file is created alongside *outputfile*
    with the extension ``.metadata``.

    Args:
        probe: An NDI probe/element object with ``epochtable``,
            ``times2samples``, ``readtimeseries``, ``samplerate``, and
            ``elementstring`` methods.
        outputfile: Path for the output binary file.
        multiplier: Scaling factor applied to data before conversion.
        verbose: If ``True``, print progress messages.
        precision: NumPy-compatible dtype string for the output
            (default ``'int16'``).
    """
    outputfile = Path(outputfile)
    metafile = outputfile.with_suffix(outputfile.suffix + ".metadata")

    et = probe.epochtable()
    if isinstance(et, tuple):
        et = et[0]

    dtype = np.dtype(precision)
    chunk_duration = 100  # seconds

    epoch_sample_counts: list[int] = []
    epoch_sample_rates: list[float] = []
    num_channels = 0

    with open(outputfile, "wb") as fid:
        for e_idx, entry in enumerate(et):
            epoch_id = entry.get("epoch_id", e_idx + 1)
            if verbose:
                print(
                    f"Processing epoch {e_idx + 1} of {len(et)}."
                )

            t0_t1 = entry.get("t0_t1", [])
            if isinstance(t0_t1, list) and len(t0_t1) > 0:
                t0_t1_pair = t0_t1[0]
            else:
                t0_t1_pair = t0_t1

            if isinstance(t0_t1_pair, (list, tuple, np.ndarray)) and len(t0_t1_pair) >= 2:
                t_start = float(t0_t1_pair[0])
                t_end = float(t0_t1_pair[1])
            else:
                continue

            samples = probe.times2samples(epoch_id, np.array([t_start, t_end]))
            sample_count = int(samples[1] - samples[0] + 1)
            epoch_sample_counts.append(sample_count)

            sr = probe.samplerate(epoch_id)
            epoch_sample_rates.append(float(sr))
            single_sample_time = 1.0 / sr if sr > 0 else 0.0

            chunk_starts = np.arange(t_start, t_end, chunk_duration)
            for c_idx, cs in enumerate(chunk_starts):
                if verbose:
                    print(
                        f"  Processing epoch {e_idx + 1}, "
                        f"chunk {c_idx + 1} of {len(chunk_starts)}."
                    )
                start_time = float(cs)
                end_time = min(cs + chunk_duration - single_sample_time, t_end)

                data, _t, _tr = probe.readtimeseries(
                    epoch=epoch_id, t0=start_time, t1=end_time
                )
                if data is None or len(data) == 0:
                    continue

                num_channels = data.shape[1] if data.ndim == 2 else 1

                # Scale and convert — write channel-interleaved (transposed)
                scaled = (multiplier * data).T
                out = scaled.astype(dtype)
                fid.write(out.tobytes())

    # Write metadata file
    probe_name = probe.elementstring()
    with open(metafile, "w") as mf:
        mf.write(f"epoch_sample_counts: {epoch_sample_counts}\n")
        mf.write(f"epoch_sample_rates: {epoch_sample_rates}\n")
        mf.write(f"multiplier: {multiplier}\n")
        mf.write(f"num_channels: {num_channels}\n")
        mf.write(f"probe_name: {probe_name}\n")


def export_all_binary(
    session: Any,
    *,
    kilosort_dir: str = "kilosort",
    verbose: bool = True,
    multiplier: float = 1 / 0.195,
) -> None:
    """Export all n-trode probes in a session to binary files.

    MATLAB equivalent: ndi.fun.probe.export_all_binary

    Creates a *kilosort_dir* directory inside the session path.  For each
    probe of type ``n-trode``, a subdirectory named after the probe's
    element string is created and a ``kilosort.bin`` file is written using
    :func:`export_binary`.

    Args:
        session: An NDI session object (must have ``path`` and
            ``getprobes`` attributes).
        kilosort_dir: Name of the output subdirectory (default
            ``'kilosort'``).
        verbose: If ``True``, print progress messages.
        multiplier: Scaling factor (default ``1/0.195``, assumes Intan
            data).
    """
    if verbose:
        print(f"About to look for probes in {session.reference}")

    probe_list = session.getprobes(type="n-trode")

    if verbose:
        print(f"Found {len(probe_list)} probe(s) of type 'n-trode'.")

    kilosort_path = Path(session.path) / kilosort_dir
    kilosort_path.mkdir(parents=True, exist_ok=True)

    for probe in probe_list:
        elestr = probe.elementstring()
        if verbose:
            print(f"Now working on probe {elestr}.")

        # Replace spaces with underscores for directory name
        safe_name = elestr.replace(" ", "_")
        this_path = kilosort_path / safe_name
        this_path.mkdir(parents=True, exist_ok=True)

        outfile = this_path / "kilosort.bin"
        export_binary(
            probe,
            outfile,
            multiplier=multiplier,
            verbose=verbose,
        )

    if verbose:
        print(f"Done processing {session.reference}")
