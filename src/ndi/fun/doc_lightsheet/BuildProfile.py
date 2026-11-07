"""
ndi.fun.doc_lightsheet.BuildProfile

MATLAB equivalent: +ndi/+fun/+doc/+lightsheet/BuildProfile.m

Where a pyramid build spends its time: one row per super-block, appended as
CSV to a profile log, with summaries printed as the build goes.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

__all__ = ["ndi_fun_doc_lightsheet_BuildProfile", "BuildProfile"]

#: The row fields, in order: the profile CSV's columns (identical to MATLAB's).
FIELDS = (
    "when",
    "level",
    "superblock",
    "nSuperBlocks",
    "chunks",
    "workers",
    "mbRead",
    "mbChunks",
    "mbOut",
    "readWait",
    "assemble",
    "compress",
    "workerBusy",
    "upload",
    "urls",
    "stage",
    "send",
    "verify",
    "progress",
    "total",
)

_EPS = sys.float_info.epsilon  # MATLAB's eps


class ndi_fun_doc_lightsheet_BuildProfile:
    """Per-batch timings of a lightsheet pyramid build.

    MATLAB equivalent: ``ndi.fun.doc.lightsheet.BuildProfile(logFile,
    everySeconds)``

    The pyramid builder times every super-block (one read, one parallel
    compression of its chunks, one hand-off to the target) and :meth:`add`\\ s
    a row. Each row is appended to *logFile* as CSV (empty: no file), a
    summary is printed every *everySeconds* (default 600) and at the end of
    each level (:meth:`endLevel`), and :meth:`finish` prints one for the
    whole build.

    Rows are dicts with the keys :data:`FIELDS` (``when`` is filled in by
    :meth:`add`); times are seconds and ``mb*`` megabytes (``mbOut`` is the
    compressed size). The CSV columns are the same, in the same order, as
    MATLAB's, so a profile.csv from either language reads alike. A resumed
    build appends to an existing log without a second header.
    """

    FIELDS = FIELDS

    def __init__(self, logFile: str | os.PathLike = "", everySeconds: float = 600):
        self._logFile = os.fspath(logFile) if logFile else ""
        self._rows: list[dict[str, Any]] = self.emptyRows()
        self._everySeconds = float(everySeconds)
        self._lastPrint = time.monotonic()
        self._windowFirst = 0
        self._levelFirst = 0

    @property
    def logFile(self) -> str:
        """The CSV log every row is appended to ('' for none)."""
        return self._logFile

    @property
    def rows(self) -> list[dict[str, Any]]:
        """One dict per super-block recorded in this run."""
        return self._rows

    def add(self, r: Mapping[str, Any]) -> None:
        """Record one super-block (a mapping with the :data:`FIELDS` keys).

        ``when`` is set here. Like MATLAB's ``orderfields``, the row must
        carry exactly the other fields.
        """
        r = dict(r)
        r["when"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if set(r) != set(FIELDS):
            missing = sorted(set(FIELDS) - set(r))
            extra = sorted(set(r) - set(FIELDS))
            raise ValueError(
                f"A BuildProfile row needs exactly its fields; missing {missing}, extra {extra}."
            )
        r = {k: r[k] for k in FIELDS}
        self._rows.append(r)
        self._append(r)
        elapsed = time.monotonic() - self._lastPrint
        if elapsed >= self._everySeconds:
            print(
                f"[profile] {r['level']}, last {self._minutes(elapsed)}: "
                f"{self.summarize(self._rows[self._windowFirst:])}"
            )
            self._windowFirst = len(self._rows)
            self._lastPrint = time.monotonic()

    def endLevel(self, label: str) -> None:
        """Print the summary of the level just finished."""
        these = self._rows[self._levelFirst :]
        if these:
            print(f"[profile] {label}, whole level: {self.summarize(these)}")
        self._levelFirst = len(self._rows)
        self._windowFirst = self._levelFirst
        self._lastPrint = time.monotonic()

    def finish(self) -> None:
        """Print the summary of everything built in this run."""
        if self._rows:
            print(f"[profile] Whole build (this run): {self.summarize(self._rows)}")
            if self._logFile:
                print(f"[profile] Every batch is in {self._logFile}")

    @staticmethod
    def summarize(rows: Sequence[Mapping[str, Any]]) -> str:
        """One sentence on where *rows*' time went."""
        n = len(rows)
        if n == 0:
            return "no batches"

        def col(name: str) -> list[float]:
            return [float(r[name]) for r in rows]

        total = sum(col("total"))

        def pct(x: list[float]) -> float:
            return 100 * sum(x) / max(total, _EPS)

        readWait, assemble = col("readWait"), col("assemble")
        compress, upload, progress = col("compress"), col("upload"), col("progress")
        other = total - sum(readWait) - sum(assemble) - sum(compress) - sum(upload)
        other -= sum(progress)
        capacity = sum(c * w for c, w in zip(compress, col("workers")))
        busy = 100 * sum(col("workerBusy")) / max(capacity, _EPS)
        return (
            f"{n} batches: read-wait {pct(readWait):.0f}%, assemble {pct(assemble):.0f}%, "
            f"compress {pct(compress):.0f}% (workers {busy:.0f}% busy), "
            f"upload {pct(upload):.0f}% (URLs {pct(col('urls')):.0f}%, "
            f"staging+CRC {pct(col('stage')):.0f}%, "
            f"waiting for curl {pct(col('send')):.0f}%, "
            f"cloud check {pct(col('verify')):.0f}%), progress {pct(progress):.0f}%, "
            f"other {max(0, 100 * other / max(total, _EPS)):.0f}%. "
            f"{sum(col('mbChunks')) / max(total, _EPS):.1f} MB/s of chunks made, "
            f"{sum(col('mbOut')) / max(total, _EPS):.1f} MB/s compressed, "
            f"{sum(col('mbRead')) / max(total, _EPS):.1f} MB/s read."
        )

    @staticmethod
    def emptyRows() -> list[dict[str, Any]]:
        """No rows (MATLAB: a 0x0 struct with :data:`FIELDS`)."""
        return []

    @staticmethod
    def _minutes(seconds: float) -> str:
        return f"{seconds / 60:.0f} min"

    def _append(self, r: dict[str, Any]) -> None:
        if not self._logFile:
            return
        try:
            isNew = not os.path.isfile(self._logFile)
            with open(self._logFile, "a", newline="") as fh:
                if isNew:
                    fh.write(",".join(FIELDS) + "\n")
                vals = []
                for k in FIELDS:
                    v = r[k]
                    if isinstance(v, str):
                        vals.append('"' + v.replace('"', '""') + '"')
                    else:
                        vals.append(f"{v:.4g}")
                fh.write(",".join(vals) + "\n")
        except Exception:  # noqa: BLE001 - profiling never stops the build
            pass


#: The MATLAB name, for callers that mirror ``ndi.fun.doc.lightsheet.BuildProfile``.
BuildProfile = ndi_fun_doc_lightsheet_BuildProfile
