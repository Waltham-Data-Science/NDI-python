"""Say what the launch is doing, and how long each part took.

Opening a lightsheetZarr pyramid on a cloud-backed session spends most
of its wall clock building the lazy multiscale ladder (Python object
work over 100k+ chunk positions per level) and then fetching the first
cascade of chunk manifests and members. Without narration the whole
wait is opaque, and the launch looks stuck on whichever step blocked
first.

Two channels, on together by default:

* stderr lines under ``NDI_LIGHTSHEET_DEBUG`` (currently always on for
  the debugging pass), so a piped log carries the same record.
* A Qt launch window with a QProgressBar, so a viewer opened from
  NDI-matlab's ``LightsheetZarrManager`` (no terminal at all) still
  shows what is happening.

Mirrors ``ndi.gui.app.genepyramid.progress`` -- the two viewers share a
launch shape (lazy multiscale + cloud fetches) and the reporting rules
are the same.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time

__all__ = ["stage", "note", "cloudFetches", "humanBytes", "closeLaunchWindow"]

#: Set NDI_LIGHTSHEET_QUIET=1 to silence every progress channel.
_QUIET_ENV = "NDI_LIGHTSHEET_QUIET"

#: "gui", "text" or "off". Unset picks gui when Qt is available and a
#: window can be created, text when stderr is a terminal, off otherwise.
_MODE_ENV = "NDI_LIGHTSHEET_PROGRESS"

#: When set (truthy) the stderr channel prints on top of whatever
#: _mode() picks -- so a GUI launch still leaves a piped log record.
_DEBUG_ENV = "NDI_LIGHTSHEET_DEBUG"


def _quiet() -> bool:
    return bool(os.environ.get(_QUIET_ENV, "").strip())


def _debug() -> bool:
    return bool(os.environ.get(_DEBUG_ENV, "").strip())


def note(text: str) -> None:
    """One launch line to stderr, no timing.

    Prints when the GUI channel is off (text-mode or no display) OR
    under NDI_LIGHTSHEET_DEBUG. Silent under NDI_LIGHTSHEET_QUIET.
    """
    if _quiet():
        return
    if _mode() == "text" or _debug():
        print(f"[lightsheet] {text}", file=sys.stderr, flush=True)


@contextlib.contextmanager
def stage(label: str):
    """Time a step of the launch and report it when it finishes.

    Label is printed BEFORE the work, so a step that hangs is named on
    screen rather than leaving the user with the previous step's line
    and no idea which one is stuck.

    The stderr channel narrates under debug or text-mode; the GUI
    channel updates the launch window's step label. Both are on
    together whenever both apply.
    """
    if _quiet():
        yield
        return

    mode = _mode()
    if mode == "text" or _debug():
        print(f"[lightsheet] {label} ...", file=sys.stderr, flush=True)
    if mode == "gui":
        _guiStage(label)
    t0 = time.perf_counter()
    try:
        # Stages used to nest their own cloudFetches observer here,
        # which silently overrode a counter the caller had installed
        # around the whole viewer session. Any fetches during add_image
        # then went to the inner observer (silent on start/done) and
        # never reached the counter -- the "no tiles requested yet"
        # heartbeat kept firing while chunks were quietly downloading.
        # Callers that want byte progress can install their own outer
        # observer via ndi.cloud.filehandler.watchFetches.
        yield
    finally:
        dt = time.perf_counter() - t0
        if mode == "text" or _debug():
            print(f"[lightsheet] {label}: {dt:.1f}s", file=sys.stderr, flush=True)


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

    A directory-backed session fetches nothing and this costs one hook
    install; no output, no way for it to matter.

    A CLOUD session is the case this exists for. Chunk fetches on the
    first-frame cascade come through here via
    :func:`ndi.cloud.filehandler.watchFetches`. The lightsheet fetcher
    pool runs several concurrent fetches, so this tracks only the
    NEWEST file's bytes/percent -- interleaving a line each would
    scroll the launch away.
    """
    mode = _mode()
    if mode == "off" and not _debug():
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
        sys.stderr.write(f"\r[lightsheet] {label}: {body}{suffix}   ")
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
                    # Only from the launch thread. Touching a widget
                    # from a fetcher worker is a crash, not a wrong
                    # number.
                    if threading.get_ident() == launch_thread:
                        _guiBytes(done, total)
                elif mode == "text" or _debug():
                    render()

    try:
        with watchFetches(observer):
            yield
    finally:
        with lock:
            if state["shown"]:
                # Leave the cursor on a clean line, so the next stage
                # note does not land on top of half a progress bar.
                sys.stderr.write("\r" + " " * 78 + "\r")
                sys.stderr.flush()


# ------------------------------------------------------------------ gui

#: The launch window, once built. One per process.
_window = None
_window_failed = False


def _mode() -> str:
    """Which indicator to use: ``"gui"``, ``"text"`` or ``"off"``."""
    asked = os.environ.get(_MODE_ENV, "").strip().lower()
    if asked in ("gui", "text", "off"):
        return asked
    if _quiet():
        return "off"
    if _launchWindow() is not None:
        return "gui"
    return "text" if sys.stderr.isatty() else "off"


def _displayLikely() -> bool:
    """Whether building a QApplication is safe to attempt.

    THIS GUARD IS NOT OPTIONAL. Qt does not raise when it cannot reach
    a display: it prints "could not connect to display" and calls
    abort(). That kills the process, so try/except around
    QApplication() catches nothing -- the launch would die instead of
    falling back to text.

    macOS and Windows always have a window server. On X11/Wayland the
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

    Built BEFORE napari is imported: the wait this reports on starts
    before there is a viewer to host it. That means creating the
    QApplication ourselves, which napari then reuses.
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
            _window_failed = True
            return None
        if app is None:
            for attr in ("AA_EnableHighDpiScaling", "AA_UseHighDpiPixmaps"):
                with contextlib.suppress(AttributeError):
                    QApplication.setAttribute(getattr(Qt, attr), True)
            app = QApplication([])

        w = QWidget()
        w.setWindowTitle("Opening lightsheet pyramid")
        layout = QVBoxLayout(w)
        title = QLabel("Opening lightsheet pyramid")
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        step = QLabel("starting ...")
        bar = QProgressBar()
        bar.setRange(0, 0)  # busy until a byte count gives it a range
        layout.addWidget(title)
        layout.addWidget(step)
        layout.addWidget(bar)
        w.resize(460, 110)
        w.show()
        app.processEvents()

        _window = {"app": app, "widget": w, "step": step, "bar": bar}
    except Exception:  # noqa: BLE001 - no display, no binding, no window
        _window_failed = True
        _window = None
    return _window


def _guiStage(label: str) -> None:
    """Show the step about to run, and MAKE SURE IT IS PAINTED.

    setText queues a repaint; processEvents services what is queued
    NOW. Between them they can still leave the old text on screen,
    because the step that follows blocks the thread for as long as it
    takes and no event loop runs meanwhile. repaint() paints
    synchronously, before returning, so the new label is on the glass
    before the blocking work starts.
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
        win["widget"].repaint()


def closeLaunchWindow() -> None:
    """Take the launch window down. Safe to call when there never was one.

    Called once napari's viewer is built and about to take over: a
    progress window that outlives the thing it was reporting on is
    worse than none, because it makes a finished launch look stuck.

    Prints a confirmation line to stderr under any of the on-stderr
    modes: users have reported the launch dialog lingering, and a
    log line pinning the exact moment we asked it to close lets us
    tell "we closed it, Qt hasn't repainted yet" from "we never
    called close at all".
    """
    global _window
    win, _window = _window, None
    if win is None:
        return
    with contextlib.suppress(Exception):
        win["widget"].close()
        win["app"].processEvents()
    print(
        "[lightsheet] closeLaunchWindow: launch dialog close requested",
        file=sys.stderr,
        flush=True,
    )
