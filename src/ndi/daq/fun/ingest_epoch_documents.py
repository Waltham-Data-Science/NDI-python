"""ndi.daq.fun.ingest_epoch_documents - build the ingested-data documents for a set of epochs.

MATLAB counterpart: ``+ndi/+daq/+fun/ingestEpochDocuments.m``

This is the per-epoch part of :meth:`ndi.daq.system.ndi_daq_system.ingest`:
each epoch's reader and metadata-reader ``ingest_epochfiles`` documents. No
database is touched here, so the epochs can be computed on worker processes
while the caller keeps every database write serial.

WHY READERS ARE DETACHED FROM THEIR SESSION FOR THE WORKERS
MATLAB's readers are value objects that hold no session, so a parfor copies
them to the workers as they are. The Python readers keep a ``_session``
reference (used only on the ingested-READ paths), and a session -- with its
open SQLite database -- cannot and must not be shipped to another process.
Each worker therefore gets a shallow copy of each reader with ``_session``
cleared; ``ingest_epochfiles`` never uses it.
"""

from __future__ import annotations

import copy
import functools
import multiprocessing
import pickle
import warnings
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from typing import Any

from pydantic import ConfigDict, validate_call

__all__ = ["ingestEpochDocuments", "ingest_epoch_documents"]


@validate_call(config=ConfigDict(arbitrary_types_allowed=True))
def ingestEpochDocuments(  # noqa: N802 (MATLAB mirror)
    daqreader: Any,
    daqmetadatareaders: list[Any],
    epochFiles: list[list[str]],
    epochIds: list[str],
    ProgressFcn: Callable[[float, int], Any] | None = None,
    NumberOfWorkers: int | None = None,
) -> tuple[list[list[Any]], bool]:
    """Build the ingested-data documents for a set of epochs.

    [DOCSPEREPOCH, USEDPARALLEL] = ndi.daq.fun.ingestEpochDocuments(DAQREADER, ...
        DAQMETADATAREADERS, EPOCHFILES, EPOCHIDS, ...)

    Runs DAQREADER.ingest_epochfiles and each DAQMETADATAREADERS[j].ingest_epochfiles
    for every epoch described by EPOCHFILES[k] (a list of file names) and
    EPOCHIDS[k] (the epoch id).

    DOCSPEREPOCH[k] is the list of ndi_document objects created for epoch k, in
    the same order as a serial ingest produces them (the daqreader document
    followed by one document per metadata reader).

    No database is touched here: the documents are NOT added to any database,
    so the caller remains responsible for serializing all database writes.

    Whether the epochs are computed on worker processes follows NDI's parallel
    preferences, through ndi.fun.parallelWorkers. Results do not depend on the
    number of workers.

    Args:
        daqreader: The ndi.daq.reader whose ingest_epochfiles makes the main
            document for each epoch.
        daqmetadatareaders: The ndi.daq.metadatareader objects to run per epoch.
        epochFiles: One list of file names per epoch.
        epochIds: One epoch id per epoch.
        ProgressFcn: Called as ``ProgressFcn(numDone, numTotal)`` in the calling
            process as epochs progress. numDone counts epochs and is fractional
            while an epoch is underway: readers whose ingest_epochfiles is
            ndi_daq_reader_mfdaq's report each segment they write. It is called
            only when numDone changes, so each whole number is reported once.
        NumberOfWorkers: Overrides the preferences for this call (passed to
            ndi.fun.parallelWorkers); 0 forces serial.

    Returns:
        ``(docsPerEpoch, usedParallel)``; usedParallel is True if the epochs
        were actually computed on worker processes.

    Python-specific Notes:
        Workers are ``concurrent.futures.ProcessPoolExecutor`` processes started
        with the ``spawn`` method -- fresh interpreters, like MATLAB's pool
        workers -- and live only for this call. Readers are sent with their
        ``_session`` cleared (see the module docstring). A reader that cannot
        be pickled falls back to serial with a warning rather than failing.
        On workers, a reader whose ingest_epochfiles is ndi_daq_reader_mfdaq's
        is ingested one segment per task (MATLAB's ``parfeval`` scheduler):
        every epoch is planned in the calling process, the segments of all
        epochs (and each epoch's metadata readers) are handed to the workers
        as they free up, and the files are attached in plan order afterwards.
        Progress is reported as each task finishes, weighted by segment size,
        so ProgressFcn may see epochs out of order, but the returned list is
        always in epoch order. The pool is used even for a single epoch.
    """
    num_epochs = len(epochFiles)
    if len(epochIds) != num_epochs:
        raise ValueError("EPOCHFILES and EPOCHIDS must have the same number of entries.")

    docs_per_epoch: list[list[Any]] = [[] for _ in range(num_epochs)]
    # per-epoch fractions done
    frac = [0.0] * num_epochs

    def update_progress(k: int, fraction: float) -> None:
        # Fractions only move forward, and ProgressFcn is called only when the
        # total changes, so a reader's own final report and the epoch's
        # completion do not count the epoch twice.
        new_fraction = max(frac[k], min(max(float(fraction), 0.0), 1.0))
        if new_fraction == frac[k]:
            return
        frac[k] = new_fraction
        if ProgressFcn is not None:
            try:
                ProgressFcn(sum(frac), num_epochs)
            except Exception as exc:  # noqa: BLE001 - progress must never break an ingest
                warnings.warn(f"Progress reporting failed: {exc}", stacklevel=3)

    # readers using ndi_daq_reader_mfdaq's ingest_epochfiles take a ProgressFcn
    # and can be ingested segment by segment; any other reader works (and
    # reports) per epoch
    plans_segments = _reader_plans_segments(daqreader)

    number_of_workers = 0
    if num_epochs > 0:
        number_of_workers = _resolve_workers(NumberOfWorkers)

    payload = None
    if number_of_workers > 0:
        payload = _detached_readers(daqreader, daqmetadatareaders)
        if payload is None:
            number_of_workers = 0

    if number_of_workers > 0:
        reader, mreaders = payload
        docs_per_epoch = _ingest_on_pool(
            daqreader,
            reader,
            mreaders,
            epochFiles,
            epochIds,
            number_of_workers,
            plans_segments,
            update_progress,
        )
        return docs_per_epoch, True

    for k, (ef, eid) in enumerate(zip(epochFiles, epochIds)):
        epoch_progress = None
        if plans_segments and ProgressFcn is not None:
            epoch_progress = functools.partial(update_progress, k)
        docs_per_epoch[k] = _ingestOneEpoch(
            daqreader, daqmetadatareaders, ef, eid, epoch_progress=epoch_progress
        )
        update_progress(k, 1)
    return docs_per_epoch, False


#: Snake-case alias for MATLAB's name; one function under two names.
ingest_epoch_documents = ingestEpochDocuments


def _ingest_on_pool(
    daqreader: Any,
    reader: Any,
    mreaders: list[Any],
    epoch_files: list[list[str]],
    epoch_ids: list[str],
    number_of_workers: int,
    plans_segments: bool,
    update_progress: Callable[[int, float], None],
) -> list[list[Any]]:
    """Ingest the epochs on worker processes, one segment per task.

    MATLAB counterpart: ``ingestOnPool``. Every epoch is planned here
    (ndi_daq_reader_mfdaq.ingest_epochfiles_plan reads only file headers and
    writes the channel list); each planned segment, and each epoch's
    metadata readers, is a task. Readers that do not plan segments run one
    task per epoch. Tasks are handed out as workers free up, so the pool stays
    busy however unequal the epochs are, and the segment files are attached
    in plan order afterwards, so the documents match a serial ingest.
    """
    from ..mfdaq import ndi_daq_reader_mfdaq

    num_epochs = len(epoch_files)
    epoch_docs: list[Any] = [None] * num_epochs
    plans: list[list[dict[str, Any]]] = [[] for _ in range(num_epochs)]
    segment_files: list[list[Any]] = [[] for _ in range(num_epochs)]
    meta_docs: list[list[Any]] = [[] for _ in range(num_epochs)]
    docs_per_epoch: list[list[Any]] = [[] for _ in range(num_epochs)]

    # (epoch, kind, index into the plan, weight)
    tasks: list[tuple[int, str, int, float]] = []
    for k in range(num_epochs):
        if plans_segments:
            epoch_docs[k], plans[k] = daqreader.ingest_epochfiles_plan(epoch_files[k], epoch_ids[k])
            segment_files[k] = [None] * len(plans[k])
            tasks.extend((k, "segment", t, e["weight"]) for t, e in enumerate(plans[k]))
            if mreaders:
                tasks.append((k, "metadata", 0, 0.0))
        else:
            tasks.append((k, "epoch", 0, 1.0))
    remaining = [0] * num_epochs
    for k, *_ in tasks:
        remaining[k] += 1
    weight_done = [0.0] * num_epochs

    ctx = multiprocessing.get_context("spawn")
    executor = ProcessPoolExecutor(max_workers=number_of_workers, mp_context=ctx)
    try:
        futures = {}
        for index, (k, kind, t, _) in enumerate(tasks):
            entry = plans[k][t] if kind == "segment" else None
            future = executor.submit(
                _run_task,
                reader,
                mreaders if kind != "segment" else [],
                epoch_files[k],
                epoch_ids[k],
                kind,
                entry,
            )
            futures[future] = index
        pending = set(futures)
        while pending:
            finished, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                k, kind, t, weight = tasks[futures[future]]
                out = future.result()
                if kind == "segment":
                    segment_files[k][t] = out
                elif kind == "metadata":
                    meta_docs[k] = out
                else:
                    docs_per_epoch[k] = out
                remaining[k] -= 1
                weight_done[k] += weight
                update_progress(k, 1 if remaining[k] == 0 else min(weight_done[k], 0.999))
    except BaseException:
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    executor.shutdown(wait=True)
    for k in range(num_epochs):
        update_progress(k, 1)  # e.g., an epoch with nothing to write

    if plans_segments:
        for k in range(num_epochs):
            d = ndi_daq_reader_mfdaq.ingest_attach_segments(
                epoch_docs[k], plans[k], segment_files[k]
            )
            docs_per_epoch[k] = [d, *meta_docs[k]]
    return docs_per_epoch


def _run_task(
    daqreader: Any,
    daqmetadatareaders: list[Any],
    ef: list[str],
    epoch_id: str,
    kind: str,
    plan_entry: dict[str, Any] | None,
) -> Any:
    """One worker task: a segment, an epoch's metadata, or a whole epoch."""
    if kind == "segment":
        return daqreader.ingest_segment(ef, plan_entry)
    if kind == "metadata":
        return _metadata_docs(daqmetadatareaders, ef, epoch_id)
    return _ingestOneEpoch(daqreader, daqmetadatareaders, ef, epoch_id)


def _metadata_docs(daqmetadatareaders: list[Any], ef: list[str], epoch_id: str) -> list[Any]:
    """The metadata readers' documents for one epoch."""
    docs: list[Any] = []
    for mreader in daqmetadatareaders:
        new_d = mreader.ingest_epochfiles(ef, epoch_id)
        docs.extend(new_d if isinstance(new_d, list) else [new_d])
    return docs


def _ingestOneEpoch(  # noqa: N802 (mirrors MATLAB's local function)
    daqreader: Any,
    daqmetadatareaders: list[Any],
    ef: list[str],
    epoch_id: str,
    epoch_progress: Callable[[float], Any] | None = None,
) -> list[Any]:
    """Create the documents for a single epoch (no database access)."""
    docs: list[Any] = []
    if daqreader is not None:
        if epoch_progress is None:
            new_d = daqreader.ingest_epochfiles(ef, epoch_id)
        else:
            new_d = daqreader.ingest_epochfiles(ef, epoch_id, ProgressFcn=epoch_progress)
        docs.extend(new_d if isinstance(new_d, list) else [new_d])
    docs.extend(_metadata_docs(daqmetadatareaders, ef, epoch_id))
    return docs


def _reader_plans_segments(daqreader: Any) -> bool:
    """Does DAQREADER use ndi_daq_reader_mfdaq's ingest_epochfiles?

    MATLAB counterpart: ``readerPlansSegments``. Such a reader takes a
    ProgressFcn and can be ingested segment by segment
    (ingest_epochfiles_plan / ingest_segment). A subclass that overrides
    ingest_epochfiles keeps its own signature and is called once per epoch,
    without one.
    """
    if daqreader is None:
        return False
    from ..mfdaq import ndi_daq_reader_mfdaq

    method = getattr(type(daqreader), "ingest_epochfiles", None)
    return method is ndi_daq_reader_mfdaq.ingest_epochfiles


def _resolve_workers(override: int | None) -> int:
    """Worker count for this call, following NDI's parallel preferences."""
    from ndi.fun.utils import parallelWorkers

    if override is None:
        return parallelWorkers()
    if override < 1:
        return 0  # forced serial
    return parallelWorkers(numberOfWorkers=override)


def _detach(obj: Any) -> Any:
    """A shallow copy of *obj* with its session reference cleared."""
    if obj is None:
        return None
    clone = copy.copy(obj)
    if hasattr(clone, "_session"):
        clone._session = None
    return clone


def _detached_readers(daqreader: Any, daqmetadatareaders: list[Any]) -> tuple[Any, list] | None:
    """Session-free, picklable copies of the readers, or None to run serially."""
    reader = _detach(daqreader)
    mreaders = [_detach(m) for m in daqmetadatareaders]
    try:
        pickle.dumps((reader, mreaders))
    except Exception as exc:  # noqa: BLE001 - any pickling failure means "run serially"
        warnings.warn(
            f"The DAQ readers cannot be sent to worker processes ({exc}). Ingesting serially.",
            stacklevel=3,
        )
        return None
    return reader, mreaders
