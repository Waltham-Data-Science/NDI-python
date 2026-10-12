"""Report a problem from inside a viewer.

A beta viewer's problems mostly go unreported: asking a user to find a
log, copy versions and write an email is too much. This module turns
that into one dialog -- the user says what they were doing, the viewer
attaches what it knows, and the report goes to NDI Cloud through
:func:`ndi.cloud.api.feedback.submitFeedback` (the user is already
signed in for the tiles). Save-to-file and Copy cover a user who is
not signed in, or offline.

Pieces, each usable on its own:

* :class:`LogBuffer` -- keeps the last lines written to stderr (and to
  the ``logging`` root) so a report can carry them without the user
  ever having seen a terminal.
* :func:`scrub` -- strips credentials before anything leaves the
  machine. Viewer logs DO carry them: signed S3 URLs embed a signature
  and session token, and auth lines can carry a bearer token.
* :func:`buildReport` -- the ``submitFeedback`` keyword arguments,
  scrubbed and cut to the server's size limits.
* :func:`sendReport` / :func:`saveReport` -- deliver it.
* :class:`FeedbackDialog` -- the Qt dialog (imported lazily).

The payload field names are a contract with NDI-matlab and the server
(Waltham-Data-Science/ndi-cloud-node#158).
"""

from __future__ import annotations

import collections
import json
import logging
import os
import platform
import re
import sys
import threading
from collections.abc import Callable
from typing import Any

__all__ = [
    "LogBuffer",
    "installLogBuffer",
    "scrub",
    "buildReport",
    "sendReport",
    "saveReport",
    "describeSendError",
    "FeedbackDialog",
    "openFeedbackDialog",
]

#: Server limits (characters / JSON bytes). Reports are cut to fit, not
#: refused: a truncated log is worth more than no report.
MAX_DESCRIPTION = 20_000
MAX_LOG = 500_000
MAX_TRACEBACK = 50_000
MAX_ENVIRONMENT_JSON = 20_000
MAX_STATE_JSON = 200_000

#: Lines the log buffer keeps. Generous: a stuck-view report wants the
#: minutes before the user gave up, and the log is cut to MAX_LOG anyway.
LOG_LINES = 5_000

_REDACTED = "[REDACTED]"

# Order matters: whole signed-URL query strings first, then the bits
# that can appear on their own.
_SCRUB_PATTERNS: list[tuple[re.Pattern, str]] = [
    # AWS signed-URL credentials (query params, any case).
    (
        re.compile(
            r"(?i)\b(X-Amz-(?:Signature|Credential|Security-Token)|Signature|"
            r"AWSAccessKeyId|x-amz-security-token)=[^&\s\"'<>]+"
        ),
        rf"\1={_REDACTED}",
    ),
    # Authorization headers / bearer tokens.
    (re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]+"), rf"\1 {_REDACTED}"),
    # JWTs anywhere (header.payload.signature, base64url).
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]+"), _REDACTED),
    # key=value / "key": "value" for anything named like a secret.
    (
        re.compile(
            r"(?i)([\"']?\b[\w-]*(?:token|password|passwd|secret|api[_-]?key)[\w-]*[\"']?"
            r"\s*[:=]\s*[\"']?)([^\s\"',&}]+)"
        ),
        rf"\1{_REDACTED}",
    ),
]


def scrub(text: str) -> str:
    """Remove credentials from TEXT. Safe on any string."""
    if not text:
        return text
    for pattern, repl in _SCRUB_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _scrubValue(value: Any) -> Any:
    """Scrub every string inside a JSON-like value; drop secret-named keys."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key = str(k)
            if re.search(r"(?i)token|password|passwd|secret|api[_-]?key", key):
                out[key] = _REDACTED
            else:
                out[key] = _scrubValue(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrubValue(v) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return scrub(str(value))


# ------------------------------------------------------------------ log buffer


class LogBuffer:
    """The last :data:`LOG_LINES` lines written to stderr and to logging.

    Installed as a tee in front of ``sys.stderr``: everything still
    reaches the real stream, and a copy of each complete line lands in
    a ring buffer. A ``\\r``-redrawn progress line keeps only its last
    state. Thread-safe; fetcher threads print too.
    """

    def __init__(self, max_lines: int = LOG_LINES):
        self._lines: collections.deque[str] = collections.deque(maxlen=max_lines)
        self._partial = ""
        self._lock = threading.Lock()

    def feed(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            data = self._partial + text
            parts = data.split("\n")
            self._partial = parts.pop()
            for line in parts:
                line = line.rsplit("\r", 1)[-1]
                if line.strip():
                    self._lines.append(line)
            # A long run of \r redraws never ends in \n; keep only the
            # current state so it cannot grow without bound.
            self._partial = self._partial.rsplit("\r", 1)[-1][-10_000:]

    def text(self) -> str:
        with self._lock:
            lines = list(self._lines)
            if self._partial.strip():
                lines.append(self._partial)
        return "\n".join(lines)


class _Tee:
    """sys.stderr stand-in: write through, and copy into a LogBuffer."""

    def __init__(self, stream, buffer: LogBuffer):
        self._stream = stream
        self._buffer = buffer

    def write(self, text):
        try:
            self._buffer.feed(text)
        except Exception:  # noqa: BLE001 - the log must never break printing
            pass
        return self._stream.write(text)

    def flush(self):
        return self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


class _BufferHandler(logging.Handler):
    def __init__(self, buffer: LogBuffer):
        super().__init__(level=logging.INFO)
        self._buffer = buffer
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record):
        try:
            self._buffer.feed(self.format(record) + "\n")
        except Exception:  # noqa: BLE001
            pass


_installed: LogBuffer | None = None


def installLogBuffer() -> LogBuffer:
    """Start buffering stderr and logging for reports. Idempotent.

    Logging records reach the buffer through their own handler, since
    a logging StreamHandler holds the stderr it was built with and would
    bypass the tee. A record that ALSO prints to stderr after the tee is
    installed can appear twice; harmless in a diagnostic log.
    """
    global _installed
    if _installed is not None:
        return _installed
    buf = LogBuffer()
    if not isinstance(sys.stderr, _Tee):
        sys.stderr = _Tee(sys.stderr, buf)
    logging.getLogger().addHandler(_BufferHandler(buf))
    _installed = buf
    return buf


# ------------------------------------------------------------------ report


def _versions() -> dict[str, Any]:
    env: dict[str, Any] = {
        "os": f"{platform.system()} {platform.release()}",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
    }
    try:
        import ndi

        env["ndi"] = str(getattr(ndi, "__version__", "?"))
    except Exception:  # noqa: BLE001
        pass
    for mod in ("napari", "numpy", "dask", "qtpy"):
        m = sys.modules.get(mod)
        if m is not None:
            env[mod] = str(getattr(m, "__version__", "?"))
    try:
        import qtpy

        env["qtApi"] = str(getattr(qtpy, "API_NAME", "?"))
        env["qt"] = str(getattr(qtpy, "QT_VERSION", "?"))
    except Exception:  # noqa: BLE001
        pass
    return env


def _envFlags(prefixes: tuple[str, ...]) -> dict[str, str]:
    return {k: v for k, v in sorted(os.environ.items()) if k.startswith(prefixes)}


def _capJson(value: dict, limit: int, what: str) -> dict:
    """VALUE if its JSON fits LIMIT bytes, else a note saying it was cut."""
    try:
        raw = json.dumps(value, default=str)
    except Exception as exc:  # noqa: BLE001
        return {"_note": f"{what} could not be serialised ({exc})"}
    if len(raw.encode("utf-8")) <= limit:
        return json.loads(raw)
    return {
        "_note": f"{what} was {len(raw):,} bytes, over the {limit:,} limit; truncated",
        "_head": raw[: limit // 2],
    }


def _tail(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    marker = f"[... {len(text) - limit:,} earlier characters cut ...]\n"
    return marker + text[-(limit - len(marker)) :]


def buildReport(
    app: str,
    category: str,
    description: str,
    *,
    appVersion: str | None = None,
    datasetId: str | None = None,
    documentId: str | None = None,
    state: dict | None = None,
    log: str | None = None,
    traceback: str | None = None,
    envPrefixes: tuple[str, ...] = ("NDI_",),
) -> dict[str, Any]:
    """Keyword arguments for ``submitFeedback``, scrubbed and size-capped.

    ``environment`` is filled in here (OS, Python, NDI and GUI library
    versions, and the ``NDI_*`` environment flags -- with any secret-
    named ones redacted). Everything the user did not type is scrubbed
    of credentials; the description is the user's own words and is
    sent as typed (cut to the limit).
    """
    if appVersion is None:
        appVersion = f"NDI-python {_versions().get('ndi', '?')}"
    environment = _versions()
    environment["flags"] = _envFlags(envPrefixes)
    report: dict[str, Any] = {
        "app": app,
        "category": category,
        "description": (description or "")[:MAX_DESCRIPTION],
        "appVersion": appVersion,
        "environment": _capJson(_scrubValue(environment), MAX_ENVIRONMENT_JSON, "environment"),
    }
    if datasetId:
        report["datasetId"] = str(datasetId)
    if documentId:
        report["documentId"] = str(documentId)
    if state is not None:
        report["state"] = _capJson(_scrubValue(state), MAX_STATE_JSON, "state")
    if log:
        report["log"] = _tail(scrub(log), MAX_LOG)
    if traceback:
        report["traceback"] = _tail(scrub(traceback), MAX_TRACEBACK)
    return report


def sendReport(report: dict[str, Any], *, client=None) -> str:
    """Submit REPORT; return the stored report's id. Raises on failure."""
    from ndi.cloud.api.feedback import submitFeedback

    kwargs = dict(report)
    if client is not None:
        kwargs["client"] = client
    b, feedback_id, _status, _url = submitFeedback(**kwargs)
    return str(feedback_id)


def describeSendError(exc: BaseException) -> str:
    """One sentence a user can act on, for a failed send."""
    try:
        from ndi.cloud.exceptions import CloudAPIError, CloudAuthError
    except Exception:  # noqa: BLE001
        CloudAPIError = CloudAuthError = ()  # type: ignore[assignment]
    if CloudAuthError and isinstance(exc, CloudAuthError):
        return (
            "Not signed in to NDI Cloud. Sign in, then send again -- or save the report to a file."
        )
    status = getattr(exc, "status_code", None)
    if CloudAPIError and isinstance(exc, CloudAPIError) and status is not None:
        if status == 429:
            return "Too many reports this hour. Save it to a file and send it later."
        if status == 413:
            return "The report is too large for the server. Save it to a file instead."
        if status == 404:
            return "This NDI Cloud server does not accept reports yet. Save it to a file instead."
        return f"NDI Cloud refused the report (HTTP {status}). Save it to a file instead."
    return f"Could not send the report ({type(exc).__name__}: {exc}). Save it to a file instead."


def saveReport(report: dict[str, Any], path: str) -> None:
    """Write REPORT as JSON to PATH (schema as sent to the server)."""
    from ndi.cloud.api.feedback import FEEDBACK_SCHEMA_VERSION

    body = {"schemaVersion": FEEDBACK_SCHEMA_VERSION, **report}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2, default=str)


# ------------------------------------------------------------------ dialog


def FeedbackDialog(  # noqa: N802 - a class factory; Qt is imported lazily
    parent=None,
    *,
    app: str,
    collect: Callable[[], dict[str, Any]],
    title: str = "Report a problem",
    send: Callable[[dict[str, Any]], str] = sendReport,
):
    """Build the report dialog. COLLECT returns the non-text fields.

    COLLECT is called when the dialog opens (and again on Send/Save so
    the attached state is current) and returns ``buildReport`` keyword
    arguments other than app/category/description: ``state``, ``log``,
    ``datasetId``, ``documentId``, ``traceback``, ...
    """
    from qtpy.QtCore import Qt, QTimer
    from qtpy.QtWidgets import (
        QApplication,
        QComboBox,
        QDialog,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QPlainTextEdit,
        QPushButton,
        QToolButton,
        QVBoxLayout,
    )

    class _Dialog(QDialog):
        CATEGORIES = [("Something is broken", "bug"), ("Slow", "performance"), ("Other", "other")]

        def __init__(self):
            super().__init__(parent)
            self.setWindowTitle(title)
            self.resize(560, 480)
            self.feedbackID: str | None = None
            self._future = None

            lay = QVBoxLayout(self)
            intro = QLabel(
                "What were you doing, and what did you see? The viewer attaches "
                "its own diagnostics (versions, what it was loading, recent log "
                "lines) with sign-in tokens and signed links removed."
            )
            intro.setWordWrap(True)
            lay.addWidget(intro)

            row = QHBoxLayout()
            row.addWidget(QLabel("Kind of problem:"))
            self.category = QComboBox()
            for label, value in self.CATEGORIES:
                self.category.addItem(label, value)
            row.addWidget(self.category, 1)
            lay.addLayout(row)

            self.description = QPlainTextEdit()
            self.description.setPlaceholderText(
                "e.g. I zoomed into the cortex at Z 1921 and the view stayed blurry "
                "for over a minute."
            )
            lay.addWidget(self.description, 2)

            self.toggle = QToolButton()
            self.toggle.setText("Show what will be sent")
            self.toggle.setCheckable(True)
            self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self.toggle.setArrowType(Qt.RightArrow)
            lay.addWidget(self.toggle, 0, Qt.AlignLeft)
            self.preview = QPlainTextEdit()
            self.preview.setReadOnly(True)
            self.preview.hide()
            lay.addWidget(self.preview, 3)
            self.toggle.toggled.connect(self._togglePreview)

            self.status = QLabel("")
            self.status.setWordWrap(True)
            self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lay.addWidget(self.status)

            buttons = QHBoxLayout()
            self.saveButton = QPushButton("Save to file...")
            self.copyButton = QPushButton("Copy")
            buttons.addWidget(self.saveButton)
            buttons.addWidget(self.copyButton)
            buttons.addStretch(1)
            self.cancelButton = QPushButton("Close")
            self.sendButton = QPushButton("Send")
            self.sendButton.setDefault(True)
            buttons.addWidget(self.cancelButton)
            buttons.addWidget(self.sendButton)
            lay.addLayout(buttons)

            self.description.textChanged.connect(self._sync)
            self.sendButton.clicked.connect(self._send)
            self.saveButton.clicked.connect(self._save)
            self.copyButton.clicked.connect(self._copy)
            self.cancelButton.clicked.connect(self.reject)

            self._poll = QTimer(self)
            self._poll.setInterval(100)
            self._poll.timeout.connect(self._checkSend)
            self._sync()

        # -- report
        def report(self) -> dict[str, Any]:
            try:
                extra = dict(collect() or {})
            except Exception as exc:  # noqa: BLE001 - a broken probe is itself a finding
                extra = {"state": {"_collectError": f"{type(exc).__name__}: {exc}"}}
            return buildReport(
                app,
                self.category.currentData(),
                self.description.toPlainText().strip() or "(no description)",
                **extra,
            )

        def _togglePreview(self, on):
            self.toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
            self.toggle.setText("Hide what will be sent" if on else "Show what will be sent")
            if on:
                self.preview.setPlainText(json.dumps(self.report(), indent=2, default=str))
            self.preview.setVisible(on)

        def _sync(self):
            has_text = bool(self.description.toPlainText().strip())
            busy = self._future is not None
            self.sendButton.setEnabled(has_text and not busy and self.feedbackID is None)

        # -- deliver
        def _send(self):
            from concurrent.futures import ThreadPoolExecutor

            rep = self.report()
            self.status.setText("Sending ...")
            pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ndi-feedback")
            self._future = pool.submit(send, rep)
            pool.shutdown(wait=False)
            self._sync()
            self._poll.start()

        def _checkSend(self):
            fut = self._future
            if fut is None or not fut.done():
                return
            self._poll.stop()
            self._future = None
            exc = fut.exception()
            if exc is None:
                self.feedbackID = fut.result()
                self.status.setText(f"Sent -- thank you. Report id: {self.feedbackID}")
                self.cancelButton.setText("Done")
            else:
                self.status.setText(describeSendError(exc))
            self._sync()

        def _save(self):
            path, _ = QFileDialog.getSaveFileName(
                self, "Save problem report", "ndi-problem-report.json", "JSON (*.json)"
            )
            if not path:
                return
            try:
                saveReport(self.report(), path)
                self.status.setText(f"Saved to {path}")
            except Exception as exc:  # noqa: BLE001
                self.status.setText(f"Could not save ({exc})")

        def _copy(self):
            QApplication.clipboard().setText(json.dumps(self.report(), indent=2, default=str))
            self.status.setText("Report copied to the clipboard.")

    return _Dialog()


def openFeedbackDialog(parent=None, **kwargs):
    """Build and show a :func:`FeedbackDialog` (non-modal); return it."""
    dlg = FeedbackDialog(parent, **kwargs)
    dlg.show()
    dlg.raise_()
    return dlg
