"""ndi.fun.probe.import_.epoch_map - the sample<->epoch map both importers share.

Python only; MATLAB inlines this in each importer.

WHY IT IS SHARED RATHER THAN COPIED
``ndi.fun.probe.export.binary`` writes a probe's epochs end to end into one
binary, and every sorter then reports spikes as sample offsets into THAT
stream. Turning an offset back into an epoch and a time therefore has exactly
one correct answer, and both importers -- Kilosort's and KIASORT's -- have to
compute it the same way or the same recording imports differently depending
on which sorter ran. Two copies of this arithmetic would be two chances to
drift, and drift here does not raise: it silently files spikes under the
wrong epoch.

The counting mirrors the export: epochs in ``epochtable`` order, each epoch's
length from ``times2samples`` over its FIRST ``t0_t1``, and boundaries as a
0-based half-open cumulative sum.
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = [
    "SPIKE_CLOCK",
    "EpochMap",
    "epoch_map",
    "epochtable",
    "clocks",
    "ranges",
    "first_range",
    "clock_index",
]

#: The clock spike times are stored against. Local to the epoch, which is what
#: makes a spike time meaningful without the syncgraph.
SPIKE_CLOCK = "dev_local_time"


class EpochMap:
    """Where each epoch sits in the concatenated stream that was exported."""

    def __init__(
        self,
        epoch_ids: list[str],
        counts: list[int],
        clocks: list[Any],
        t0_t1: list[Any],
        sample_rate: float,
    ):
        #: Epoch ids, in epochtable order -- the export's order.
        self.epoch_ids = epoch_ids
        #: Samples in each epoch.
        self.counts = counts
        #: Each epoch's ``dev_local_time`` clock.
        self.clocks = clocks
        #: Each epoch's ``[t0 t1]`` on that clock.
        self.t0_t1 = t0_t1
        #: Sample rate, from the first epoch.
        self.sample_rate = sample_rate
        #: 0-based half-open boundaries; ``bounds[i]`` starts epoch ``i``.
        self.bounds = np.concatenate([[0], np.cumsum(counts)]).astype(float)

    @property
    def total_samples(self) -> float:
        """Samples across every epoch: the length the sorted recording should be."""
        return float(self.bounds[-1])

    def __len__(self) -> int:
        return len(self.epoch_ids)

    def check_in_range(self, spike_samples: np.ndarray, sorter: str) -> None:
        """Raise unless every spike sample falls inside the probe's epochs.

        A sort of a DIFFERENT recording lands here: its indices run past the
        end of this probe's epochs. Caught now, that is one clear error;
        missed, the out-of-range spikes are silently dropped and the neurons
        that survive are a subset nobody can account for.
        """
        samples = np.asarray(spike_samples, dtype=float)
        if samples.size == 0:
            return
        total = self.total_samples
        overrun = int(np.sum((samples >= total) | (samples < 0)))
        if overrun:
            raise ValueError(
                f"{overrun} of {samples.size} spike sample indices fall outside the "
                f"probe's epochs [0, {total:g}). The largest spike sample index is "
                f"{samples.max():g}. This usually means the {sorter} output was sorted "
                "on a recording whose concatenation does not match this probe's epochs "
                "(epochtable order or sample rate)."
            )

    def epoch_slice(self, index: int, spike_samples: np.ndarray) -> np.ndarray:
        """The local sample of each spike falling in epoch INDEX.

        NO ``+1`` HERE, where MATLAB has one. MATLAB's
        ``probe.samples2times`` is 1-BASED -- sample 1 is the epoch's first --
        so MATLAB converts a 0-based offset by adding one. This port's
        ``samples2times`` is 0-based, so adding one would place every spike a
        sample late: invisible in a raster, and 33 microseconds at 30 kHz.
        Each language's arithmetic is right for its own indexing, and the
        times that come out agree, which is the thing that has to be true.
        """
        samples = np.asarray(spike_samples, dtype=float)
        start, stop = self.bounds[index], self.bounds[index + 1]
        inside = samples[(samples >= start) & (samples < stop)]
        return inside - start


def epoch_map(probe_obj: Any) -> EpochMap:
    """Build the :class:`EpochMap` for PROBE_OBJ.

    Raises:
        ValueError: when an epoch has no ``dev_local_time`` clock, which is
            the clock spike times are stored against.
    """
    table, _hash = epochtable(probe_obj)

    epoch_ids: list[str] = []
    counts: list[int] = []
    epoch_clocks: list[Any] = []
    epoch_ranges: list[Any] = []
    sample_rate = float("nan")

    for entry in table:
        epoch_id = entry["epoch_id"]
        epoch_ids.append(epoch_id)
        first, last = probe_obj.times2samples(epoch_id, first_range(entry))
        counts.append(int(last) - int(first) + 1)

        index = clock_index(entry, SPIKE_CLOCK)
        if index is None:
            raise ValueError(f"Epoch {epoch_id} has no '{SPIKE_CLOCK}' clock.")
        epoch_clocks.append(clocks(entry)[index])
        epoch_ranges.append(ranges(entry)[index])

        if sample_rate != sample_rate:  # still NaN
            sample_rate = float(probe_obj.samplerate(epoch_id))

    return EpochMap(epoch_ids, counts, epoch_clocks, epoch_ranges, sample_rate)


def epochtable(probe_obj: Any) -> tuple[list[dict[str, Any]], Any]:
    """PROBE_OBJ's epoch table, whichever shape it returns.

    ndi.epoch.epochset.epochtable returns ``(table, hashvalue)``; MATLAB's
    returns the table alone.
    """
    result = probe_obj.epochtable()
    if isinstance(result, tuple):
        return list(result[0]), result[1]
    return list(result), None


def clocks(entry: dict[str, Any]) -> list[Any]:
    """An epoch's clocks, as a list however the entry stores them."""
    entry_clocks = entry.get("epoch_clock") or []
    return list(entry_clocks) if isinstance(entry_clocks, (list, tuple)) else [entry_clocks]


def ranges(entry: dict[str, Any]) -> list[Any]:
    """An epoch's ``t0_t1`` pairs, one per clock, as a list of pairs."""
    entry_ranges = entry.get("t0_t1") or []
    if entry_ranges and not isinstance(entry_ranges[0], (list, tuple, np.ndarray)):
        return [entry_ranges]
    return list(entry_ranges)


def first_range(entry: dict[str, Any]) -> Any:
    """The epoch's first ``[t0 t1]``, which is what export.binary counted with."""
    entry_ranges = ranges(entry)
    return entry_ranges[0] if entry_ranges else (0.0, 0.0)


def clock_index(entry: dict[str, Any], clock_name: str) -> int | None:
    """Index of the epoch's CLOCK_NAME clock, or None when it has none."""
    for index, clock in enumerate(clocks(entry)):
        if (getattr(clock, "type", None) or str(clock)) == clock_name:
            return index
    return None
