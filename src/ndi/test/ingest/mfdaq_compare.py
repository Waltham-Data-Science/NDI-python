"""Compare raw and ingested data from two multifunction DAQ systems.

MATLAB equivalent: ndi.test.ingest.mfdaq_compare
"""

from __future__ import annotations

import dataclasses
import math
import random
from typing import Any

import numpy as np

#: The continuous channel types compared, sample by sample.
CONTINUOUS_TYPES = ("analog_in", "analog_out", "auxiliary_in", "digital_in", "digital_out", "time")
#: The event channel types compared, over the whole epoch.
EVENT_TYPES = ("event", "marker", "text")


def mfdaq_compare(
    daq1: Any,
    daq2: Any,
    *,
    Mode: str = "full",
    ChunkSeconds: float = 60,
    SpotSeconds: float = 300,
    RelativeTolerance: float = 1e-12,
    TimeTolerance: float = 1e-6,
    Verbose: bool = True,
    ProgressBar: Any = None,
) -> tuple[bool, list[str], list[dict[str, Any]]]:
    """Compare raw and ingested data from two ``ndi_daq_system_mfdaq`` objects.

    MATLAB equivalent: ndi.test.ingest.mfdaq_compare

    Compares the data read through *daq1*, a DAQ system of a session that has
    NOT been ingested, with the data read through *daq2*, the same DAQ system
    in a copy of that session that HAS been ingested. Reads through *daq2*
    come only from the ingested documents, so a match shows that ingestion
    stored the data faithfully.

    For every epoch of *daq1*, matched to *daq2*'s epoch by epoch id, it
    checks:

    - that the epoch exists in *daq2* and is ingested there;
    - the channel list (every channel, matched by name; every field the raw
      reader sets, e.g., type, time channel, sample rate);
    - every continuous channel type present (analog_in, analog_out,
      auxiliary_in, digital_in, digital_out, time): the sample range and the
      samples themselves (to *RelativeTolerance*; time channels to
      *TimeTolerance*);
    - every event channel type present (event, marker, text): the timestamps
      and values over the whole epoch.

    Returns ``(b, errmsg, report)``. *b* is True if every check passed;
    *errmsg* has one message per failed check; *report* has one dict per
    check, with keys ``daqsystem``, ``epoch_id``, ``check`` ('epoch',
    'channel_list' or the channel type), ``ok``, ``message`` ('' when ok),
    ``t0_t1``, ``samples`` (the number compared, continuous types) and
    ``maxAbsDiff`` (the largest absolute difference, continuous types).
    Nothing stops on a mismatch; every difference is reported and the
    comparison continues with the next check.

    Args:
        Mode: 'full' compares every sample of every epoch, *ChunkSeconds* at a
            time; 'spot' compares one randomly placed window of *SpotSeconds*
            per channel type per epoch.
        ChunkSeconds: Length of each read in 'full' mode (bounds memory use).
        SpotSeconds: Length of the window in 'spot' mode.
        RelativeTolerance: Largest difference allowed between raw and ingested
            samples, relative to the larger of the two values. Scaled channels
            can differ in the last bit because the two paths round the scaling
            differently; 0 demands exact equality.
        TimeTolerance: Largest difference allowed for time channels.
        Verbose: Print each epoch as it is compared, and each failed check.
        ProgressBar: A ProgressBarWindow to add a bar to (None: no bar).

    Sample numbers here, as everywhere in this port, are 0-based: a raw
    reader's ``readchannels_epochsamples`` takes 1-based samples and an
    ingested read 0-based ones, and both are called accordingly.
    """
    from ...daq.mfdaq import ndi_daq_reader_mfdaq
    from ...daq.system import ndi_daq_system
    from ...file.navigator import ndi_file_navigator

    if Mode not in ("full", "spot"):
        raise ValueError("Mode must be 'full' or 'spot'.")
    if ChunkSeconds <= 0 or SpotSeconds <= 0:
        raise ValueError("ChunkSeconds and SpotSeconds must be positive.")
    if RelativeTolerance < 0 or TimeTolerance < 0:
        raise ValueError("RelativeTolerance and TimeTolerance must be nonnegative.")
    for daq in (daq1, daq2):
        if not isinstance(getattr(daq, "daqreader", None), ndi_daq_reader_mfdaq):
            raise TypeError("Each DAQ system must be an ndi_daq_system_mfdaq.")

    options = {
        "Mode": Mode,
        "ChunkSeconds": ChunkSeconds,
        "SpotSeconds": SpotSeconds,
        "RelativeTolerance": RelativeTolerance,
        "TimeTolerance": TimeTolerance,
        "Verbose": Verbose,
    }
    report: list[dict[str, Any]] = []
    name = str(daq1.name)

    for daq in (daq1, daq2):
        cache = getattr(daq.session, "cache", None)
        if cache is not None:
            cache.clear()

    et1 = daq1.epochtable()
    et2 = daq2.epochtable()
    by_id2 = {e["epoch_id"]: e for e in et2}
    reader1 = daq1.daqreader
    reader2 = daq2.daqreader
    session2 = daq2.session

    progress_bar, bar_tag = None, ""
    if ProgressBar is not None and et1:
        progress_bar, bar_tag = ndi_daq_system.addIngestProgressBar(
            ProgressBar, f"Comparing {name} ({len(et1)} epochs)"
        )

    def add(epoch_id, check, ok, msg, t0_t1, n=0, mx=math.nan):
        report.append(
            {
                "daqsystem": name,
                "epoch_id": epoch_id,
                "check": check,
                "ok": bool(ok),
                "message": msg,
                "t0_t1": t0_t1,
                "samples": n,
                "maxAbsDiff": mx,
            }
        )
        if not ok and Verbose:
            print(f"  MISMATCH {epoch_id} {check}: {msg}")

    for i, e1 in enumerate(et1, start=1):
        epoch_id = e1["epoch_id"]
        t0_t1 = list(e1["t0_t1"][0])
        files1 = e1["underlying_epochs"]["underlying"]
        if Verbose:
            print(f"Comparing {name} epoch {epoch_id} ({i} of {len(et1)})...")
        try:
            e2 = by_id2.get(epoch_id)
            if e2 is None:
                add(epoch_id, "epoch", False, "Epoch is missing from the ingested session.", t0_t1)
                continue
            files2 = e2["underlying_epochs"]["underlying"]
            if not ndi_file_navigator.isingested(files2):
                add(epoch_id, "epoch", False, "Epoch is not ingested in the second session.", t0_t1)
                continue
            add(epoch_id, "epoch", True, "", t0_t1)

            c1 = reader1.getchannelsepoch(files1)
            c2 = reader2.getchannelsepoch_ingested(files2, session2)
            ok, msg = _compare_channel_lists(c1, c2)
            add(epoch_id, "channel_list", ok, msg, t0_t1)

            # continuous channels, grouped by sample rate so each read is uniform
            for channeltype in CONTINUOUS_TYPES:
                channels = [c.number for c in c1 if c.type == channeltype]
                if not channels:
                    continue
                sr = np.ravel(
                    np.asarray(reader1.samplerate(files1, channeltype, channels), dtype=float)
                )
                for rate in sorted({r for r in sr if not np.isnan(r)}):
                    here = [ch for ch, r in zip(channels, sr) if r == rate]
                    ok, msg, n, mx = _compare_continuous(
                        reader1,
                        reader2,
                        session2,
                        files1,
                        files2,
                        channeltype,
                        here,
                        rate,
                        t0_t1,
                        options,
                    )
                    add(epoch_id, channeltype, ok, msg, t0_t1, n, mx)

            # event channels, over the whole epoch
            for channeltype in EVENT_TYPES:
                channels = [c.number for c in c1 if c.type == channeltype]
                if not channels:
                    continue
                ok, msg = _compare_events(
                    reader1, reader2, session2, files1, files2, channeltype, channels, t0_t1
                )
                add(epoch_id, channeltype, ok, msg, t0_t1)
        finally:
            ndi_daq_system.updateIngestProgressBar(progress_bar, bar_tag, i / len(et1))

    errmsg = [
        f"{r['daqsystem']} {r['epoch_id']} {r['check']}: {r['message']}"
        for r in report
        if not r["ok"]
    ]
    return all(r["ok"] for r in report), errmsg, report


def _compare_channel_lists(c1: list[Any], c2: list[Any]) -> tuple[bool, str]:
    """Same channels (by name) and the same values in every shared field.

    MATLAB compares the fields the two structure arrays share; a raw reader's
    list there often has only name, type and time_channel. Python's
    ChannelInfo always has every field, holding its default where the reader
    set nothing, so a field counts as the raw list's when some raw channel
    holds a value other than the default."""
    d1 = {c.name: _as_dict(c) for c in c1}
    d2 = {c.name: _as_dict(c) for c in c2}
    if sorted(d1) != sorted(d2):
        only1 = ", ".join(sorted(set(d1) - set(d2)))
        only2 = ", ".join(sorted(set(d2) - set(d1)))
        return False, f"Channel names differ. Only raw: {only1}; only ingested: {only2}."
    defaults = {}
    if c1 and dataclasses.is_dataclass(c1[0]):
        defaults = {
            f.name: f.default
            for f in dataclasses.fields(c1[0])
            if f.default is not dataclasses.MISSING
        }
    shared = set.intersection(*(set(d) for d in [*d1.values(), *d2.values()]))
    fields = sorted(
        f
        for f in shared
        if f not in defaults or any(not _same(d[f], defaults[f]) for d in d1.values())
    )
    bad = [f for f in fields if any(not _same(d1[n][f], d2[n][f]) for n in d1)]
    if bad:
        return False, f"Channel list fields differ: {', '.join(bad)}."
    return True, ""


def _as_dict(c: Any) -> dict[str, Any]:
    if hasattr(c, "to_dict"):
        return c.to_dict()
    if dataclasses.is_dataclass(c):
        return dataclasses.asdict(c)
    return dict(c) if isinstance(c, dict) else dict(vars(c))


def _same(a: Any, b: Any) -> bool:
    """Equality in which NaN equals NaN (MATLAB's isequaln) and 1 == 1.0."""
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


def _compare_continuous(
    reader1, reader2, session2, files1, files2, channeltype, channels, rate, t0_t1, options
) -> tuple[bool, str, int, float]:
    """Compare the samples of one channel type at one sample rate."""
    n_compared = 0
    max_abs_diff = 0.0
    is_time = channeltype == "time"

    s1 = np.ravel(reader1.epochtimes2samples(channeltype, channels, files1, np.asarray(t0_t1)))
    s2 = np.ravel(
        reader2.epochtimes2samples_ingested(
            channeltype, channels, files2, np.asarray(t0_t1), session2
        )
    )
    s1 = [int(round(float(x))) for x in s1]
    s2 = [int(round(float(x))) for x in s2]
    if s1 != s2:
        return (
            False,
            f"Sample range differs: raw {s1[0]}..{s1[-1]}, ingested {s2[0]}..{s2[-1]}.",
            0,
            max_abs_diff,
        )
    s_first, s_last = s1[0], s1[-1]

    if options["Mode"] == "full":
        chunk = max(1, round(options["ChunkSeconds"] * rate))
        starts = range(s_first, s_last + 1, chunk)
    else:
        chunk = max(1, round(options["SpotSeconds"] * rate))
        span = max(0, s_last - s_first + 1 - chunk)
        starts = [s_first + random.randint(0, span)]

    for s0 in starts:
        s_end = min(s0 + chunk - 1, s_last)
        try:
            # a raw reader's samples are 1-based
            d1 = np.asarray(
                reader1.readchannels_epochsamples(channeltype, channels, files1, s0 + 1, s_end + 1)
            )
        except Exception as exc:  # noqa: BLE001 - report it and go on
            return (
                False,
                f"Reading the raw data failed at samples {s0}..{s_end}: {exc}",
                n_compared,
                max_abs_diff,
            )
        try:
            d2 = np.asarray(
                reader2.readchannels_epochsamples_ingested(
                    channeltype, channels, files2, s0, s_end, session2
                )
            )
        except Exception as exc:  # noqa: BLE001 - report it and go on
            return (
                False,
                f"Reading the ingested data failed at samples {s0}..{s_end}: {exc}",
                n_compared,
                max_abs_diff,
            )
        if d1.shape != d2.shape:
            return (
                False,
                f"Sizes differ at samples {s0}..{s_end}: raw {list(d1.shape)}, "
                f"ingested {list(d2.shape)}.",
                n_compared,
                max_abs_diff,
            )
        n_compared += d1.shape[0] if d1.ndim else 0
        if d1.size == 0:
            continue
        a = d1.astype(float).reshape(d1.shape[0], -1)
        b = d2.astype(float).reshape(d2.shape[0], -1)
        d = np.abs(a - b)
        d[np.isnan(a) & np.isnan(b)] = 0
        d[np.isnan(a) ^ np.isnan(b)] = np.inf
        max_abs_diff = max(max_abs_diff, float(np.max(d)))
        if is_time:
            allowed = options["TimeTolerance"]
        else:
            allowed = options["RelativeTolerance"] * np.maximum(np.abs(a), np.abs(b))
        too_large = d > allowed
        if np.any(too_large):
            excess = np.where(too_large, d, -np.inf)
            row, col = np.unravel_index(int(np.argmax(excess)), excess.shape)
            return (
                False,
                f"Data differ (max |difference| {max_abs_diff:g}) starting by sample "
                f"{s0 + int(row)}, channel {channels[int(col)]} (read window {s0}..{s_end}).",
                n_compared,
                max_abs_diff,
            )
    return True, "", n_compared, max_abs_diff


def _compare_events(
    reader1, reader2, session2, files1, files2, channeltype, channels, t0_t1
) -> tuple[bool, str]:
    """Compare the timestamps and values of event-type channels."""
    try:
        t1, d1 = reader1.readevents_epochsamples(channeltype, channels, files1, t0_t1[0], t0_t1[1])
        t2, d2 = reader2.readevents_epochsamples_ingested(
            channeltype, channels, files2, t0_t1[0], t0_t1[1], session2
        )
    except Exception as exc:  # noqa: BLE001 - report it and go on
        return False, f"Reading events failed: {exc}"
    if not _events_equal(t1, t2):
        return False, "Event timestamps differ."
    if not _events_equal(d1, d2):
        return False, "Event values (codes/text) differ."
    return True, ""


def _events_equal(a: Any, b: Any) -> bool:
    """isequaln for event arrays: per channel when given as lists; every empty
    array equal to every other (MATLAB's normalizeEmpty); NaN equal to NaN."""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        a_is_channels = all(isinstance(x, (list, tuple, np.ndarray)) for x in a)
        b_is_channels = all(isinstance(x, (list, tuple, np.ndarray)) for x in b)
        if a_is_channels and b_is_channels:
            return len(a) == len(b) and all(_events_equal(x, y) for x, y in zip(a, b))
    x = np.asarray(a, dtype=object if _is_text(a) else None)
    y = np.asarray(b, dtype=object if _is_text(b) else None)
    if x.size == 0 and y.size == 0:
        return True
    if x.dtype == object or y.dtype == object:
        return [str(v) for v in np.ravel(x)] == [str(v) for v in np.ravel(y)]
    if np.squeeze(x).shape != np.squeeze(y).shape:
        return False
    return bool(np.array_equal(np.squeeze(x), np.squeeze(y), equal_nan=True))


def _is_text(a: Any) -> bool:
    flat = a if isinstance(a, (list, tuple)) else np.ravel(np.asarray(a, dtype=object))
    return any(isinstance(v, str) for v in flat)
