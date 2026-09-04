"""ndi.fun.probe.import.kilosort.neuropixelsmultiplier - int16 encode multiplier.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kilosort/neuropixelsmultiplier.m``
"""

from __future__ import annotations

from typing import Any

__all__ = ["neuropixelsmultiplier", "neuropixels_multiplier", "PROBE_TYPES"]

#: ``canonical name -> (Vmax volts, Imax counts, gain)`` per Neuropixels
#: generation, at the default AP-band gain. The decode used everywhere else in
#: the importer is ``volts = int16 / multiplier``, so the multiplier is the
#: reciprocal of the volts-per-bit scale: ``multiplier = Imax * gain / Vmax``.
PROBE_TYPES = {
    "NP1": (0.6, 512.0, 500.0),  # Neuropixels 1.0, ~2.34 uV/bit
    "NP2": (0.5, 8192.0, 80.0),  # Neuropixels 2.0, ~0.763 uV/bit
}

#: The spellings MATLAB accepts, reduced to the canonical name. Matching is
#: case-insensitive after spaces, dots, underscores and dashes are dropped, so
#: 'NP 1.0' and 'neuropixels1' both land on NP1.
_ALIASES = {
    "np1": "NP1",
    "np10": "NP1",
    "1": "NP1",
    "10": "NP1",
    "neuropixels1": "NP1",
    "neuropixels10": "NP1",
    "np2": "NP2",
    "np20": "NP2",
    "2": "NP2",
    "20": "NP2",
    "neuropixels2": "NP2",
    "neuropixels20": "NP2",
}


def neuropixelsmultiplier(probe_type: str) -> tuple[float, dict[str, Any]]:
    """The int16 encode multiplier for a Neuropixels generation.

    Returns ``(multiplier, info)``; ``info`` carries the constants behind it
    (``Vmax``, ``Imax``, ``gain``, ``uV_per_bit``) and the canonical ``name``.

    A recording made at a non-default AP gain needs a scaled multiplier; the
    multiplier only sets the amplitude UNITS of a recovered waveform and never
    its shape, so a wrong gain rescales the spikes rather than distorting them.
    """
    key = str(probe_type).strip().lower()
    for character in " ._-":
        key = key.replace(character, "")

    canonical = _ALIASES.get(key)
    if canonical is None:
        raise ValueError(
            f"Unrecognized probe type '{probe_type}'. Use 'NP1' (Neuropixels 1.0) "
            "or 'NP2' (Neuropixels 2.0)."
        )

    vmax, imax, gain = PROBE_TYPES[canonical]
    multiplier = (imax * gain) / vmax
    info = {
        "name": canonical,
        "Vmax": vmax,
        "Imax": imax,
        "gain": gain,
        "uV_per_bit": 1e6 / multiplier,
    }
    return multiplier, info


#: The readable spelling beside MATLAB's.
neuropixels_multiplier = neuropixelsmultiplier
