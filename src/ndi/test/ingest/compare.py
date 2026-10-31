"""Compare a raw session with an ingested copy of it, channel by channel.

MATLAB equivalent: ndi.test.ingest.compare
"""

from __future__ import annotations

import math
import warnings
from pathlib import Path
from typing import Any

from .mfdaq_compare import mfdaq_compare


def compare(
    rawSession: Any,  # noqa: N803 - MATLAB's name
    ingestedSession: Any,  # noqa: N803
    *,
    Mode: str = "full",
    ChunkSeconds: float = 60,
    SpotSeconds: float = 300,
    RelativeTolerance: float = 1e-12,
    TimeTolerance: float = 1e-6,
    DaqSystemNames: list[str] | tuple[str, ...] | str = (),
    Verbose: bool = True,
    ShowProgress: bool = True,
) -> tuple[bool, list[dict[str, Any]]]:
    """Compare a raw session with an ingested copy of it.

    MATLAB equivalent: ndi.test.ingest.compare

    Compares the data of *rawSession*, a session that has NOT been ingested,
    with *ingestedSession*, a copy of it that HAS been ingested (e.g., copy
    the session folder and call ``S.ingest()`` on the copy). Each may be an
    ndi session or the path of a session folder. Reads from the ingested copy
    come only from its ingested documents, so a match shows that ingestion
    stored the data faithfully.

    Every multifunction DAQ system of *rawSession* is matched by name to one
    in *ingestedSession* and compared with :func:`mfdaq_compare`. A DAQ system
    missing from *ingestedSession* is reported (check 'daqsystem').

    Returns ``(b, report)``: *b* is True if everything compared equal;
    *report* is the list described in :func:`mfdaq_compare`, for all DAQ
    systems. Nothing stops or prompts on a mismatch.

    Args:
        Mode: 'full' compares every sample; 'spot' one random window per
            channel type per epoch.
        ChunkSeconds: Length of each read in 'full' mode.
        SpotSeconds: Length of the window in 'spot' mode.
        RelativeTolerance: Largest relative difference allowed between raw and
            ingested samples.
        TimeTolerance: Largest difference allowed for time channels.
        DaqSystemNames: Compare only these DAQ systems (default: all).
        Verbose: Print progress and each failed check.
        ShowProgress: Show a progress bar per DAQ system.

    Example::

        b, report = compare(s_raw, s_ingested)
        [r for r in report if not r["ok"]]   # the checks that failed
    """
    from ...daq.mfdaq import ndi_daq_reader_mfdaq

    s1 = _open_session(rawSession)
    s2 = _open_session(ingestedSession)
    daqs1 = _as_list(s1.daqsystem_load(name="(.*)"))
    daqs2 = {str(d.name): d for d in _as_list(s2.daqsystem_load(name="(.*)"))}
    wanted = [DaqSystemNames] if isinstance(DaqSystemNames, str) else list(DaqSystemNames)

    progress_bar = None
    if ShowProgress:
        try:
            from ...gui.component.ProgressBarWindow import ndi_gui_component_ProgressBarWindow

            progress_bar = ndi_gui_component_ProgressBarWindow(
                "NDI Ingest Compare", Overwrite=False
            )
        except Exception as exc:  # noqa: BLE001 - no window is not a failed comparison
            warnings.warn(f"Could not open a progress window: {exc}", stacklevel=2)

    report: list[dict[str, Any]] = []
    for daq in daqs1:
        name = str(daq.name)
        if wanted and name not in wanted:
            continue
        if not isinstance(getattr(daq, "daqreader", None), ndi_daq_reader_mfdaq):
            if Verbose:
                print(f"Skipping {name}: not an ndi_daq_system_mfdaq.")
            continue
        other = daqs2.get(name)
        if other is None:
            msg = "DAQ system is missing from the ingested session."
            report.append(
                {
                    "daqsystem": name,
                    "epoch_id": "",
                    "check": "daqsystem",
                    "ok": False,
                    "message": msg,
                    "t0_t1": [],
                    "samples": 0,
                    "maxAbsDiff": math.nan,
                }
            )
            if Verbose:
                print(f"MISMATCH {name}: {msg}")
            continue
        _, _, here = mfdaq_compare(
            daq,
            other,
            Mode=Mode,
            ChunkSeconds=ChunkSeconds,
            SpotSeconds=SpotSeconds,
            RelativeTolerance=RelativeTolerance,
            TimeTolerance=TimeTolerance,
            Verbose=Verbose,
            ProgressBar=progress_bar,
        )
        report.extend(here)

    b = all(r["ok"] for r in report)
    if Verbose:
        print(f"{len(report)} checks, {sum(not r['ok'] for r in report)} failed.")
    return b, report


def _open_session(s: Any) -> Any:
    """An ndi session, or a session opened from a folder path."""
    if isinstance(s, (str, Path)):
        from ...session.dir import ndi_session_dir

        return ndi_session_dir(str(s))
    if hasattr(s, "daqsystem_load"):
        return s
    raise TypeError("Each session must be an ndi session or the path of a session folder.")


def _as_list(x: Any) -> list[Any]:
    if x is None:
        return []
    if isinstance(x, (list, tuple)):
        return list(x)
    return [x]
