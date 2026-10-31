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
import multiprocessing
import pickle
import warnings
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

from pydantic import ConfigDict, validate_call

__all__ = ["ingestEpochDocuments", "ingest_epoch_documents"]


@validate_call(config=ConfigDict(arbitrary_types_allowed=True))
def ingestEpochDocuments(  # noqa: N802 (MATLAB mirror)
    daqreader: Any,
    daqmetadatareaders: list[Any],
    epochFiles: list[list[str]],
    epochIds: list[str],
    ProgressFcn: Callable[[int, int], Any] | None = None,
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
            process after each epoch completes.
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
    """
    num_epochs = len(epochFiles)
    if len(epochIds) != num_epochs:
        raise ValueError("EPOCHFILES and EPOCHIDS must have the same number of entries.")

    docs_per_epoch: list[list[Any]] = [[] for _ in range(num_epochs)]
    done = 0

    def tick() -> None:
        nonlocal done
        done += 1
        if ProgressFcn is not None:
            try:
                ProgressFcn(done, num_epochs)
            except Exception as exc:  # noqa: BLE001 - progress must never break an ingest
                warnings.warn(f"Progress reporting failed: {exc}", stacklevel=3)

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
        executor = ProcessPoolExecutor(
            max_workers=min(number_of_workers, num_epochs), mp_context=ctx
        )
        try:
            futures = {
                executor.submit(_ingestOneEpoch, reader, mreaders, ef, eid): k
                for k, (ef, eid) in enumerate(zip(epochFiles, epochIds))
            }
            for future in as_completed(futures):
                docs_per_epoch[futures[future]] = future.result()
                tick()
        except BaseException:
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        executor.shutdown(wait=True)
        return docs_per_epoch, True

    for k, (ef, eid) in enumerate(zip(epochFiles, epochIds)):
        docs_per_epoch[k] = _ingestOneEpoch(daqreader, daqmetadatareaders, ef, eid)
        tick()
    return docs_per_epoch, False


#: Snake-case alias for MATLAB's name; one function under two names.
ingest_epoch_documents = ingestEpochDocuments


def _ingestOneEpoch(  # noqa: N802 (mirrors MATLAB's local function)
    daqreader: Any, daqmetadatareaders: list[Any], ef: list[str], epoch_id: str
) -> list[Any]:
    """Create the documents for a single epoch (no database access)."""
    docs: list[Any] = []
    if daqreader is not None:
        new_d = daqreader.ingest_epochfiles(ef, epoch_id)
        docs.extend(new_d if isinstance(new_d, list) else [new_d])
    for mreader in daqmetadatareaders:
        new_d = mreader.ingest_epochfiles(ef, epoch_id)
        docs.extend(new_d if isinstance(new_d, list) else [new_d])
    return docs


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
