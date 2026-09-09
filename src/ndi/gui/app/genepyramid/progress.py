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

__all__ = ["stage", "note", "cloudFetches", "humanBytes", "closeLaunchWindow"]

#: Set NDI_GENEPYRAMID_QUIET=1 to silence the launch narration.
_QUIET_ENV = "NDI_GENEPYRAMID_QUIET"

#: "gui", "text" or "off". Unset picks gui when a Qt binding loads and a
#: window can be created, text when stderr is a terminal, off otherwise.
_MODE_ENV = "NDI_GENEPYRAMID_PROGRESS"


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
    # The stderr narration stays on in every mode. It is the record of
    # where the time went, and it costs one print per step whether or not
    # anyone is watching a window.
    print(f"[genepyramid] {label} ...", file=sys.stderr, flush=True)
    if _mode() == "gui":
        _guiStage(label)
    t0 = time.perf_counter()
    try:
        # Every stage gets the byte reporting. On a directory-backed
        # session nothing is fetched and this costs one hook install; on a
        # cloud-backed one it is the difference between a label that sits
        # there for a minute and something that moves.
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
    mode = _mode()
    if mode == "off":
        yield
        return

    try:
        from ....cloud.filehandler import watchFetches
    except Exception:  # noqa: BLE001 - reporting is never worth the launch
        yield
        return

    state = {"files": 0, "done": 0, "total": None, "shown": False}
    lock = threading.Lock()
    launch_thread = threading.get_ident()

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
                if mode == "gui":
                    # Only from the launch thread. Touching a widget from
                    # a _TileFetcher worker is a crash, not a wrong number.
                    if threading.get_ident() == launch_thread:
                        _guiBytes(done, total)
                else:
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


# ------------------------------------------------------------------ gui

#: The launch window, once built. One per process: the launch is one
#: sequence on one thread, and a second window would be a second claim
#: about what is happening.
_window = None
_window_failed = False


def _mode() -> str:
    """Which indicator to use: ``"gui"``, ``"text"`` or ``"off"``."""
    asked = os.environ.get(_MODE_ENV, "").strip().lower()
    if asked in ("gui", "text", "off"):
        return asked
    if _quiet():
        return "off"
    # GUI first: the viewer is normally started from NDI-matlab's View
    # button, where there is no terminal at all and a stderr bar is
    # written to nobody. Falling back to text keeps a terminal launch
    # informative.
    if _launchWindow() is not None:
        return "gui"
    return "text" if sys.stderr.isatty() else "off"


def _displayLikely() -> bool:
    """Whether building a QApplication is safe to attempt.

    THIS GUARD IS NOT OPTIONAL. Qt does not raise when it cannot reach a
    display: it prints "could not connect to display" and calls abort().
    That kills the process, so try/except around QApplication() catches
    nothing -- the launch would die instead of falling back to text, which
    is a worse failure than having no progress window at all.

    macOS and Windows always have a window server, and they are where the
    viewer is started from NDI-matlab's View button. On X11/Wayland the
    environment says: DISPLAY or WAYLAND_DISPLAY, or an explicit
    QT_QPA_PLATFORM (offscreen included, which is how this is tested).
    """
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("QT_QPA_PLATFORM")
    )


def _launchWindow():
    """The launch window, built on first use, or None if Qt will not.

    Built BEFORE napari is imported, because the wait this reports on
    starts before there is a viewer to host it -- opening the session,
    the cell table and the contour file are all spent before napari is
    even imported. That means creating the QApplication ourselves, which
    napari then reuses.

    The high-DPI attributes are set here for that reason: napari sets
    them before creating its own app, and on a Retina display an app
    created without them renders at the wrong scale. Setting them is
    harmless where they are already the default (Qt6 deprecates both).
    """
    global _window, _window_failed
    if _window is not None or _window_failed:
        return _window
    try:
        from qtpy.QtCore import Qt
        from qtpy.QtWidgets import (
            QApplication,
            QLabel,
            QProgressBar,
            QVBoxLayout,
            QWidget,
        )

        app = QApplication.instance()
        if app is None and not _displayLikely():
            # No app to borrow and no display to make one against. See
            # _displayLikely: attempting it anyway aborts the process.
            _window_failed = True
            return None
        if app is None:
            for attr in ("AA_EnableHighDpiScaling", "AA_UseHighDpiPixmaps"):
                with contextlib.suppress(AttributeError):
                    QApplication.setAttribute(getattr(Qt, attr), True)
            app = QApplication([])

        w = QWidget()
        w.setWindowTitle("Opening pyramid")
        layout = QVBoxLayout(w)
        title = QLabel("Opening pyramid")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        step = QLabel("starting ...")
        bar = QProgressBar()
        bar.setRange(0, 0)  # busy until a byte count gives it a range
        layout.addWidget(title)
        layout.addWidget(step)
        layout.addWidget(bar)
        w.resize(420, 110)
        w.show()
        app.processEvents()

        _window = {"app": app, "widget": w, "step": step, "bar": bar}
    except Exception:  # noqa: BLE001 - no display, no binding, no window
        _window_failed = True
        _window = None
    return _window


def _guiStage(label: str) -> None:
    """Show the step that is about to run, and MAKE SURE IT IS PAINTED.

    setText queues a repaint; processEvents services what is queued NOW.
    Between them they can still leave the old text on screen, because the
    step that follows blocks the thread for as long as it takes and no
    event loop runs meanwhile -- so any paint the window needs after that
    point (it gets exposed, the compositor asks again, the OS marks the
    app unresponsive) is never serviced.

    The effect is a window frozen on whichever label was current when the
    FIRST slow step began, which made a launch that was working look
    stuck on "importing napari" for minutes while the label underneath
    had long since moved on.

    repaint() paints synchronously, before returning, so the new label is
    on the glass before the blocking work starts. It does not animate --
    nothing can, without an event loop -- but each step is legible while
    it runs instead of one step being legible for all of them.
    """
    win = _launchWindow()
    if win is None:
        return
    with contextlib.suppress(Exception):
        win["step"].setText(label)
        win["bar"].setRange(0, 0)  # unknown length again
        win["app"].processEvents()
        win["widget"].repaint()


def _guiBytes(done: int, total) -> None:
    win = _launchWindow()
    if win is None:
        return
    with contextlib.suppress(Exception):
        if total:
            win["bar"].setRange(0, 100)
            win["bar"].setValue(int(100 * done / total))
            win["bar"].setFormat(f"{humanBytes(done)} of {humanBytes(total)} (%p%)")
        else:
            win["bar"].setRange(0, 0)
            win["bar"].setFormat(humanBytes(done))
        win["app"].processEvents()
        # Synchronous, for the same reason as _guiStage: a byte count that
        # only lands when the transfer finishes has reported nothing.
        win["widget"].repaint()


def closeLaunchWindow() -> None:
    """Take the launch window down. Safe to call when there never was one.

    Called once the viewer is built and about to be handed to the user:
    a progress window that outlives the thing it was reporting on is
    worse than none, because it makes a finished launch look stuck.
    """
    global _window
    win, _window = _window, None
    if win is None:
        return
    with contextlib.suppress(Exception):
        win["widget"].close()
        win["app"].processEvents()
