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
from queue import Empty
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
        Completed epochs are reported as they finish, so ProgressFcn may see
        epochs out of order, but the returned list is always in epoch order.
        Within-epoch progress travels from the workers on a
        ``multiprocessing.Manager`` queue (MATLAB uses a DataQueue) that the
        caller drains while it waits.
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

    # only readers using ndi_daq_reader_mfdaq's ingest_epochfiles take a
    # ProgressFcn; any other reader reports per epoch only
    within_epoch = ProgressFcn is not None and _reader_reports_progress(daqreader)

    number_of_workers = 0
    if num_epochs > 1:
        number_of_workers = _resolve_workers(NumberOfWorkers)

    payload = None
    if number_of_workers > 0:
        payload = _detached_readers(daqreader, daqmetadatareaders)
        if payload is None:
            number_of_workers = 0

    if number_of_workers > 0:
        reader, mreaders = payload
        ctx = multiprocessing.get_context("spawn")
        manager = ctx.Manager() if within_epoch else None
        queue = manager.Queue() if manager is not None else None

        def drain() -> None:
            while queue is not None:
                try:
                    k, fraction = queue.get_nowait()
                except Empty:
                    return
                update_progress(k, fraction)

        executor = ProcessPoolExecutor(
            max_workers=min(number_of_workers, num_epochs), mp_context=ctx
        )
        try:
            futures = {
                executor.submit(_ingestOneEpoch, reader, mreaders, ef, eid, queue, k): k
                for k, (ef, eid) in enumerate(zip(epochFiles, epochIds))
            }
            pending = set(futures)
            while pending:
                finished, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                drain()
                for future in finished:
                    docs_per_epoch[futures[future]] = future.result()
                    update_progress(futures[future], 1)
            drain()
        except BaseException:
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        finally:
            if manager is not None:
                manager.shutdown()
        executor.shutdown(wait=True)
        return docs_per_epoch, True

    for k, (ef, eid) in enumerate(zip(epochFiles, epochIds)):
        epoch_progress = None
        if within_epoch:
            epoch_progress = functools.partial(update_progress, k)
        docs_per_epoch[k] = _ingestOneEpoch(
            daqreader, daqmetadatareaders, ef, eid, epoch_progress=epoch_progress
        )
        update_progress(k, 1)
    return docs_per_epoch, False


#: Snake-case alias for MATLAB's name; one function under two names.
ingest_epoch_documents = ingestEpochDocuments


def _ingestOneEpoch(  # noqa: N802 (mirrors MATLAB's local function)
    daqreader: Any,
    daqmetadatareaders: list[Any],
    ef: list[str],
    epoch_id: str,
    queue: Any = None,
    k: int = 0,
    epoch_progress: Callable[[float], Any] | None = None,
) -> list[Any]:
    """Create the documents for a single epoch (no database access).

    In a worker process, progress is sent as ``(k, fraction)`` on QUEUE; in
    the calling process it goes to EPOCH_PROGRESS.
    """
    if queue is not None:
        epoch_progress = functools.partial(_send_progress, queue, k)
    docs: list[Any] = []
    if daqreader is not None:
        if epoch_progress is None:
            new_d = daqreader.ingest_epochfiles(ef, epoch_id)
        else:
            new_d = daqreader.ingest_epochfiles(ef, epoch_id, ProgressFcn=epoch_progress)
        docs.extend(new_d if isinstance(new_d, list) else [new_d])
    for mreader in daqmetadatareaders:
        new_d = mreader.ingest_epochfiles(ef, epoch_id)
        docs.extend(new_d if isinstance(new_d, list) else [new_d])
    return docs


def _send_progress(queue: Any, k: int, fraction: float) -> None:
    """Send epoch K's progress from a worker process to the caller."""
    queue.put((k, fraction))


def _reader_reports_progress(daqreader: Any) -> bool:
    """Does DAQREADER's ingest_epochfiles take a ProgressFcn?

    True when the method is ndi_daq_reader_mfdaq's own; a subclass that
    overrides ingest_epochfiles keeps its own signature and is called without
    one.
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
