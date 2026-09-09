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
import threading
import time

__all__ = ["stage", "note", "cloudFetches", "humanBytes"]

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
        # Every stage gets the byte bar. On a directory-backed session
        # nothing is fetched and this costs one hook install; on a
        # cloud-backed one it is the difference between a label that sits
        # there for a minute and a line that moves.
        with cloudFetches(label):
            yield
    finally:
        dt = time.perf_counter() - t0
        print(f"[genepyramid] {label}: {dt:.1f}s", file=sys.stderr, flush=True)


def humanBytes(n: int) -> str:
    """A byte count at a glance. 26214400 is not a number anyone reads."""
    step = 1024.0
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < step or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= step
    return f"{value:.1f} GB"


@contextlib.contextmanager
def cloudFetches(label: str = "fetching"):
    """Draw a progress line for every cloud file fetched inside this block.

    A session opened from a local directory fetches nothing and this costs
    one hook install; there is no output and no reason to ask the caller
    which kind of session they have.

    A CLOUD session is the case this exists for. The cell table, the
    contour file and the gene list are each a whole download before the
    window can appear, and stage() alone prints a label and then nothing
    moves for however long that takes -- which is indistinguishable from a
    hang. This redraws one line in place with bytes and, when the server
    sent a Content-Length, a percentage.

    ONE LINE, AND ONLY FOR THE FILE BEING WAITED ON. Tiles are fetched
    from _TileFetcher threads once the viewer is up, several possibly at
    once; interleaving a line each would scroll the launch notes away. So
    the renderer tracks a count of files and shows the newest, and every
    write is under a lock because the callers are threads.
    """
    if _quiet() or not sys.stderr.isatty():
        # Not a terminal: a redrawn line becomes thousands of lines in a
        # log or a CI capture. The stage timings still say what happened.
        yield
        return

    try:
        from ....cloud.filehandler import watchFetches
    except Exception:  # noqa: BLE001 - reporting is never worth the launch
        yield
        return

    state = {"files": 0, "done": 0, "total": None, "shown": False}
    lock = threading.Lock()

    def render():
        n, done, total = state["files"], state["done"], state["total"]
        if total:
            pct = min(100.0, 100.0 * done / total)
            body = f"{humanBytes(done)} of {humanBytes(total)} ({pct:.0f}%)"
        else:
            body = humanBytes(done)
        suffix = f", file {n}" if n > 1 else ""
        sys.stderr.write(f"\r[genepyramid] {label}: {body}{suffix}   ")
        sys.stderr.flush()
        state["shown"] = True

    def observer(event, _uri, done, total):
        with lock:
            if event == "start":
                state["files"] += 1
                state["done"] = 0
                state["total"] = None
            elif event == "chunk":
                state["done"] = done
                state["total"] = total
                render()

    try:
        with watchFetches(observer):
            yield
    finally:
        with lock:
            if state["shown"]:
                # Leave the cursor on a clean line, so the next stage note
                # does not land on top of half a progress bar.
                sys.stderr.write("\r" + " " * 78 + "\r")
                sys.stderr.flush()
