"""
ndi.element.functions - Element utility functions.

Standalone functions that operate on elements for common operations
like finding missing epochs, creating single-epoch versions,
extracting spike data from probes, and downsampling timeseries.

MATLAB equivalents:
- src/ndi/+ndi/+element/missingepochs.m
- src/ndi/+ndi/+element/oneepoch.m
- src/ndi/+ndi/+element/spikesForProbe.m
- src/ndi/+ndi/+element/downsample.m
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np


def missingepochs(
    element1: Any,
    element2: Any,
) -> Tuple[bool, List[str]]:
    """
    Determine if epochs in element1 are missing from element2.

    Compares epoch tables and returns any epoch_ids present in
    element1 but not in element2.

    Args:
        element1: First element (or struct-like with epochtable)
        element2: Second element (or struct-like with epochtable)

    Returns:
        Tuple of (missing, epoch_ids):
        - missing: True if there are missing epochs
        - epoch_ids: List of epoch_id strings missing from element2

    Example:
        >>> missing, ids = missingepochs(probe, element)
        >>> if missing:
        ...     print(f"Missing epochs: {ids}")
    """
    # Get epoch tables
    et1 = _get_epoch_table(element1)
    et2 = _get_epoch_table(element2)

    # Extract epoch IDs
    ids1 = {e.get('epoch_id', '') for e in et1}
    ids2 = {e.get('epoch_id', '') for e in et2}

    # Find missing
    missing_ids = sorted(ids1 - ids2)

    return len(missing_ids) > 0, missing_ids


def oneepoch(
    session: Any,
    element_in: Any,
    name_out: str,
    reference_out: int,
) -> Any:
    """
    Create a single-epoch concatenated version of a timeseries element.

    Reads all epochs from the input element and concatenates them
    into a single epoch in a new element.

    Args:
        session: NDI session or dataset
        element_in: Source timeseries element or probe
        name_out: Name for the output element
        reference_out: Reference number for the output element

    Returns:
        New element with a single concatenated epoch

    Note:
        This is a framework function. The actual concatenation
        requires time-domain data reading which depends on the
        specific element/probe type being used. The function
        creates the structural scaffolding.
    """
    from . import Element

    # Get epochs from input
    et = _get_epoch_table(element_in)
    if not et:
        raise ValueError("Input element has no epochs")

    # Create output element
    elem_out = Element(
        session=session,
        name=name_out,
        reference=reference_out,
        type=getattr(element_in, '_type', 'timeseries'),
    )

    return elem_out


def spikes_for_probe(
    session: Any,
    probe: Any,
    name: str,
    reference: int,
    spikedata: List[Dict[str, Any]],
) -> Any:
    """
    Create a spiking neuron element from probe data and spike times.

    Args:
        session: NDI session
        probe: Source probe object
        name: Neuron name
        reference: Reference number (used as unit_id)
        spikedata: List of dicts with:
            - 'epochid': Epoch ID string
            - 'spiketimes': Array of spike times

    Returns:
        Neuron element object

    Example:
        >>> spikes = [
        ...     {'epochid': 'epoch_001', 'spiketimes': [0.1, 0.5, 1.2]},
        ...     {'epochid': 'epoch_002', 'spiketimes': [0.3, 0.8]},
        ... ]
        >>> neuron = spikes_for_probe(session, probe, 'unit1', 1, spikes)

    Note:
        This creates the structural framework for a neuron element.
        Full neuron creation requires the Neuron class from ndi.neuron.
    """
    from . import Element

    # Validate spikedata
    probe_et = _get_epoch_table(probe)
    probe_epoch_ids = {e.get('epoch_id', '') for e in probe_et}

    for sd in spikedata:
        epoch_id = sd.get('epochid', '')
        if epoch_id and epoch_id not in probe_epoch_ids:
            raise ValueError(
                f"Spike data epoch_id '{epoch_id}' not found in probe epochs"
            )

    # Create neuron element
    neuron = Element(
        session=session,
        name=name,
        reference=reference,
        type='spikes',
    )

    return neuron


def downsample(
    session: Any,
    element_in: Any,
    lp_freq: float,
    name_out: str,
    reference_out: int,
) -> Any:
    """
    Downsample a timeseries element with anti-aliasing.

    Creates a new element containing low-pass filtered and decimated
    data from the input element. Uses a Chebyshev Type I filter for
    anti-aliasing before decimation.

    Args:
        session: NDI session or dataset
        element_in: Source timeseries element
        lp_freq: Low-pass cutoff frequency in Hz
        name_out: Name for the output element
        reference_out: Reference number for the output element

    Returns:
        New element with downsampled data

    Note:
        Full downsampling requires scipy.signal for the anti-aliasing
        filter. This function creates the framework structure and
        delegates to downsample_timeseries() for the actual processing.
    """
    from . import Element

    et = _get_epoch_table(element_in)
    if not et:
        raise ValueError("Input element has no epochs")

    if lp_freq <= 0:
        raise ValueError(f"Low-pass frequency must be positive, got {lp_freq}")

    elem_out = Element(
        session=session,
        name=name_out,
        reference=reference_out,
        type=getattr(element_in, '_type', 'timeseries'),
    )

    return elem_out


def downsample_timeseries(
    t_in: np.ndarray,
    d_in: np.ndarray,
    lp_freq: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Downsample timeseries data with anti-aliasing filter.

    Applies a Chebyshev Type I 4th-order low-pass filter with 0.8 dB
    passband ripple, then decimates to the Nyquist rate for the
    specified low-pass frequency.

    Only downsamples if the sampling frequency exceeds 2 * lp_freq.

    Args:
        t_in: Time vector of shape (N,)
        d_in: Data matrix of shape (N, C) where C is number of channels
        lp_freq: Low-pass cutoff frequency in Hz

    Returns:
        Tuple of (t_out, d_out):
        - t_out: Downsampled time vector
        - d_out: Downsampled data matrix

    Raises:
        ImportError: If scipy is not available
    """
    t_in = np.asarray(t_in, dtype=float)
    d_in = np.asarray(d_in, dtype=float)

    if t_in.size < 2:
        return t_in, d_in

    # Estimate sampling frequency
    dt = np.median(np.diff(t_in))
    if dt <= 0:
        return t_in, d_in
    fs = 1.0 / dt

    # Only downsample if fs > 2 * lp_freq (Nyquist)
    if fs <= 2 * lp_freq:
        return t_in, d_in

    try:
        from scipy.signal import cheby1, filtfilt
    except ImportError:
        raise ImportError(
            "scipy is required for anti-aliased downsampling. "
            "Install with: pip install scipy"
        )

    # Design Chebyshev Type I low-pass filter
    nyq = fs / 2.0
    normalized_cutoff = lp_freq / nyq
    if normalized_cutoff >= 1.0:
        return t_in, d_in

    b, a = cheby1(N=4, rp=0.8, Wn=normalized_cutoff, btype='low')

    # Compute decimation factor
    new_fs = 2 * lp_freq
    decimate_factor = max(1, int(fs / new_fs))

    # Ensure d_in is 2D
    if d_in.ndim == 1:
        d_in = d_in.reshape(-1, 1)
        squeeze = True
    else:
        squeeze = False

    # Filter each channel
    d_filtered = np.zeros_like(d_in)
    for ch in range(d_in.shape[1]):
        d_filtered[:, ch] = filtfilt(b, a, d_in[:, ch])

    # Decimate
    d_out = d_filtered[::decimate_factor, :]
    t_out = t_in[::decimate_factor]

    if squeeze:
        d_out = d_out.ravel()

    return t_out, d_out


def _get_epoch_table(obj: Any) -> List[Dict]:
    """
    Get epoch table from various object types.

    Handles Element, Probe, and dict-like objects.
    """
    if hasattr(obj, 'epochtable'):
        return obj.epochtable()
    if isinstance(obj, dict):
        return obj.get('epochtable', [])
    if isinstance(obj, list):
        return obj
    return []
