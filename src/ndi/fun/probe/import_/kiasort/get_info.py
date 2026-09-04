"""ndi.fun.probe.import.kiasort.getInfo - summarize a sort without importing it.

MATLAB counterpart: ``+ndi/+fun/+probe/+import/+kiasort/getInfo.m``

Reads a probe's KIASORT output and reports what is in it -- how many units,
how many spikes each has, which would pass the quality filter -- touching
neither the database nor the sort. It is the "look before you import" call,
and the one to reach for when an import produced a surprising number of
neurons.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from .labels import DEFAULT_LABEL, labels
from .results import RES_SORTED, results

__all__ = ["getInfo", "get_info", "kiasort_directory", "SortInfo", "DEFAULT_QUALITY_LABELS"]

#: The labels imported by default. Every unit of a plain KIASORT sort is
#: "good" (see :mod:`.labels`), so this imports all of them.
DEFAULT_QUALITY_LABELS: tuple[str, ...] = (DEFAULT_LABEL,)


def kiasort_directory(
    S: Any,  # noqa: N803 - MATLAB's parameter name
    probe: Any,
    *,
    kiasort_dir: str = "kiasort",
    subdir: str = "kiasort_output",
    noSubFolder: bool = False,  # noqa: N803 - MATLAB's parameter name
) -> tuple[Path, str]:
    """The KIASORT output folder for PROBE, and the probe's element string.

    One place for the path arithmetic every entry point in this package
    repeats, so the importer, the summary and the status all look in exactly
    the same folder -- including the legacy ``|`` folder name that
    ``elementDirectory`` still finds.
    """
    from ....file import elementDirectory

    probedir, _name, _legacy = elementDirectory(Path(S.path) / kiasort_dir, probe)
    element_string = str(probe.elementstring())
    folder = Path(probedir) if noSubFolder or not subdir else Path(probedir) / subdir
    return folder, element_string


class SortInfo:
    """What a KIASORT sort holds -- MATLAB's ``info`` struct, field for field."""

    def __init__(self, **fields: Any):
        #: The KIASORT output directory that was read.
        self.directory: str = fields["directory"]
        #: The ``RES_Sorted`` directory inside it.
        self.res_dir: str = fields["res_dir"]
        #: ``""`` or ``"_curated"``.
        self.suffix: str = fields["suffix"]
        #: Number of units in the sort.
        self.num_units: int = fields["num_units"]
        #: The unit ids.
        self.unit_ids: np.ndarray = fields["unit_ids"]
        #: Each unit's label, parallel to :attr:`unit_ids`.
        self.unit_labels: list[str] = fields["unit_labels"]
        #: The distinct labels present.
        self.unique_tags: list[str] = fields["unique_tags"]
        #: How many units carry each of :attr:`unique_tags`.
        self.tag_counts: list[int] = fields["tag_counts"]
        #: Spikes across all units.
        self.num_spikes_total: int = fields["num_spikes_total"]
        #: Spikes per unit, parallel to :attr:`unit_ids`.
        self.num_spikes: np.ndarray = fields["num_spikes"]
        #: True for each unit the quality filter would import.
        self.would_import: np.ndarray = fields["would_import"]
        #: How many that is.
        self.num_would_import: int = fields["num_would_import"]
        #: Samples per mean waveform, NaN when there are no waveforms.
        self.samples_per_waveform: float = fields["samples_per_waveform"]
        #: Channels per mean waveform, NaN when there are no waveforms.
        self.num_channels: float = fields["num_channels"]

    def __repr__(self) -> str:
        return (
            f"SortInfo(units={self.num_units}, spikes={self.num_spikes_total}, "
            f"would_import={self.num_would_import})"
        )


def getInfo(  # noqa: N802 - MATLAB's function name
    S: Any,  # noqa: N803 - MATLAB's parameter name
    probe: Any,
    *,
    kiasort_dir: str = "kiasort",
    subdir: str = "kiasort_output",
    noSubFolder: bool = False,  # noqa: N803 - MATLAB's parameter name
    curated: bool = False,
    quality_labels: Sequence[str] = DEFAULT_QUALITY_LABELS,
) -> tuple[SortInfo, str]:
    """Summarize the KIASORT output for PROBE. Returns ``(info, summary)``.

    *summary* is the multi-line human-readable rendering of *info*; print it.
    Nothing is imported and nothing in the database is touched.

    MATLAB equivalent: ``ndi.fun.probe.import.kiasort.getInfo``.
    """
    kdir, element_string = kiasort_directory(
        S, probe, kiasort_dir=kiasort_dir, subdir=subdir, noSubFolder=noSubFolder
    )
    if not (kdir / RES_SORTED).is_dir():
        raise FileNotFoundError(f"KIASORT {RES_SORTED} folder not found in {kdir}.")

    found = results(kdir, curated=curated)
    unit_ids, unit_labels = labels(kdir, curated=curated)

    num_spikes = np.array([int(np.sum(found.spike_units == uid)) for uid in unit_ids], dtype=float)

    unique_tags: list[str] = []
    for label in unit_labels:
        if label not in unique_tags:
            unique_tags.append(label)
    tag_counts = [unit_labels.count(tag) for tag in unique_tags]

    wanted = {str(label).lower() for label in quality_labels}
    would_import = np.array([str(label).lower() in wanted for label in unit_labels], dtype=bool)

    samples_per_waveform, num_channels = _waveform_shape(found.unit_stats)

    info = SortInfo(
        directory=str(kdir),
        res_dir=found.res_dir,
        suffix=found.suffix,
        num_units=int(unit_ids.size),
        unit_ids=unit_ids,
        unit_labels=unit_labels,
        unique_tags=unique_tags,
        tag_counts=tag_counts,
        num_spikes_total=int(found.spike_units.size),
        num_spikes=num_spikes,
        would_import=would_import,
        num_would_import=int(would_import.sum()),
        samples_per_waveform=samples_per_waveform,
        num_channels=num_channels,
    )
    return info, summarize(info, element_string, quality_labels)


def _waveform_shape(unit_stats: Any) -> tuple[float, float]:
    """``(samples, channels)`` of the mean waveforms, NaN each when absent."""
    waveforms = getattr(unit_stats, "meanWaveforms", None) if unit_stats else None
    if waveforms is None:
        return float("nan"), float("nan")
    shape = np.asarray(waveforms).shape  # nUnits x nSamples x nChannels
    samples = float(shape[1]) if len(shape) >= 2 else float("nan")
    channels = float(shape[2]) if len(shape) >= 3 else float("nan")
    return samples, channels


def summarize(
    info: SortInfo,
    element_string: str,
    quality_labels: Sequence[str] = DEFAULT_QUALITY_LABELS,
) -> str:
    """The multi-line report MATLAB's second output returns."""
    lines = [f"KIASORT summary for probe '{element_string}'", f"  Directory:        {info.res_dir}"]
    if info.suffix:
        lines.append("  Output:           curated")
    lines.append(f"  Units:            {info.num_units}")
    lines.append(f"  Total spikes:     {info.num_spikes_total}")
    if info.num_units:
        lines.append(
            f"  Spikes/unit:      min {int(info.num_spikes.min())}, "
            f"median {int(round(float(np.median(info.num_spikes))))}, "
            f"max {int(info.num_spikes.max())}"
        )
    lines.append("  Tags:")
    for tag, count in zip(info.unique_tags, info.tag_counts):
        lines.append(f"     {tag}: {count} unit(s)")
    lines.append(
        f"  Would import ({', '.join(str(q) for q in quality_labels)}): "
        f"{info.num_would_import} of {info.num_units} unit(s)"
    )
    if not np.isnan(info.samples_per_waveform):
        lines.append(
            f"  Mean waveforms:   {_plain(info.num_channels)} channels, "
            f"{_plain(info.samples_per_waveform)} samples each"
        )
    else:
        lines.append("  Mean waveforms:   (sorted_samples.mat not present)")
    return "\n".join(lines)


def _plain(value: float) -> str:
    """A count without a trailing ``.0``, as MATLAB's num2str writes it."""
    return "NaN" if np.isnan(value) else str(int(value))


#: The readable spelling beside MATLAB's.
get_info = getInfo
