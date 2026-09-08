"""Say what the launch is doing, and how long each part took.

Opening a large section takes tens of seconds before anything is drawn,
and every one of those seconds is spent somewhere specific: reading a
26 MB cell table, placing twelve million contour vertices, handing half
a million polygons to napari. Without this the whole wait is one opaque
block and the only available theory is "NDI is slow".

Timings go to STDERR so they interleave with the other launch notes and
stay out of anything a caller pipes. On by default: a program that makes
you wait owes you an account of the wait, and these lines cost one print
each.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time

__all__ = ["stage", "note"]

#: Set NDI_GENEPYRAMID_QUIET=1 to silence the launch narration.
_QUIET_ENV = "NDI_GENEPYRAMID_QUIET"


def _quiet() -> bool:
    return bool(os.environ.get(_QUIET_ENV, "").strip())


def note(text: str) -> None:
    """One launch line, no timing."""
    if not _quiet():
        print(f"[genepyramid] {text}", file=sys.stderr, flush=True)


@contextlib.contextmanager
def stage(label: str):
    """Time a step of the launch and report it when it finishes.

    The label is printed BEFORE the work, so a step that hangs is named
    on screen rather than leaving the user with the previous step's line
    and no idea which one is stuck.
    """
    if _quiet():
        yield
        return
    print(f"[genepyramid] {label} ...", file=sys.stderr, flush=True)
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        print(f"[genepyramid] {label}: {dt:.1f}s", file=sys.stderr, flush=True)
